"""SQLite 每日在线备份。

运行中的 WAL 数据库不能靠复制单个 .db 文件获得一致快照，因此这里使用
sqlite3.Connection.backup()，先写唯一临时库、通过 quick_check 后再原子发布。
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .db import DATA_DIR, DB_PATH
from .logging_setup import log


BACKUP_DIR = DATA_DIR / "backup" / "db"


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


BACKUP_ENABLED = os.environ.get("PIXELCOMP_BACKUP_ENABLED", "1").lower() \
    not in {"0", "false", "no", "off"}
BACKUP_RETENTION_DAYS = _env_int("PIXELCOMP_BACKUP_RETENTION_DAYS", 30)
BACKUP_CHECK_INTERVAL_SECONDS = _env_int(
    "PIXELCOMP_BACKUP_CHECK_INTERVAL_SECONDS", 3600, minimum=60,
)

_BACKUP_LOCK = threading.Lock()


def create_daily_backup(
    db_path: Path = DB_PATH,
    backup_dir: Path = BACKUP_DIR,
    now: datetime | None = None,
) -> Path | None:
    """创建当天的一致性快照；当天已存在时返回 None。"""
    db_path = Path(db_path).resolve()
    backup_dir = Path(backup_dir).resolve()
    now = now or datetime.now()
    target = backup_dir / f"{db_path.stem}-{now:%Y-%m-%d}.db"

    with _BACKUP_LOCK:
        if target.is_file():
            return None
        if not db_path.is_file():
            raise FileNotFoundError(f"数据库不存在: {db_path}")

        backup_dir.mkdir(parents=True, exist_ok=True)
        temp = backup_dir / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        source = destination = None
        try:
            source_uri = f"{db_path.as_uri()}?mode=ro"
            source = sqlite3.connect(source_uri, uri=True, timeout=30)
            destination = sqlite3.connect(temp, timeout=30)
            source.backup(destination, pages=256, sleep=0.05)
            check = destination.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                raise sqlite3.DatabaseError(f"备份完整性检查失败: {check}")
            destination.close()
            destination = None
            source.close()
            source = None
            os.replace(temp, target)
            return target
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()
            temp.unlink(missing_ok=True)


def prune_backups(
    backup_dir: Path = BACKUP_DIR,
    retention_days: int = BACKUP_RETENTION_DAYS,
    now: datetime | None = None,
    db_stem: str = DB_PATH.stem,
) -> list[Path]:
    """删除超过保留天数的本数据库日备份；0 表示永久保留。"""
    backup_dir = Path(backup_dir)
    if retention_days <= 0 or not backup_dir.is_dir():
        return []
    cutoff = (now or datetime.now()).timestamp() - timedelta(days=retention_days).total_seconds()
    removed: list[Path] = []
    for path in backup_dir.glob(f"{db_stem}-????-??-??.db"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path)
        except OSError as exc:
            log.warning("删除过期数据库备份失败 %s: %s", path, exc)
    return removed


class DatabaseBackupScheduler:
    """进程内每日备份调度器：启动即检查，此后每小时检查一次。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        if not BACKUP_ENABLED:
            log.info("数据库自动备份已禁用")
            return
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="pixelcomp-db-backup", daemon=True,
            )
            self._thread.start()
        log.info(
            "数据库自动备份已启用:目录=%s 保留=%s",
            BACKUP_DIR, f"{BACKUP_RETENTION_DAYS} 天" if BACKUP_RETENTION_DAYS else "永久",
        )

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if not thread:
                return
            self._stop.set()
        thread.join(timeout=5)
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                created = create_daily_backup()
                if created:
                    log.info("数据库每日备份完成: %s", created)
                removed = prune_backups()
                if removed:
                    log.info("数据库备份淘汰:删除 %d 个过期文件", len(removed))
            except Exception:  # noqa: BLE001
                log.exception("数据库每日备份失败,稍后自动重试")
            if self._stop.wait(BACKUP_CHECK_INTERVAL_SECONDS):
                break


backup_scheduler = DatabaseBackupScheduler()
