"""GPMHeatmap 最终 schema，不测试任何历史迁移。"""

import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def test_final_schema_is_created_without_legacy_point_identity(tmp_path, monkeypatch):
    database = tmp_path / "gpm.db"
    assets = tmp_path / "assets"

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
    assert assets.is_dir()


def test_schema_mismatch_refuses_startup_and_preserves_database_and_assets(tmp_path, monkeypatch):
    database = tmp_path / "gpm.db"
    assets = tmp_path / "assets"
    assets.mkdir()
    marker = assets / "old.png"
    marker.write_bytes(b"old")
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE old_gpm_demo (id INTEGER PRIMARY KEY)")
    connection.execute("INSERT INTO old_gpm_demo (id) VALUES (7)")
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()

    monkeypatch.setenv("PIXELCOMP_GPM_DB_PATH", str(database))
    monkeypatch.setenv("PIXELCOMP_GPM_ASSETS_DIR", str(assets))
    import app.gpm_storage as storage
    importlib.reload(storage)

    with pytest.raises(storage.GpmSchemaMismatchError, match="拒绝启动且未修改") as error:
        storage.initialize_gpm_database()

    assert str(database.resolve()) in str(error.value)
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT id FROM old_gpm_demo").fetchall() == [(7,)]
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'gpm_uploads'"
        ).fetchone()[0] == 0
    finally:
        connection.close()
    assert marker.read_bytes() == b"old"


def test_application_startup_fails_on_gpm_schema_mismatch_without_modifying_data(tmp_path):
    database = tmp_path / "gpm.db"
    assets = tmp_path / "assets"
    assets.mkdir()
    marker = assets / "point.png"
    marker.write_bytes(b"point-data")
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE old_gpm_demo (id INTEGER PRIMARY KEY)")
    connection.execute("INSERT INTO old_gpm_demo (id) VALUES (9)")
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()

    environment = os.environ.copy()
    for name in (
        "PIXELCOMP_DB_PATH",
        "PIXELCOMP_IMAGES_DIR",
        "PIXELCOMP_THUMB_DIR",
        "PIXELCOMP_GPM_DIR",
        "PIXELCOMP_GPM_DB_PATH",
        "PIXELCOMP_GPM_ASSETS_DIR",
    ):
        environment.pop(name, None)
    environment.update({
        "PIXELCOMP_DATA_DIR": str(tmp_path / "application-data"),
        "PIXELCOMP_GPM_DB_PATH": str(database),
        "PIXELCOMP_GPM_ASSETS_DIR": str(assets),
        "PIXELCOMP_BACKUP_ENABLED": "0",
    })
    completed = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    output = completed.stdout + completed.stderr
    assert "GpmSchemaMismatchError" in output
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT id FROM old_gpm_demo").fetchall() == [(9,)]
    finally:
        connection.close()
    assert marker.read_bytes() == b"point-data"


def test_final_schema_fingerprint_rejects_partial_same_version_database(tmp_path, monkeypatch):
    database = tmp_path / "partial.db"
    assets = tmp_path / "assets"
    connection = sqlite3.connect(database)
    # 表名和版本都伪装成最终状态，但列不完整。这种数据库必须拒绝启动，
    # 不能修改原库，也不能等到首个用户请求时才报 no such column。
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
    monkeypatch.setenv("PIXELCOMP_GPM_ASSETS_DIR", str(assets))
    import app.gpm_storage as storage
    importlib.reload(storage)

    with pytest.raises(storage.GpmSchemaMismatchError, match="schema 不兼容"):
        storage.initialize_gpm_database()

    connection = sqlite3.connect(database)
    try:
        assert {
            row[1] for row in connection.execute("PRAGMA table_info(gpm_uploads)")
        } == {"id"}
    finally:
        connection.close()
    assert not assets.exists()
