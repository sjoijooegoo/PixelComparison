import json
import logging
import os
import re
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
        "branch_tag": "VARCHAR NOT NULL DEFAULT 'main'",
        "batch_url": "VARCHAR",
        "resolution": "VARCHAR",
        "capture_type": "VARCHAR",
        "levelsequence_name": "VARCHAR",
        "levelsequence_path": "VARCHAR",
        "shading_quality": "INTEGER",
        "manifest_format_version": "INTEGER",
        "source_manifest_sha256": "VARCHAR(64)",
    },
    "screenshots": {
        "frame_index": "INTEGER",
        "camera": "JSON",
        "cache_version": "VARCHAR",
    },
    "baselines": {
        "branch_tag": "VARCHAR NOT NULL DEFAULT 'main'",
        "source_quality_run_id": "INTEGER",
    },
    "comparisons": {
        "current_quality_run_id": "INTEGER",
        "reference_quality_run_id": "INTEGER",
        "scope_status": "VARCHAR NOT NULL DEFAULT 'valid'",
    },
    "comparison_items": {
        "cache_version": "VARCHAR",
    },
    "map_build_registries": {
        name: "BIGINT" for name in _MAP_BUILD_DETAIL_JSON_PATHS
    },
}


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


_CREATE_TABLE_PREFIX = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'(?:"(?:[^"]|"")*"|`[^`]*`|\[[^\]]*\]|[^\s(]+)',
    re.IGNORECASE,
)
_STALE_BATCH_REFERENCE = re.compile(
    r'(\bREFERENCES\s+)(?:"_batches_old"|`_batches_old`|'
    r"\[_batches_old\]|_batches_old)(?=\s|\()",
    re.IGNORECASE,
)


def _repair_stale_batch_foreign_keys() -> list[str]:
    """修复旧版 v2 迁移中断后指向已删除临时表的外键。

    已发布过的迁移曾先把 ``batches`` 重命名为 ``_batches_old``。
    SQLite 会连带重写所有子表的父表名；临时表删除后，第一次启动会在
    ``foreign_key_check`` 失败，但之前的表结构事务已经提交。这里仅重建实际
    指向该临时表的子表，并保留其数据、索引和触发器，使迁移可以安全续跑。
    """
    repaired: list[str] = []
    with engine.begin() as conn:
        if int(conn.scalar(text("PRAGMA foreign_keys")) or 0):
            raise RuntimeError("修复迁移外键前必须关闭 SQLite foreign_keys")

        tables = list(conn.execute(text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
        )))
        for table_name, create_sql in tables:
            quoted_table = _quote_identifier(table_name)
            foreign_keys = list(conn.execute(text(
                f"PRAGMA foreign_key_list({quoted_table})"
            )))
            if not any(row[2] == "_batches_old" for row in foreign_keys):
                continue

            prefix = _CREATE_TABLE_PREFIX.match(create_sql)
            repaired_sql = _STALE_BATCH_REFERENCE.sub(r"\1batches", create_sql)
            if prefix is None or repaired_sql == create_sql:
                raise RuntimeError(f"无法安全修复表 {table_name} 的旧批次外键")

            temp_name = f"_fk_repair_{table_name}"
            quoted_temp = _quote_identifier(temp_name)
            repaired_sql = (
                f"CREATE TABLE {quoted_temp}" + repaired_sql[prefix.end():]
            )
            schema_objects = list(conn.execute(text(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE tbl_name = :table_name "
                "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
            ), {"table_name": table_name}))
            columns = [
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({quoted_table})"))
            ]
            if not columns:
                raise RuntimeError(f"无法读取待修复表 {table_name} 的列")
            column_list = ", ".join(_quote_identifier(name) for name in columns)
            old_count = int(conn.scalar(text(
                f"SELECT COUNT(*) FROM {quoted_table}"
            )) or 0)

            conn.execute(text(f"DROP TABLE IF EXISTS {quoted_temp}"))
            conn.exec_driver_sql(repaired_sql)
            conn.execute(text(
                f"INSERT INTO {quoted_temp} ({column_list}) "
                f"SELECT {column_list} FROM {quoted_table}"
            ))
            new_count = int(conn.scalar(text(
                f"SELECT COUNT(*) FROM {quoted_temp}"
            )) or 0)
            if old_count != new_count:
                raise RuntimeError(
                    f"修复表 {table_name} 数据数量不一致: "
                    f"old={old_count} new={new_count}"
                )

            conn.execute(text(f"DROP TABLE {quoted_table}"))
            conn.execute(text(
                f"ALTER TABLE {quoted_temp} RENAME TO {quoted_table}"
            ))
            for _object_type, _object_name, object_sql in schema_objects:
                conn.exec_driver_sql(object_sql)
            repaired.append(table_name)

        remaining = []
        for table_name, _create_sql in tables:
            if table_name in repaired:
                foreign_keys = list(conn.execute(text(
                    f"PRAGMA foreign_key_list({_quote_identifier(table_name)})"
                )))
                if any(row[2] == "_batches_old" for row in foreign_keys):
                    remaining.append(table_name)
        if remaining:
            raise RuntimeError(f"旧批次外键修复不完整: {remaining}")

    if repaired:
        logging.getLogger("pixelcomp").warning(
            "检测到上次中断的多画质迁移，已修复外键表: %s",
            ", ".join(repaired),
        )
    return repaired


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
        # 必须先创建新表再替换原表。若先把父表 batches 改名，SQLite 3.26+
        # 会把所有子表外键自动改写为临时表名，临时表删除后外键即悬空。
        conn.execute(text("DROP TABLE IF EXISTS _batches_nullable"))
        conn.execute(text(f"CREATE TABLE _batches_nullable ({', '.join(defs)})"))
        conn.execute(text(
            f"INSERT INTO _batches_nullable ({cols}) SELECT {cols} FROM batches"
        ))
        conn.execute(text("DROP TABLE batches"))
        conn.execute(text("ALTER TABLE _batches_nullable RENAME TO batches"))


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
    _repair_stale_batch_foreign_keys()
    _relax_p4_nullable()
    with engine.begin() as conn:
        tables = set(conn.scalars(text(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )))
        if "batches" in tables:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_batches_branch_tag "
                "ON batches(branch_tag)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_batches_branch_scene_created "
                "ON batches(branch_tag, scene_id, created_at)"
            ))
        if "baselines" in tables:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_baselines_branch_tag "
                "ON baselines(branch_tag)"
            ))
    with engine.begin() as conn:
        tables = set(conn.scalars(text(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )))
        if "screenshots" in tables:
            columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(screenshots)"))
            }
            if "quality_run_id" in columns:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_screenshot_run_scene "
                    "ON screenshots(quality_run_id, scene_name)"
                ))


