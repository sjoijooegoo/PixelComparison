"""GPMHeatmap 独立 SQLite 与资源目录配置。

路径和数据库初始化集中在这里，避免上传 API、备份调度器各自解释同一组环境变量。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path


_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[Path] = set()


def data_dir() -> Path:
    return Path(
        os.environ.get("PIXELCOMP_DATA_DIR")
        or (Path(__file__).resolve().parent.parent / "data")
    )


def gpm_root() -> Path:
    return Path(os.environ.get("PIXELCOMP_GPM_DIR") or (data_dir() / "gpm_heatmap"))


def gpm_db_path() -> Path:
    return Path(os.environ.get("PIXELCOMP_GPM_DB_PATH") or (gpm_root() / "gpm_heatmap.db"))


def gpm_assets_dir() -> Path:
    return Path(os.environ.get("PIXELCOMP_GPM_ASSETS_DIR") or (gpm_root() / "assets"))


def initialize_gpm_database() -> None:
    """幂等初始化独立 SQLite；运行时解析路径以支持部署覆盖和隔离测试。"""

    database = gpm_db_path().resolve()
    with _INITIALIZE_LOCK:
        if database in _INITIALIZED_DATABASES and database.is_file():
            return
        database.parent.mkdir(parents=True, exist_ok=True)
        gpm_assets_dir().mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database, timeout=30)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA busy_timeout=5000;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS gpm_uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    branch_tag TEXT NOT NULL DEFAULT 'main',
                    batch_url TEXT,
                    captured_at TEXT NOT NULL,
                    p4_version INTEGER,
                    platform TEXT NOT NULL,
                    shading_quality INTEGER NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(branch_tag, batch_id)
                );

                CREATE TABLE IF NOT EXISTS gpm_scenes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    upload_id INTEGER NOT NULL REFERENCES gpm_uploads(id) ON DELETE CASCADE,
                    scene_id TEXT NOT NULL,
                    pic_id INTEGER,
                    show_z INTEGER NOT NULL DEFAULT 0,
                    show_direction INTEGER NOT NULL DEFAULT 1,
                    x_reverse INTEGER NOT NULL DEFAULT 0,
                    y_reverse INTEGER NOT NULL DEFAULT 1,
                    heat_map_json TEXT NOT NULL,
                    trend_json TEXT NOT NULL,
                    UNIQUE(upload_id, scene_id)
                );

                CREATE TABLE IF NOT EXISTS gpm_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scene_row_id INTEGER NOT NULL REFERENCES gpm_scenes(id) ON DELETE CASCADE,
                    point_index INTEGER NOT NULL,
                    screenshot_id TEXT NOT NULL,
                    point_key TEXT,
                    position_json TEXT NOT NULL,
                    direction_json TEXT NOT NULL,
                    view_json TEXT NOT NULL,
                    heat_map_data_json TEXT NOT NULL,
                    trend_data_json TEXT NOT NULL,
                    detail_data_json TEXT NOT NULL,
                    screenshot_path TEXT,
                    thumbnail_path TEXT,
                    UNIQUE(scene_row_id, point_index),
                    UNIQUE(scene_row_id, screenshot_id)
                );

                CREATE TABLE IF NOT EXISTS gpm_map_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scene_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    image_width INTEGER NOT NULL,
                    image_height INTEGER NOT NULL,
                    origin_x REAL NOT NULL,
                    origin_y REAL NOT NULL,
                    range_x REAL NOT NULL,
                    range_y REAL NOT NULL,
                    x_reverse INTEGER NOT NULL DEFAULT 0,
                    y_reverse INTEGER NOT NULL DEFAULT 1,
                    color_ranges_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(scene_id, revision)
                );

                CREATE INDEX IF NOT EXISTS ix_gpm_upload_scope
                    ON gpm_uploads(branch_tag, platform, shading_quality, captured_at DESC);
                CREATE INDEX IF NOT EXISTS ix_gpm_scene_lookup
                    ON gpm_scenes(scene_id, upload_id);
                CREATE INDEX IF NOT EXISTS ix_gpm_point_scene
                    ON gpm_points(scene_row_id, point_index);
                CREATE INDEX IF NOT EXISTS ix_gpm_point_key
                    ON gpm_points(point_key);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_gpm_active_map
                    ON gpm_map_revisions(scene_id) WHERE active = 1;
                """
            )
            connection.commit()
            _INITIALIZED_DATABASES.add(database)
        finally:
            connection.close()


def connect_gpm_database() -> sqlite3.Connection:
    initialize_gpm_database()
    connection = sqlite3.connect(gpm_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection
