"""SQLite 在线日备份：日期快照、WAL 一致性、失败清理和安全保留。"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import app.backup as backup_module
from app.backup import (
    _parse_backup_date,
    create_daily_backup,
    daily_backup_path,
    prune_backups,
)


NOW = datetime(2026, 7, 10, 12, 0, 0)


def _open_wal_source(path: Path, rows: tuple[tuple[str, str], ...] = (("1", "SceneA"),)):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE batches (id TEXT PRIMARY KEY, scene_id TEXT NOT NULL)")
    connection.executemany("INSERT INTO batches VALUES (?, ?)", rows)
    connection.commit()
    return connection


def _file_fingerprint(path: Path) -> tuple[int, str]:
    content = path.read_bytes()
    return len(content), hashlib.sha256(content).hexdigest()


def _immutable_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )


def _temp_path(connection: sqlite3.Connection) -> Path:
    rows = connection.execute("PRAGMA database_list").fetchall()
    return Path(next(row[2] for row in rows if row[1] == "main"))


def _sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(Path(f"{path}{suffix}") for suffix in ("-journal", "-wal", "-shm"))


def _snapshot(root: Path, day: str, db_name: str = "shotdiff.db") -> Path:
    database = root / day / "db" / db_name
    database.parent.mkdir(parents=True)
    database.write_bytes(b"owned snapshot")
    return database


def _make_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"当前平台不能创建目录链接: {exc}")


def _make_file_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"当前平台不能创建文件链接: {exc}")


def _make_directory_junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction 仅在 Windows 验证")
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()
        pytest.skip(f"当前环境不能创建 Windows junction: {detail}")


def _assert_create_rejects_linked_parent(tmp_path: Path, level: str, maker) -> None:
    source_path = tmp_path / "shotdiff.db"
    root = tmp_path / "backup"
    root.mkdir()
    date_dir = root / "2026-07-10"
    external = tmp_path / f"outside-{level}"
    if level == "date":
        (external / "db").mkdir(parents=True)
        maker(date_dir, external)
    else:
        date_dir.mkdir()
        external.mkdir()
        maker(date_dir / "db", external)

    source = _open_wal_source(source_path)
    try:
        with pytest.raises(OSError, match="链接|越界"):
            create_daily_backup(source_path, root, now=NOW)
    finally:
        source.close()

    assert not list(external.rglob("*.tmp"))
    assert not list(external.rglob("shotdiff.db"))


def test_daily_backup_path_uses_exact_dated_layout(tmp_path):
    source = tmp_path / "data" / "shotdiff.db"
    root = tmp_path / "backup"

    assert daily_backup_path(source, root, now=NOW) == (
        root.resolve() / "2026-07-10" / "db" / "shotdiff.db"
    )


def test_missing_source_does_not_create_backup_directories(tmp_path):
    source = tmp_path / "missing.db"
    root = tmp_path / "backup"

    with pytest.raises(FileNotFoundError, match="数据库不存在"):
        create_daily_backup(source, root, now=NOW)

    assert not root.exists()


def test_daily_backup_preserves_custom_database_basename(tmp_path):
    source = tmp_path / "custom" / "production.sqlite3"
    root = tmp_path / "snapshots"
    source.parent.mkdir()
    connection = _open_wal_source(source)
    try:
        created = create_daily_backup(source, root, now=NOW)

        assert created == root.resolve() / "2026-07-10" / "db" / "production.sqlite3"
        assert created.is_file()
    finally:
        connection.close()


def test_daily_backup_contains_wal_rows_without_changing_source_wal(tmp_path):
    source_path = tmp_path / "shotdiff.db"
    root = tmp_path / "backup"
    source = _open_wal_source(source_path, (("1", "SceneA"), ("2", "SceneB")))
    try:
        wal = Path(f"{source_path}-wal")
        assert wal.is_file()
        before = _file_fingerprint(wal)

        created = create_daily_backup(source_path, root, now=NOW)

        assert created == root.resolve() / "2026-07-10" / "db" / "shotdiff.db"
        assert _file_fingerprint(wal) == before
        with _immutable_connection(created) as backup:
            assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert backup.execute("PRAGMA journal_mode").fetchone() == ("delete",)
            assert backup.execute(
                "SELECT id, scene_id FROM batches ORDER BY id",
            ).fetchall() == [("1", "SceneA"), ("2", "SceneB")]
        assert not any(path.exists() for path in _sidecars(created))
    finally:
        source.close()


def test_daily_backup_is_idempotent_for_same_date(tmp_path):
    source_path = tmp_path / "shotdiff.db"
    root = tmp_path / "backup"
    source = _open_wal_source(source_path)
    try:
        created = create_daily_backup(source_path, root, now=NOW)

        assert created is not None
        assert create_daily_backup(source_path, root, now=NOW) is None
        assert [path for path in root.rglob("*") if path.is_file()] == [created]
    finally:
        source.close()


@pytest.mark.parametrize("existing_level", ["date", "db"])
def test_empty_snapshot_directories_do_not_suppress_creation(tmp_path, existing_level):
    source_path = tmp_path / "shotdiff.db"
    root = tmp_path / "backup"
    existing = root / "2026-07-10"
    if existing_level == "db":
        existing /= "db"
    existing.mkdir(parents=True)
    source = _open_wal_source(source_path)
    try:
        created = create_daily_backup(source_path, root, now=NOW)

        assert created == root.resolve() / "2026-07-10" / "db" / "shotdiff.db"
        assert created.is_file()
    finally:
        source.close()


@pytest.mark.parametrize("level", ["date", "db"])
def test_create_rejects_linked_backup_parent(tmp_path, level):
    _assert_create_rejects_linked_parent(tmp_path, level, _make_directory_link)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 仅在 Windows 验证")
@pytest.mark.parametrize("level", ["date", "db"])
def test_create_rejects_windows_junction_parent(tmp_path, level):
    _assert_create_rejects_linked_parent(tmp_path, level, _make_directory_junction)


def test_validation_failure_removes_temp_database_and_exact_sidecars(tmp_path, monkeypatch):
    source_path = tmp_path / "shotdiff.db"
    root = tmp_path / "backup"
    source = _open_wal_source(source_path)

    def fail_validation(connection):
        temp = _temp_path(connection)
        for sidecar in _sidecars(temp):
            sidecar.write_bytes(b"temporary")
        raise sqlite3.DatabaseError("injected validation failure")

    monkeypatch.setattr(backup_module, "_validate_destination", fail_validation)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="injected validation failure"):
            create_daily_backup(source_path, root, now=NOW)

        target = daily_backup_path(source_path, root, now=NOW)
        assert not target.exists()
        assert [path for path in root.rglob("*") if path.is_file()] == []
    finally:
        source.close()


def test_validation_failure_does_not_change_source_wal(tmp_path, monkeypatch):
    source_path = tmp_path / "shotdiff.db"
    root = tmp_path / "backup"
    source = _open_wal_source(source_path, (("1", "SceneA"), ("2", "SceneB")))
    wal = Path(f"{source_path}-wal")
    before = _file_fingerprint(wal)

    def fail_validation(_connection):
        raise sqlite3.DatabaseError("stop before publication")

    monkeypatch.setattr(backup_module, "_validate_destination", fail_validation)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="stop before publication"):
            create_daily_backup(source_path, root, now=NOW)

        assert _file_fingerprint(wal) == before
        assert not daily_backup_path(source_path, root, now=NOW).exists()
    finally:
        source.close()


def test_replace_failure_removes_temp_database_and_exact_sidecars(tmp_path, monkeypatch):
    source_path = tmp_path / "shotdiff.db"
    root = tmp_path / "backup"
    source = _open_wal_source(source_path)
    real_validate = backup_module._validate_destination

    def validate_and_add_sidecars(connection):
        real_validate(connection)
        for sidecar in _sidecars(_temp_path(connection)):
            sidecar.write_bytes(b"temporary")

    def fail_replace(_source, _target):
        raise OSError("injected publication failure")

    monkeypatch.setattr(backup_module, "_validate_destination", validate_and_add_sidecars)
    monkeypatch.setattr(backup_module.os, "replace", fail_replace)
    try:
        with pytest.raises(OSError, match="injected publication failure"):
            create_daily_backup(source_path, root, now=NOW)

        target = daily_backup_path(source_path, root, now=NOW)
        assert not target.exists()
        assert [path for path in root.rglob("*") if path.is_file()] == []
    finally:
        source.close()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("2026-07-10", "2026-07-10"),
        ("2026-7-1", None),
        ("2026-00-01", None),
        ("2026-02-30", None),
        ("2026-07-10-extra", None),
    ],
)
def test_parse_backup_date_is_strict(name, expected):
    parsed = _parse_backup_date(name)

    assert (parsed.isoformat() if parsed else None) == expected


def test_prune_deletes_only_strictly_expired_owned_date_units(tmp_path):
    root = tmp_path / "backup"
    expired_db = _snapshot(root, "2026-06-09")
    expired_dir = expired_db.parents[1]
    (expired_dir / "metadata.json").write_text("{}", encoding="utf-8")
    Path(f"{expired_db}-wal").write_bytes(b"owned sidecar")
    cutoff_db = _snapshot(root, "2026-06-10")
    fresh_db = _snapshot(root, "2026-07-05")
    unrelated = root / "operator-files"
    unrelated.mkdir(parents=True)
    (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

    removed = prune_backups(root, retention_days=30, now=NOW)

    assert removed == [expired_dir]
    assert not expired_dir.exists()
    assert cutoff_db.exists()
    assert fresh_db.exists()
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_zero_retention_keeps_all_snapshots(tmp_path):
    root = tmp_path / "backup"
    database = _snapshot(root, "2020-01-01")

    assert prune_backups(root, retention_days=0, now=NOW) == []
    assert database.exists()


@pytest.mark.parametrize(
    "name",
    ["2026-7-1", "2026-00-01", "2026-02-30", "2026-06-01-extra"],
)
def test_prune_ignores_malformed_date_directories(tmp_path, name):
    root = tmp_path / "backup"
    database = _snapshot(root, name)

    assert prune_backups(root, retention_days=30, now=NOW) == []
    assert database.exists()


@pytest.mark.parametrize("missing", ["db_directory", "database_file"])
def test_prune_skips_snapshot_missing_required_database(tmp_path, missing):
    root = tmp_path / "backup"
    date_dir = root / "2026-06-01"
    if missing == "database_file":
        (date_dir / "db").mkdir(parents=True)
    else:
        date_dir.mkdir(parents=True)

    assert prune_backups(root, retention_days=30, now=NOW) == []
    assert date_dir.exists()


def test_prune_skips_database_file_symlink(tmp_path):
    root = tmp_path / "backup"
    external = tmp_path / "outside.db"
    external.write_bytes(b"do not delete")
    db_dir = root / "2026-06-01" / "db"
    db_dir.mkdir(parents=True)
    link = db_dir / "shotdiff.db"
    _make_file_link(link, external)

    assert prune_backups(root, retention_days=30, now=NOW) == []
    assert link.exists()
    assert external.read_bytes() == b"do not delete"


def test_prune_skips_linked_db_directory_with_resolved_path_mismatch(tmp_path):
    root = tmp_path / "backup"
    date_dir = root / "2026-06-01"
    date_dir.mkdir(parents=True)
    external_db_dir = tmp_path / "outside-db"
    external_db_dir.mkdir()
    (external_db_dir / "shotdiff.db").write_bytes(b"do not delete")
    link = date_dir / "db"
    _make_directory_link(link, external_db_dir)

    assert prune_backups(root, retention_days=30, now=NOW) == []
    assert link.exists()
    assert (external_db_dir / "shotdiff.db").read_bytes() == b"do not delete"


def test_prune_skips_linked_date_directory_with_resolved_path_mismatch(tmp_path):
    root = tmp_path / "backup"
    root.mkdir()
    external_date_dir = tmp_path / "outside-date"
    (external_date_dir / "db").mkdir(parents=True)
    (external_date_dir / "db" / "shotdiff.db").write_bytes(b"do not delete")
    link = root / "2026-06-01"
    _make_directory_link(link, external_date_dir)

    assert prune_backups(root, retention_days=30, now=NOW) == []
    assert link.exists()
    assert (external_date_dir / "db" / "shotdiff.db").read_bytes() == b"do not delete"


def test_scheduler_backs_up_primary_and_independent_gpm_database(tmp_path, monkeypatch):
    gpm_database = tmp_path / "gpm_heatmap.db"
    gpm_database.write_bytes(b"gpm")
    calls = []

    def fake_backup(db_path=backup_module.DB_PATH, *_args, **_kwargs):
        calls.append(Path(db_path).resolve())
        return None

    class OnePassStop:
        def is_set(self):
            return False

        def wait(self, _timeout):
            return True

    monkeypatch.setattr(backup_module, "create_daily_backup", fake_backup)
    monkeypatch.setattr(backup_module, "gpm_db_path", lambda: gpm_database)
    monkeypatch.setattr(backup_module, "prune_backups", lambda: [])
    scheduler = backup_module.DatabaseBackupScheduler()
    scheduler._stop = OnePassStop()

    scheduler._run()

    assert calls == [Path(backup_module.DB_PATH).resolve(), gpm_database.resolve()]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 仅在 Windows 验证")
@pytest.mark.parametrize("level", ["date", "db"])
def test_prune_skips_windows_junction_with_resolved_path_mismatch(tmp_path, level):
    root = tmp_path / "backup"
    root.mkdir()
    date_dir = root / "2026-06-01"
    external = tmp_path / f"outside-{level}"
    if level == "date":
        (external / "db").mkdir(parents=True)
        database = external / "db" / "shotdiff.db"
        database.write_bytes(b"do not delete")
        _make_directory_junction(date_dir, external)
    else:
        date_dir.mkdir()
        external.mkdir()
        database = external / "shotdiff.db"
        database.write_bytes(b"do not delete")
        _make_directory_junction(date_dir / "db", external)

    assert prune_backups(root, retention_days=30, now=NOW) == []
    assert database.read_bytes() == b"do not delete"
