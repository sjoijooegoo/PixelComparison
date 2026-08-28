"""GPMHeatmap 独立 SQLite 与资源目录配置。

路径和数据库初始化集中在这里，避免上传 API、备份调度器各自解释同一组环境变量。
"""

from __future__ import annotations

import os
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .gpm_scale_expressions import default_scale_segments, segments_from_legacy


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


_SCALE_SET_MIGRATION = "metric-scale-sets-v1"


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone() is not None


def _unique_scale_set_name(connection: sqlite3.Connection, preferred: str) -> str:
    base = preferred.strip()[:100] or "迁移标尺集"
    candidate = base
    suffix = 2
    while connection.execute(
        "SELECT 1 FROM gpm_metric_scale_sets WHERE name = ?", (candidate,)
    ).fetchone():
        tail = f" ({suffix})"
        candidate = f"{base[:100 - len(tail)]}{tail}"
        suffix += 1
    return candidate


def _insert_migrated_scale_set(
    connection: sqlite3.Connection,
    *,
    name: str,
    items: dict[str, int],
    now: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO gpm_metric_scale_sets (name, revision, created_at, updated_at)
        VALUES (?, 1, ?, ?)
        """,
        (_unique_scale_set_name(connection, name), now, now),
    )
    scale_set_id = int(cursor.lastrowid)
    connection.executemany(
        """
        INSERT INTO gpm_metric_scale_set_items (scale_set_id, metric_key, scale_id)
        VALUES (?, ?, ?)
        """,
        [(scale_set_id, metric_key, scale_id) for metric_key, scale_id in sorted(items.items())],
    )
    return scale_set_id


def _migrate_metric_scale_sets(connection: sqlite3.Connection, now: str) -> None:
    """把旧方案/覆盖无损折叠为新标尺集和地图作用域绑定，仅执行一次。"""

    if connection.execute(
        "SELECT 1 FROM gpm_schema_migrations WHERE name = ?", (_SCALE_SET_MIGRATION,)
    ).fetchone():
        return

    scope_sets: dict[tuple[int, str, int], int] = {}
    has_profiles = _table_exists(connection, "gpm_scale_profiles")
    has_slots = _table_exists(connection, "gpm_scale_profile_slots")
    profile_rows = connection.execute(
        "SELECT id, name FROM gpm_scale_profiles ORDER BY id"
    ).fetchall() if has_profiles and has_slots else []
    for profile_id, profile_name in profile_rows:
        slot_rows = connection.execute(
            """
            SELECT platform, shading_quality, metric_key, scale_id
            FROM gpm_scale_profile_slots
            WHERE profile_id = ?
            ORDER BY platform, shading_quality DESC, metric_key
            """,
            (profile_id,),
        ).fetchall()
        scoped_items: dict[tuple[str, int], dict[str, int]] = {}
        for platform, quality, metric_key, scale_id in slot_rows:
            scoped_items.setdefault((str(platform), int(quality)), {})[str(metric_key)] = int(scale_id)

        if not scoped_items:
            continue

        signatures: dict[tuple[tuple[str, int], ...], list[tuple[str, int]]] = {}
        for scope, items in scoped_items.items():
            signatures.setdefault(tuple(sorted(items.items())), []).append(scope)
        for signature, scopes in signatures.items():
            first_platform, first_quality = scopes[0]
            set_name = str(profile_name) if len(signatures) == 1 else (
                f"{profile_name} · {first_platform} · Q{first_quality}"
            )
            scale_set_id = _insert_migrated_scale_set(
                connection, name=set_name, items=dict(signature), now=now,
            )
            for platform, quality in scopes:
                scope_sets[(int(profile_id), platform, quality)] = scale_set_id

    legacy_bindings = connection.execute(
        "SELECT map_name, profile_id FROM gpm_map_scale_bindings ORDER BY map_name"
    ).fetchall() if _table_exists(connection, "gpm_map_scale_bindings") else []
    map_profiles = {str(map_name): int(profile_id) for map_name, profile_id in legacy_bindings}
    for map_name, profile_id in map_profiles.items():
        for (candidate_profile_id, platform, quality), scale_set_id in scope_sets.items():
            if candidate_profile_id != profile_id:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO gpm_map_scale_set_bindings (
                    map_name, platform, shading_quality, scale_set_id, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (map_name, platform, quality, scale_set_id, now),
            )

    override_scopes = connection.execute(
        """
        SELECT DISTINCT map_name, platform, shading_quality
        FROM gpm_map_scale_overrides
        ORDER BY map_name, platform, shading_quality DESC
        """
    ).fetchall() if _table_exists(connection, "gpm_map_scale_overrides") else []
    for map_name, platform, quality in override_scopes:
        map_name = str(map_name)
        platform = str(platform)
        quality = int(quality)
        merged: dict[str, int] = {}
        base_binding = connection.execute(
            """
            SELECT scale_set_id FROM gpm_map_scale_set_bindings
            WHERE map_name = ? AND platform = ? AND shading_quality = ?
            """,
            (map_name, platform, quality),
        ).fetchone()
        if base_binding:
            merged.update({
                str(row[0]): int(row[1]) for row in connection.execute(
                    """
                    SELECT metric_key, scale_id FROM gpm_metric_scale_set_items
                    WHERE scale_set_id = ?
                    """,
                    (base_binding[0],),
                )
            })
        merged.update({
            str(row[0]): int(row[1]) for row in connection.execute(
                """
                SELECT metric_key, scale_id FROM gpm_map_scale_overrides
                WHERE map_name = ? AND platform = ? AND shading_quality = ?
                """,
                (map_name, platform, quality),
            )
        })
        migrated_set_id = _insert_migrated_scale_set(
            connection,
            name=f"{map_name} · {platform} · Q{quality} · 迁移配置",
            items=merged,
            now=now,
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO gpm_map_scale_set_bindings (
                map_name, platform, shading_quality, scale_set_id, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (map_name, platform, quality, migrated_set_id, now),
        )

    connection.execute(
        "INSERT INTO gpm_schema_migrations (name, applied_at) VALUES (?, ?)",
        (_SCALE_SET_MIGRATION, now),
    )


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
                    map_name TEXT NOT NULL,
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
                    map_name TEXT NOT NULL,
                    -- scene_id 保留为旧库兼容列；新代码写入与 map_name 相同的值。
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

                CREATE TABLE IF NOT EXISTS gpm_config_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_filename TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    map_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gpm_map_definitions (
                    map_name TEXT PRIMARY KEY,
                    map_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    origin_x REAL NOT NULL,
                    origin_y REAL NOT NULL,
                    range_x REAL NOT NULL,
                    range_y REAL NOT NULL,
                    x_reverse INTEGER NOT NULL DEFAULT 0,
                    y_reverse INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    import_id INTEGER NOT NULL REFERENCES gpm_config_imports(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gpm_metric_scales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    -- metric_key 是早期版本的兼容列；指标关联现由标尺集条目维护。
                    metric_key TEXT NOT NULL DEFAULT '*',
                    thresholds_json TEXT NOT NULL,
                    colors_json TEXT NOT NULL DEFAULT '["#52e817","#b7f400","#ffb20a","#ff4a0a","#ff1111"]',
                    segments_json TEXT NOT NULL DEFAULT '[{"color":"#52e817","expression":"<100"},{"color":"#b7f400","expression":">=100 & <200"},{"color":"#ffb20a","expression":">=200 & <300"},{"color":"#ff4a0a","expression":">=300 & <400"},{"color":"#ff1111","expression":">=400"}]',
                    direction TEXT NOT NULL DEFAULT 'lower_is_better',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gpm_metric_scale_sets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    revision INTEGER NOT NULL DEFAULT 1,
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
                    map_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    shading_quality INTEGER NOT NULL,
                    scale_set_id INTEGER NOT NULL REFERENCES gpm_metric_scale_sets(id) ON DELETE RESTRICT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(map_name, platform, shading_quality)
                );

                CREATE TABLE IF NOT EXISTS gpm_schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_gpm_upload_scope
                    ON gpm_uploads(branch_tag, platform, shading_quality, captured_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_gpm_batch_id
                    ON gpm_uploads(batch_id);
                CREATE INDEX IF NOT EXISTS ix_gpm_scene_lookup
                    ON gpm_scenes(scene_id, upload_id);
                CREATE INDEX IF NOT EXISTS ix_gpm_point_scene
                    ON gpm_points(scene_row_id, point_index);
                CREATE INDEX IF NOT EXISTS ix_gpm_point_key
                    ON gpm_points(point_key);
                CREATE INDEX IF NOT EXISTS ix_gpm_map_definition_active
                    ON gpm_map_definitions(active, map_id, map_name);
                CREATE INDEX IF NOT EXISTS ix_gpm_config_import_time
                    ON gpm_config_imports(imported_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS ix_gpm_metric_scale_key
                    ON gpm_metric_scales(metric_key, name);
                CREATE INDEX IF NOT EXISTS ix_gpm_scale_set_item_scale
                    ON gpm_metric_scale_set_items(scale_id);
                CREATE INDEX IF NOT EXISTS ix_gpm_map_scale_set_binding
                    ON gpm_map_scale_set_bindings(scale_set_id, map_name);
                """
            )
            scene_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(gpm_scenes)")
            }
            if "map_name" not in scene_columns:
                connection.execute("ALTER TABLE gpm_scenes ADD COLUMN map_name TEXT")
            connection.execute(
                "UPDATE gpm_scenes SET map_name = scene_id "
                "WHERE map_name IS NULL OR TRIM(map_name) = ''"
            )

            map_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(gpm_map_revisions)")
            }
            if "map_name" not in map_columns:
                connection.execute("ALTER TABLE gpm_map_revisions ADD COLUMN map_name TEXT")
            connection.execute(
                "UPDATE gpm_map_revisions SET map_name = scene_id "
                "WHERE map_name IS NULL OR TRIM(map_name) = ''"
            )
            connection.execute("DROP INDEX IF EXISTS uq_gpm_active_map")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_gpm_active_map_name "
                "ON gpm_map_revisions(map_name) WHERE active = 1"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_gpm_map_revision_name "
                "ON gpm_map_revisions(map_name, revision)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_gpm_scene_map_name "
                "ON gpm_scenes(map_name, upload_id)"
            )
            scale_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(gpm_metric_scales)")
            }
            if "colors_json" not in scale_columns:
                connection.execute("ALTER TABLE gpm_metric_scales ADD COLUMN colors_json TEXT")
            connection.execute(
                "UPDATE gpm_metric_scales SET colors_json = ? "
                "WHERE colors_json IS NULL OR TRIM(colors_json) = ''",
                ('["#52e817","#b7f400","#ffb20a","#ff4a0a","#ff1111"]',),
            )
            if "segments_json" not in scale_columns:
                connection.execute("ALTER TABLE gpm_metric_scales ADD COLUMN segments_json TEXT")
            for row in connection.execute(
                """
                SELECT id, thresholds_json, colors_json, direction
                FROM gpm_metric_scales
                WHERE segments_json IS NULL OR TRIM(segments_json) = ''
                """
            ).fetchall():
                try:
                    thresholds = json.loads(row[1])
                    colors = json.loads(row[2])
                    segments = segments_from_legacy(thresholds, colors, row[3])
                except (TypeError, ValueError, json.JSONDecodeError):
                    segments = default_scale_segments()
                connection.execute(
                    "UPDATE gpm_metric_scales SET segments_json = ? WHERE id = ?",
                    (json.dumps(segments, ensure_ascii=False), row[0]),
                )
            now = datetime.now().isoformat(timespec="seconds")
            _migrate_metric_scale_sets(connection, now)
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
