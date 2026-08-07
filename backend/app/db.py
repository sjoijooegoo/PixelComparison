import json
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(
    os.environ.get("PIXELCOMP_DATA_DIR")
    or (Path(__file__).resolve().parent.parent / "data")
)
# db 与 images 可分别覆盖:SQLite 库务必放**本地磁盘**(网络共享盘 SMB/NFS 上
# SQLite 文件锁不可靠、WAL 易异常,会导致读写不一致甚至损坏);图片是普通文件,
# 可单独放共享盘。都不设时落在 DATA_DIR 下(行为与旧版一致)。
DB_PATH = Path(os.environ.get("PIXELCOMP_DB_PATH") or (DATA_DIR / "shotdiff.db"))
IMAGES_DIR = Path(os.environ.get("PIXELCOMP_IMAGES_DIR") or (DATA_DIR / "images"))
# 缩略图是可重建缓存，默认跟随 SQLite 放本地磁盘，避免在共享盘/按需召回盘上
# 一边读取原图一边并发写 WebP，拖垮请求线程。需要时可单独覆盖。
THUMB_DIR = Path(os.environ.get("PIXELCOMP_THUMB_DIR") or (DB_PATH.parent / "thumbs"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):
    """WAL:读写不互相阻塞;busy_timeout:写锁时等待而非立即报错(多人并发更稳)。"""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 新增列(随上报 manifest 升级而来);旧库存量数据取 NULL,不重建库。
_MAP_BUILD_DETAIL_JSON_PATHS = {
    "lightmap_all_mips_bytes": ("lightmapTextures", "allMipsBytes"),
    "hue_all_mips_bytes": ("hueTextures", "allMipsBytes"),
    "shadowmap_all_mips_bytes": ("shadowmapTextures", "allMipsBytes"),
    "mesh_map_build_data_bytes": ("meshMapBuildDataBytes",),
    "precomputed_light_volume_bytes": ("precomputedLightVolumeBytes",),
    "precomputed_reflection_volume_bytes": ("precomputedReflectionVolumeBytes",),
    "volumetric_lightmap_bytes": ("volumetricLightmapBytes",),
    "light_build_data_bytes": ("lightBuildDataBytes",),
    "reflection_capture_bytes": ("reflectionCaptureBytes",),
    "precomputed_instanced_ilc_bytes": ("precomputedInstancedILCBytes",),
    "precomputed_instanced_pr_bytes": ("precomputedInstancedPRBytes",),
    "lightmap_resource_cluster_bytes": ("lightmapResourceClusterBytes",),
}

_NEW_COLUMNS = {
    "batches": {
        "batch_url": "VARCHAR",
        "resolution": "VARCHAR",
        "capture_type": "VARCHAR",
        "levelsequence_name": "VARCHAR",
        "levelsequence_path": "VARCHAR",
        "shading_quality": "INTEGER",
    },
    "screenshots": {
        "frame_index": "INTEGER",
        "camera": "JSON",
        "cache_version": "VARCHAR",
    },
    "comparison_items": {
        "cache_version": "VARCHAR",
    },
    "map_build_registries": {
        name: "BIGINT" for name in _MAP_BUILD_DETAIL_JSON_PATHS
    },
}


def _relax_p4_nullable() -> None:
    """放宽 batches.p4_version 的 NOT NULL,允许未上报 p4 版本。

    SQLite 不支持直接改列约束,需按现有列重建表(仅把 p4_version 改为可空,
    其余列原样保留),再拷回数据。已可空则跳过。
    """
    with engine.begin() as conn:
        info = conn.execute(text("PRAGMA table_info(batches)")).fetchall()
        if not info:
            return  # 表还没建,create_all 会用新模型(可空)建好
        p4 = next((r for r in info if r[1] == "p4_version"), None)
        if p4 is None or p4[3] == 0:
            return  # 不存在或已可空(notnull 标志=0)
        # PRAGMA table_info 列:cid, name, type, notnull, dflt_value, pk
        defs = []
        for _cid, name, ctype, notnull, dflt, pk in info:
            piece = f'"{name}" {ctype or ""}'.rstrip()
            if pk:
                piece += " PRIMARY KEY"
            elif notnull and name != "p4_version":
                piece += " NOT NULL"
            if dflt is not None:
                piece += f" DEFAULT {dflt}"
            defs.append(piece)
        cols = ", ".join(f'"{r[1]}"' for r in info)
        conn.execute(text("ALTER TABLE batches RENAME TO _batches_old"))
        conn.execute(text(f"CREATE TABLE batches ({', '.join(defs)})"))
        conn.execute(text(f"INSERT INTO batches ({cols}) SELECT {cols} FROM _batches_old"))
        conn.execute(text("DROP TABLE _batches_old"))


def _nested_json_value(data: object, path: tuple[str, ...]) -> int:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    try:
        return int(current or 0)
    except (TypeError, ValueError):
        return 0


def _backfill_map_build_registry_details() -> int:
    """从保留的原始 JSON 一次性回填旧快照缺失的趋势指标。"""

    columns = tuple(_MAP_BUILD_DETAIL_JSON_PATHS)
    with engine.begin() as conn:
        existing = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(map_build_registries)"))
        }
        if not set(columns).issubset(existing):
            return 0

        missing = " OR ".join(f'r."{column}" IS NULL' for column in columns)
        snapshots = conn.execute(
            text(
                "SELECT DISTINCT s.batch_id, s.raw_payload "
                "FROM map_build_snapshots AS s "
                "JOIN map_build_registries AS r ON r.batch_id = s.batch_id "
                f"WHERE {missing}"
            )
        ).all()
        if not snapshots:
            return 0

        assignments = ", ".join(f'"{column}" = :{column}' for column in columns)
        update_stmt = text(
            f"UPDATE map_build_registries SET {assignments} "
            "WHERE batch_id = :batch_id AND path = :path"
        )
        updated = 0
        logger = logging.getLogger("pixelcomp")
        for batch_id, raw_payload in snapshots:
            try:
                payload = (
                    json.loads(raw_payload)
                    if isinstance(raw_payload, (str, bytes, bytearray))
                    else raw_payload
                )
                registries = payload.get("registries", []) or []
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning("跳过无法解析的烘培数据回填 batch=%s: %s", batch_id, exc)
                continue

            values = []
            for registry in registries:
                if not isinstance(registry, dict) or not registry.get("path"):
                    continue
                own = registry.get("self") or {}
                breakdown = own.get("breakdown", {}) if isinstance(own, dict) else {}
                values.append(
                    {
                        "batch_id": batch_id,
                        "path": registry["path"],
                        **{
                            column: _nested_json_value(breakdown, json_path)
                            for column, json_path in _MAP_BUILD_DETAIL_JSON_PATHS.items()
                        },
                    }
                )
            if values:
                result = conn.execute(update_stmt, values)
                updated += max(result.rowcount or 0, 0)
        return updated


def migrate_columns() -> None:
    """轻量迁移:缺失的新列用 ALTER TABLE ADD COLUMN 补上(SQLite 支持)。"""
    with engine.begin() as conn:
        for table, cols in _NEW_COLUMNS.items():
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            if not existing:
                continue  # 表还没建,create_all 会带上全部列
            for name, sqltype in cols.items():
                if name not in existing:
                    conn.execute(
                        text(f'ALTER TABLE {table} ADD COLUMN "{name}" {sqltype}')
                    )
    backfilled = _backfill_map_build_registry_details()
    if backfilled:
        logging.getLogger("pixelcomp").info(
            "已回填烘培趋势静态指标: %s 条 registry", backfilled
        )
    _relax_p4_nullable()
    # 同一对(batch, ref)至多一条对比;防并发重复(应用层加锁兜底)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_pair "
                "ON comparisons(batch_id, ref_batch_id)"
            ))
    except Exception:
        pass  # 历史遗留重复数据时跳过,不阻断启动
    # 同一批次内 scene_name 唯一;防并发同名上传重复(应用层 409 兜底)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_screenshot_batch_scene "
                "ON screenshots(batch_id, scene_name)"
            ))
    except Exception:
        pass  # 历史遗留重复数据时跳过,不阻断启动
