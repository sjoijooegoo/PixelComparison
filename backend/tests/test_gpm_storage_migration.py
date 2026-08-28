import importlib
import sqlite3


def test_legacy_gpm_database_backfills_map_name(tmp_path, monkeypatch):
    database = tmp_path / "gpm_heatmap.db"
    assets = tmp_path / "assets"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE gpm_uploads (
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
        CREATE TABLE gpm_scenes (
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
        CREATE TABLE gpm_map_revisions (
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
        CREATE TABLE gpm_metric_scales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            metric_key TEXT NOT NULL,
            thresholds_json TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'lower_is_better',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO gpm_metric_scales (
            name, metric_key, thresholds_json, direction, created_at, updated_at
        ) VALUES ('旧五色标尺', 'Scene_DC', '[100,200,300,400]', 'lower_is_better', '2026-08-26', '2026-08-26');
        INSERT INTO gpm_uploads (
            batch_id, branch_tag, captured_at, platform, shading_quality,
            source_sha256, created_at
        ) VALUES ('legacy', 'main', '2026-08-26T15:00:00+08:00', 'Android', 5, 'sha', '2026-08-26');
        INSERT INTO gpm_scenes (
            upload_id, scene_id, heat_map_json, trend_json
        ) VALUES (1, 'LegacyScene', '[]', '[]');
        INSERT INTO gpm_map_revisions (
            scene_id, revision, image_path, image_width, image_height,
            origin_x, origin_y, range_x, range_y, color_ranges_json, created_at
        ) VALUES ('LegacyScene', 1, 'maps/legacy.png', 100, 100, 0, 0, 10, 10, '{}', '2026-08-26');
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.setenv("PIXELCOMP_GPM_DB_PATH", str(database))
    monkeypatch.setenv("PIXELCOMP_GPM_ASSETS_DIR", str(assets))
    import app.gpm_storage as storage
    importlib.reload(storage)

    storage.initialize_gpm_database()
    migrated = storage.connect_gpm_database()
    try:
        assert migrated.execute("SELECT map_name FROM gpm_scenes").fetchone()[0] == "LegacyScene"
        assert migrated.execute("SELECT map_name FROM gpm_map_revisions").fetchone()[0] == "LegacyScene"
        indexes = {
            row[1] for row in migrated.execute("PRAGMA index_list(gpm_map_revisions)")
        }
        assert "uq_gpm_active_map_name" in indexes
        assert "uq_gpm_map_revision_name" in indexes
        tables = {
            row[0] for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "gpm_config_imports", "gpm_map_definitions",
            "gpm_metric_scales",
            "gpm_metric_scale_sets", "gpm_metric_scale_set_items",
            "gpm_map_scale_set_bindings",
            "gpm_schema_migrations",
        } <= tables
        assert "gpm_metric_catalog" not in tables
        assert "gpm_scale_profiles" not in tables
        assert "gpm_map_scale_overrides" not in tables
        scale_columns = {
            row[1] for row in migrated.execute("PRAGMA table_info(gpm_metric_scales)")
        }
        assert "colors_json" in scale_columns
        assert "segments_json" in scale_columns
        assert migrated.execute(
            "SELECT colors_json FROM gpm_metric_scales WHERE name = '旧五色标尺'"
        ).fetchone()[0] == '["#52e817","#b7f400","#ffb20a","#ff4a0a","#ff1111"]'
        assert migrated.execute(
            "SELECT segments_json FROM gpm_metric_scales WHERE name = '旧五色标尺'"
        ).fetchone()[0] == (
            '[{"color": "#52e817", "expression": "<100"}, '
            '{"color": "#b7f400", "expression": ">=100 & <200"}, '
            '{"color": "#ffb20a", "expression": ">=200 & <300"}, '
            '{"color": "#ff4a0a", "expression": ">=300 & <400"}, '
            '{"color": "#ff1111", "expression": ">=400"}]'
        )
    finally:
        migrated.close()


def test_legacy_scale_profiles_and_overrides_migrate_to_scope_bound_scale_sets(
    tmp_path, monkeypatch,
):
    database = tmp_path / "gpm_heatmap.db"
    assets = tmp_path / "assets"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE gpm_metric_scales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            metric_key TEXT NOT NULL DEFAULT '*',
            thresholds_json TEXT NOT NULL,
            colors_json TEXT NOT NULL,
            segments_json TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'lower_is_better',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE gpm_scale_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE gpm_scale_profile_slots (
            profile_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            shading_quality INTEGER NOT NULL,
            metric_key TEXT NOT NULL,
            scale_id INTEGER NOT NULL,
            PRIMARY KEY(profile_id, platform, shading_quality, metric_key)
        );
        CREATE TABLE gpm_map_scale_bindings (
            map_name TEXT PRIMARY KEY,
            profile_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE gpm_map_scale_overrides (
            map_name TEXT NOT NULL,
            platform TEXT NOT NULL,
            shading_quality INTEGER NOT NULL,
            metric_key TEXT NOT NULL,
            scale_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(map_name, platform, shading_quality, metric_key)
        );
        INSERT INTO gpm_metric_scales (
            name, thresholds_json, colors_json, segments_json, created_at, updated_at
        ) VALUES
          ('基础标尺', '[100]', '["#00ff00","#ff0000"]',
           '[{"color":"#00ff00","expression":"<100"},{"color":"#ff0000","expression":">=100"}]',
           '2026-08-28', '2026-08-28'),
          ('覆盖标尺', '[200]', '["#00ff00","#ff0000"]',
           '[{"color":"#00ff00","expression":"<200"},{"color":"#ff0000","expression":">=200"}]',
           '2026-08-28', '2026-08-28');
        INSERT INTO gpm_scale_profiles (name, created_at, updated_at)
        VALUES ('旧方案', '2026-08-28', '2026-08-28');
        INSERT INTO gpm_scale_profile_slots (
            profile_id, platform, shading_quality, metric_key, scale_id
        ) VALUES
          (1, 'Android', 5, 'Scene_DC', 1),
          (1, 'Android', 5, 'Scene_Tris', 1);
        INSERT INTO gpm_map_scale_bindings (map_name, profile_id, updated_at)
        VALUES ('Village_Dimension_Main', 1, '2026-08-28');
        INSERT INTO gpm_map_scale_overrides (
            map_name, platform, shading_quality, metric_key, scale_id, updated_at
        ) VALUES ('Village_Dimension_Main', 'Android', 5, 'Scene_DC', 2, '2026-08-28');
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.setenv("PIXELCOMP_GPM_DB_PATH", str(database))
    monkeypatch.setenv("PIXELCOMP_GPM_ASSETS_DIR", str(assets))
    import app.gpm_storage as storage
    importlib.reload(storage)

    storage.initialize_gpm_database()
    migrated = storage.connect_gpm_database()
    try:
        binding = migrated.execute(
            """
            SELECT scale_set_id FROM gpm_map_scale_set_bindings
            WHERE map_name = 'Village_Dimension_Main'
              AND platform = 'Android' AND shading_quality = 5
            """
        ).fetchone()
        assert binding is not None
        items = {
            row[0]: row[1] for row in migrated.execute(
                """
                SELECT i.metric_key, s.name
                FROM gpm_metric_scale_set_items i
                JOIN gpm_metric_scales s ON s.id = i.scale_id
                WHERE i.scale_set_id = ?
                """,
                (binding[0],),
            )
        }
        assert items == {"Scene_DC": "覆盖标尺", "Scene_Tris": "基础标尺"}
        set_count = migrated.execute("SELECT COUNT(*) FROM gpm_metric_scale_sets").fetchone()[0]
        assert migrated.execute(
            "SELECT 1 FROM gpm_schema_migrations WHERE name = 'metric-scale-sets-v1'"
        ).fetchone()
    finally:
        migrated.close()

    storage._INITIALIZED_DATABASES.clear()
    storage.initialize_gpm_database()
    migrated_again = storage.connect_gpm_database()
    try:
        assert migrated_again.execute(
            "SELECT COUNT(*) FROM gpm_metric_scale_sets"
        ).fetchone()[0] == set_count
    finally:
        migrated_again.close()
