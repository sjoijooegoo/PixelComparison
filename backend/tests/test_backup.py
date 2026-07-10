"""SQLite 在线日备份：WAL 一致性、每日去重、完整性和保留策略。"""
import os
import sqlite3
from datetime import datetime, timedelta

from app.backup import create_daily_backup, prune_backups


def test_daily_backup_contains_committed_wal_data_and_is_deduplicated(tmp_path):
    source_path = tmp_path / "shotdiff.db"
    backup_dir = tmp_path / "backup" / "db"
    source = sqlite3.connect(source_path)
    try:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE batches (id TEXT PRIMARY KEY, scene_id TEXT NOT NULL)")
        source.executemany(
            "INSERT INTO batches VALUES (?, ?)",
            [("1", "SceneA"), ("2", "SceneB")],
        )
        source.commit()

        now = datetime(2026, 7, 10, 3, 0, 0)
        created = create_daily_backup(source_path, backup_dir, now=now)
        assert created == backup_dir / "shotdiff-2026-07-10.db"
        assert created.is_file()

        backup = sqlite3.connect(f"{created.resolve().as_uri()}?mode=ro", uri=True)
        try:
            assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert backup.execute("SELECT id, scene_id FROM batches ORDER BY id").fetchall() == [
                ("1", "SceneA"), ("2", "SceneB"),
            ]
        finally:
            backup.close()

        assert create_daily_backup(source_path, backup_dir, now=now) is None
        assert list(backup_dir.glob("*.tmp")) == []
    finally:
        source.close()


def test_prune_backups_only_removes_expired_matching_files(tmp_path):
    backup_dir = tmp_path / "backup" / "db"
    backup_dir.mkdir(parents=True)
    now = datetime(2026, 7, 10, 12, 0, 0)
    expired = backup_dir / "shotdiff-2026-06-01.db"
    fresh = backup_dir / "shotdiff-2026-07-05.db"
    unrelated = backup_dir / "other-2026-06-01.db"
    for path in (expired, fresh, unrelated):
        path.write_bytes(b"placeholder")
    old_timestamp = (now - timedelta(days=31)).timestamp()
    fresh_timestamp = (now - timedelta(days=5)).timestamp()
    os.utime(expired, (old_timestamp, old_timestamp))
    os.utime(unrelated, (old_timestamp, old_timestamp))
    os.utime(fresh, (fresh_timestamp, fresh_timestamp))

    removed = prune_backups(
        backup_dir, retention_days=30, now=now, db_stem="shotdiff",
    )

    assert removed == [expired]
    assert not expired.exists()
    assert fresh.exists()
    assert unrelated.exists()


def test_zero_retention_means_keep_forever(tmp_path):
    backup_dir = tmp_path / "backup" / "db"
    backup_dir.mkdir(parents=True)
    backup = backup_dir / "shotdiff-2020-01-01.db"
    backup.write_bytes(b"placeholder")

    assert prune_backups(backup_dir, retention_days=0) == []
    assert backup.exists()
