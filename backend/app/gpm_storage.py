"""GPMHeatmap 最终 SQLite schema 与资源目录。

GPMHeatmap 仍处于 Demo 阶段，schema 不提供历史迁移。检测到旧 Demo 数据库时会
一次性清空独立的 GPM 数据和资源，再创建当前唯一 schema；主业务数据库不受影响。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
from pathlib import Path


GPM_SCHEMA_VERSION = 1

_LOG = logging.getLogger("pixelcomp")
_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[Path] = set()
_FINAL_TABLES = {
    "gpm_uploads",
    "gpm_upload_maps",
    "gpm_points",
    "gpm_map_definitions",
    "gpm_metric_scales",
    "gpm_metric_scale_sets",
    "gpm_metric_scale_set_items",
    "gpm_map_scale_set_bindings",
}
_FINAL_COLUMNS = {
    "gpm_uploads": {
        "id", "batch_id", "branch_tag", "batch_url", "captured_at",
        "captured_at_epoch", "p4_version", "platform", "shading_quality",
        "source_sha256", "created_at",
    },
    "gpm_upload_maps": {
        "id", "upload_id", "map_name", "show_direction", "heat_map_json",
        "trend_json",
    },
    "gpm_points": {
        "id", "upload_map_id", "point_index", "screenshot_id", "point_key",
        "position_x", "position_y", "direction_x", "direction_y",
        "heat_map_data_json", "trend_data_json", "detail_data_json",
        "screenshot_path", "thumbnail_path",
    },
    "gpm_map_definitions": {
        "map_name", "map_id", "description", "origin_x", "origin_y", "range_x",
        "range_y", "x_reverse", "y_reverse", "image_path", "image_width",
        "image_height", "revision", "created_at", "updated_at",
    },
    "gpm_metric_scales": {
        "id", "name", "segments_json", "revision", "created_at", "updated_at",
    },
    "gpm_metric_scale_sets": {
        "id", "name", "revision", "created_at", "updated_at",
    },
    "gpm_metric_scale_set_items": {"scale_set_id", "metric_key", "scale_id"},
    "gpm_map_scale_set_bindings": {
        "map_name", "platform", "shading_quality", "scale_set_id",
    },
}


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


def _has_user_tables(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone())


def _is_final_schema(connection: sqlite3.Connection) -> bool:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables != _FINAL_TABLES:
        return False
    return all(
        {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
        == expected_columns
        for table_name, expected_columns in _FINAL_COLUMNS.items()
    )


def _reset_demo_storage(database: Path) -> None:
    """删除旧 GPM Demo 数据；这是唯一的版本切换策略，不保留迁移分支。"""

    for candidate in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            _LOG.exception("无法删除旧 GPMHeatmap Demo 数据库文件: %s", candidate)
            raise
    assets = gpm_assets_dir().resolve()
    if assets.exists():
        shutil.rmtree(assets)
    _LOG.info("已清空旧 GPMHeatmap Demo 数据并切换到最终 schema v%d", GPM_SCHEMA_VERSION)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        f"""
        PRAGMA journal_mode=WAL;
        PRAGMA busy_timeout=5000;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS gpm_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL UNIQUE,
            branch_tag TEXT NOT NULL DEFAULT 'main',
            batch_url TEXT,
            captured_at TEXT NOT NULL,
            captured_at_epoch INTEGER NOT NULL,
            p4_version INTEGER NOT NULL CHECK(p4_version >= 0),
            platform TEXT NOT NULL CHECK(platform IN ('Android', 'IOS', 'Windows')),
            shading_quality INTEGER NOT NULL CHECK(shading_quality BETWEEN 0 AND 5),
            source_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gpm_upload_maps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER NOT NULL REFERENCES gpm_uploads(id) ON DELETE CASCADE,
            map_name TEXT NOT NULL,
            show_direction INTEGER NOT NULL DEFAULT 1 CHECK(show_direction IN (0, 1)),
            heat_map_json TEXT NOT NULL,
            trend_json TEXT NOT NULL,
            UNIQUE(upload_id, map_name)
        );

        CREATE TABLE IF NOT EXISTS gpm_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_map_id INTEGER NOT NULL REFERENCES gpm_upload_maps(id) ON DELETE CASCADE,
            point_index INTEGER NOT NULL,
            screenshot_id TEXT NOT NULL,
            point_key TEXT,
            position_x REAL NOT NULL,
            position_y REAL NOT NULL,
            direction_x REAL NOT NULL,
            direction_y REAL NOT NULL,
            heat_map_data_json TEXT NOT NULL,
            trend_data_json TEXT NOT NULL,
            detail_data_json TEXT NOT NULL,
            screenshot_path TEXT NOT NULL,
            thumbnail_path TEXT NOT NULL,
            UNIQUE(upload_map_id, point_index),
            UNIQUE(upload_map_id, screenshot_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_gpm_points_stable_key
            ON gpm_points(upload_map_id, point_key) WHERE point_key IS NOT NULL;

        CREATE TABLE IF NOT EXISTS gpm_map_definitions (
            map_name TEXT PRIMARY KEY,
            map_id INTEGER NOT NULL UNIQUE CHECK(map_id >= 0),
            description TEXT NOT NULL DEFAULT '',
            origin_x REAL NOT NULL,
            origin_y REAL NOT NULL,
            range_x REAL NOT NULL CHECK(range_x > 0),
            range_y REAL NOT NULL CHECK(range_y > 0),
            x_reverse INTEGER NOT NULL DEFAULT 0 CHECK(x_reverse IN (0, 1)),
            y_reverse INTEGER NOT NULL DEFAULT 1 CHECK(y_reverse IN (0, 1)),
            image_path TEXT,
            image_width INTEGER CHECK(image_width IS NULL OR image_width > 0),
            image_height INTEGER CHECK(image_height IS NULL OR image_height > 0),
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(
                (image_path IS NULL AND image_width IS NULL AND image_height IS NULL)
                OR (image_path IS NOT NULL AND image_width IS NOT NULL AND image_height IS NOT NULL)
            )
        );

        CREATE TABLE IF NOT EXISTS gpm_metric_scales (
            id INTEGER PRIMARY KEY CHECK(id >= 0),
            name TEXT NOT NULL UNIQUE,
            segments_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gpm_metric_scale_sets (
            id INTEGER PRIMARY KEY CHECK(id >= 0),
            name TEXT NOT NULL UNIQUE,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gpm_metric_scale_set_items (
            scale_set_id INTEGER NOT NULL REFERENCES gpm_metric_scale_sets(id) ON DELETE CASCADE,
            metric_key TEXT NOT NULL,
            scale_id INTEGER NOT NULL REFERENCES gpm_metric_scales(id) ON DELETE RESTRICT,
            PRIMARY KEY(scale_set_id, metric_key)
        );

        CREATE TABLE IF NOT EXISTS gpm_map_scale_set_bindings (
            map_name TEXT NOT NULL REFERENCES gpm_map_definitions(map_name) ON DELETE CASCADE,
            platform TEXT NOT NULL CHECK(platform IN ('Android', 'IOS', 'Windows')),
            shading_quality INTEGER NOT NULL CHECK(shading_quality BETWEEN 0 AND 5),
            scale_set_id INTEGER NOT NULL REFERENCES gpm_metric_scale_sets(id) ON DELETE RESTRICT,
            PRIMARY KEY(map_name, platform, shading_quality)
        );

        CREATE INDEX IF NOT EXISTS ix_gpm_upload_scope
            ON gpm_uploads(branch_tag, platform, shading_quality, captured_at_epoch DESC);
        CREATE INDEX IF NOT EXISTS ix_gpm_upload_map_name ON gpm_upload_maps(map_name, upload_id);
        CREATE INDEX IF NOT EXISTS ix_gpm_point_upload_map ON gpm_points(upload_map_id, point_index);
        CREATE INDEX IF NOT EXISTS ix_gpm_point_key ON gpm_points(point_key);
        CREATE INDEX IF NOT EXISTS ix_gpm_scale_item_scale ON gpm_metric_scale_set_items(scale_id);
        CREATE INDEX IF NOT EXISTS ix_gpm_binding_set ON gpm_map_scale_set_bindings(scale_set_id, map_name);

        PRAGMA user_version={GPM_SCHEMA_VERSION};
        """
    )


def initialize_gpm_database() -> None:
    """初始化唯一最终 schema；旧 Demo schema 会被整体重建。"""

    database = gpm_db_path().resolve()
    with _INITIALIZE_LOCK:
        if database in _INITIALIZED_DATABASES and database.is_file():
            return
        database.parent.mkdir(parents=True, exist_ok=True)
        reset_required = False
        if database.exists():
            probe = sqlite3.connect(database, timeout=30)
            try:
                version = int(probe.execute("PRAGMA user_version").fetchone()[0])
                reset_required = _has_user_tables(probe) and (
                    version != GPM_SCHEMA_VERSION or not _is_final_schema(probe)
                )
            finally:
                probe.close()
        if reset_required:
            _reset_demo_storage(database)

        gpm_assets_dir().mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database, timeout=30)
        try:
            _create_schema(connection)
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