CURRENT_SCHEMA_VERSION = 2


def _database_state() -> tuple[int, set[str]]:
    with engine.connect() as conn:
        version = int(conn.scalar(text("PRAGMA user_version")) or 0)
        tables = set(conn.scalars(text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )))
    return version, tables


def _rebuild_screenshots_for_quality_runs() -> None:
    """把旧截图唯一键升级为 (quality_run_id, scene_name)，保留行 id/路径。"""
    with engine.begin() as conn:
        columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(screenshots)"))
        }
        if not columns or "quality_run_id" in columns:
            return
        conn.execute(text("""
            CREATE TABLE _screenshots_multi_quality (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                batch_id VARCHAR NOT NULL,
                quality_run_id INTEGER,
                scene_name VARCHAR NOT NULL,
                path VARCHAR,
                source_relative_path VARCHAR,
                upload_status VARCHAR NOT NULL DEFAULT 'ready',
                sha256 VARCHAR(64),
                byte_size BIGINT,
                cache_version VARCHAR,
                frame_index INTEGER,
                camera JSON,
                FOREIGN KEY(batch_id) REFERENCES batches (id),
                FOREIGN KEY(quality_run_id) REFERENCES quality_runs (id),
                CONSTRAINT uq_screenshot_run_scene UNIQUE (quality_run_id, scene_name)
            )
        """))
        conn.execute(text("""
            INSERT INTO _screenshots_multi_quality (
                id, batch_id, quality_run_id, scene_name, path,
                source_relative_path, upload_status, sha256, byte_size,
                cache_version, frame_index, camera
            )
            SELECT s.id, s.batch_id, q.id, s.scene_name, s.path,
                   NULL, 'ready', NULL, NULL,
                   s.cache_version, s.frame_index, s.camera
            FROM screenshots AS s
            JOIN quality_runs AS q ON q.batch_id = s.batch_id
        """))
        old_count = int(conn.scalar(text("SELECT COUNT(*) FROM screenshots")) or 0)
        new_count = int(conn.scalar(text(
            "SELECT COUNT(*) FROM _screenshots_multi_quality"
        )) or 0)
        if old_count != new_count:
            raise RuntimeError(
                f"截图迁移数量不一致: old={old_count} new={new_count}"
            )
        conn.execute(text("DROP TABLE screenshots"))
        conn.execute(text(
            "ALTER TABLE _screenshots_multi_quality RENAME TO screenshots"
        ))
        conn.execute(text(
            "CREATE INDEX ix_screenshots_batch_id ON screenshots(batch_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_screenshots_quality_run_id ON screenshots(quality_run_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_screenshots_scene_name ON screenshots(scene_name)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_screenshots_upload_status ON screenshots(upload_status)"
        ))


