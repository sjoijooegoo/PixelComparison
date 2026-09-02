"""GPMHeatmap 最终 schema，不测试任何历史迁移。"""

import importlib
import sqlite3


def test_final_schema_replaces_old_demo_database(tmp_path, monkeypatch):
    database = tmp_path / "gpm.db"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "old.png").write_bytes(b"old")
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE old_gpm_demo (id INTEGER PRIMARY KEY)")
    # 同一版本号但结构不匹配也必须整体重建，不能进入半兼容状态。
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()

    monkeypatch.setenv("PIXELCOMP_GPM_DB_PATH", str(database))
    monkeypatch.setenv("PIXELCOMP_GPM_ASSETS_DIR", str(assets))
    import app.gpm_storage as storage
    importlib.reload(storage)

    storage.initialize_gpm_database()
    connection = storage.connect_gpm_database()
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'gpm_%'"
            )
        }
        assert tables == {
            "gpm_uploads",
            "gpm_upload_maps",
            "gpm_points",
            "gpm_map_definitions",
            "gpm_metric_scales",
            "gpm_metric_scale_sets",
            "gpm_metric_scale_set_items",
            "gpm_map_scale_set_bindings",
        }
        assert connection.execute("PRAGMA user_version").fetchone()[0] == storage.GPM_SCHEMA_VERSION
        assert "scene_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(gpm_upload_maps)")
        }
        point_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(gpm_points)")
        }
        assert "scene_row_id" not in point_columns
        assert "point_key" not in point_columns
        point_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(gpm_points)")
        }
        assert "uq_gpm_points_stable_key" not in point_indexes
        assert "ix_gpm_point_key" not in point_indexes
        assert "thresholds_json" not in {
            row[1] for row in connection.execute("PRAGMA table_info(gpm_metric_scales)")
        }
    finally:
        connection.close()
    assert not (assets / "old.png").exists()


def test_final_schema_fingerprint_rejects_partial_same_version_database(tmp_path, monkeypatch):
    database = tmp_path / "partial.db"
    connection = sqlite3.connect(database)
    # 表名和版本都伪装成最终状态，但列不完整。这种数据库必须整体重建，
    # 否则会在首个用户请求时才报 no such column。
    for table_name in (
        "gpm_uploads", "gpm_upload_maps", "gpm_points", "gpm_map_definitions",
        "gpm_metric_scales", "gpm_metric_scale_sets",
        "gpm_metric_scale_set_items", "gpm_map_scale_set_bindings",
    ):
        connection.execute(f"CREATE TABLE {table_name} (id INTEGER)")
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()

    monkeypatch.setenv("PIXELCOMP_GPM_DB_PATH", str(database))
    monkeypatch.setenv("PIXELCOMP_GPM_ASSETS_DIR", str(tmp_path / "assets"))
    import app.gpm_storage as storage
    importlib.reload(storage)

    storage.initialize_gpm_database()
    connection = storage.connect_gpm_database()
    try:
        assert {
            row[1] for row in connection.execute("PRAGMA table_info(gpm_uploads)")
        } == storage._FINAL_COLUMNS["gpm_uploads"]
    finally:
        connection.close()
