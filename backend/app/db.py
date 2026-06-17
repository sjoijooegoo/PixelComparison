import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(
    os.environ.get("PIXELCOMP_DATA_DIR")
    or (Path(__file__).resolve().parent.parent / "data")
)
IMAGES_DIR = DATA_DIR / "images"
DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DATA_DIR / 'shotdiff.db'}",
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
_NEW_COLUMNS = {
    "batches": {
        "batch_url": "VARCHAR",
        "resolution": "VARCHAR",
        "capture_type": "VARCHAR",
        "levelsequence_name": "VARCHAR",
        "levelsequence_path": "VARCHAR",
    },
    "screenshots": {
        "frame_index": "INTEGER",
        "camera": "JSON",
    },
}


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
    # 同一对(batch, ref)至多一条对比;防并发重复(应用层加锁兜底)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_pair "
                "ON comparisons(batch_id, ref_batch_id)"
            ))
    except Exception:
        pass  # 历史遗留重复数据时跳过,不阻断启动