def _migrate_multi_quality() -> None:
    """把旧单画质批次映射到唯一 legacy QualityRun，并回填引用。"""
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS uq_comparison_pair"))
        conn.execute(text("""
            INSERT INTO quality_runs (
                batch_id, quality_run_index, shading_quality, tex_quality,
                capture_status, expected_screenshot_count, created_at
            )
            SELECT b.id, 0, COALESCE(b.shading_quality, 4), NULL,
                   'legacy', COUNT(s.id), b.created_at
            FROM batches AS b
            JOIN screenshots AS s ON s.batch_id = b.id
            WHERE NOT EXISTS (
                SELECT 1 FROM quality_runs AS q WHERE q.batch_id = b.id
            )
            GROUP BY b.id
        """))

    _rebuild_screenshots_for_quality_runs()

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE baselines
            SET source_quality_run_id = (
                SELECT q.id FROM quality_runs AS q
                WHERE q.batch_id = baselines.source_batch_id
                ORDER BY q.id LIMIT 1
            )
            WHERE source_quality_run_id IS NULL
        """))
        conn.execute(text("""
            UPDATE comparisons
            SET current_quality_run_id = (
                    SELECT q.id FROM quality_runs AS q
                    WHERE q.batch_id = comparisons.batch_id
                    ORDER BY q.id LIMIT 1
                ),
                reference_quality_run_id = (
                    SELECT q.id FROM quality_runs AS q
                    WHERE q.batch_id = comparisons.ref_batch_id
                    ORDER BY q.id LIMIT 1
                )
        """))
        conn.execute(text("""
            UPDATE comparisons
            SET scope_status = CASE
                WHEN current_quality_run_id IS NOT NULL
                 AND reference_quality_run_id IS NOT NULL
                 AND (SELECT shading_quality FROM quality_runs
                      WHERE id = current_quality_run_id) =
                     (SELECT shading_quality FROM quality_runs
                      WHERE id = reference_quality_run_id)
                THEN 'valid' ELSE 'legacy_incompatible' END
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_quality_pair
            ON comparisons(current_quality_run_id, reference_quality_run_id)
            WHERE current_quality_run_id IS NOT NULL
              AND reference_quality_run_id IS NOT NULL
        """))
        violations = list(conn.execute(text("PRAGMA foreign_key_check")))
        if violations:
            raise RuntimeError(f"数据库迁移外键检查失败: {violations[:5]}")
        check = conn.execute(text("PRAGMA quick_check")).fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError(f"数据库迁移完整性检查失败: {check}")


def initialize_database() -> None:
    """创建/迁移数据库；任何既有库迁移前必须先生成已校验快照。"""
    version, tables = _database_state()
    needs_multi_quality = "batches" in tables and version < CURRENT_SCHEMA_VERSION
    if needs_multi_quality:
        from .backup import create_migration_backup

        backup = create_migration_backup("multi-quality-v2")
        logging.getLogger("pixelcomp").info("数据库迁移前备份完成: %s", backup)

    Base.metadata.create_all(engine)
    migrate_columns()
    if needs_multi_quality:
        _migrate_multi_quality()
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS uq_comparison_pair"))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_quality_pair
            ON comparisons(current_quality_run_id, reference_quality_run_id)
            WHERE current_quality_run_id IS NOT NULL
              AND reference_quality_run_id IS NOT NULL
        """))
        conn.execute(text(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}"))
    logging.getLogger("pixelcomp").info(
        "数据库 schema 已就绪: version=%s", CURRENT_SCHEMA_VERSION
    )
