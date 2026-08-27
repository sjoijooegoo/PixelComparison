"""SQLite 每日在线备份。

运行中的 WAL 数据库不能靠复制单个 .db 文件获得一致快照，因此这里使用
sqlite3.Connection.backup()，先写唯一临时库、通过 quick_check 后再原子发布。
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .db import DATA_DIR, DB_PATH
from .gpm_storage import gpm_db_path
from .logging_setup import log


BACKUP_ROOT = DATA_DIR / "backup"


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


def daily_backup_path(
    db_path: Path = DB_PATH,
    backup_root: Path = BACKUP_ROOT,
    now: datetime | None = None,
) -> Path:
    """返回当天快照的最终发布路径。"""
    db_path = Path(db_path).resolve()
    backup_root = Path(backup_root).resolve()
    now = now or datetime.now()
    return backup_root / f"{now:%Y-%m-%d}" / "db" / db_path.name


def _validate_destination(connection: sqlite3.Connection) -> None:
    """确认快照独立可读且使用不会遗留 WAL sidecar 的日志模式。"""
    journal_mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
    if not journal_mode or str(journal_mode[0]).lower() != "delete":
        raise sqlite3.DatabaseError(f"备份日志模式设置失败: {journal_mode}")
    check = connection.execute("PRAGMA quick_check").fetchone()
    if not check or check[0] != "ok":
        raise sqlite3.DatabaseError(f"备份完整性检查失败: {check}")


def _cleanup_temp_files(temp: Path) -> None:
    """仅清理当前备份临时库及其 SQLite sidecar。"""
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = temp.with_name(f"{temp.name}{suffix}")
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("清理数据库备份临时文件失败 %s: %s", path, exc)


def _ensure_backup_target_parent(target: Path, backup_root: Path) -> Path:
    """创建并复核日期/db 目录，拒绝链接、junction 或解析后的路径越界。"""
    backup_root_resolved = Path(backup_root).resolve()
    backup_root_resolved.mkdir(parents=True, exist_ok=True)
    if not backup_root_resolved.is_dir():
        raise OSError(f"数据库备份根路径不是目录: {backup_root_resolved}")

    date_dir = target.parent.parent
    expected_date_dir = backup_root_resolved / date_dir.name
    if date_dir != expected_date_dir:
        raise OSError(f"数据库备份日期路径不匹配: {date_dir}")
    if date_dir.is_symlink():
        raise OSError(f"数据库备份日期目录不能是链接: {date_dir}")
    date_dir.mkdir(exist_ok=True)
    if not date_dir.is_dir() or date_dir.resolve() != expected_date_dir:
        raise OSError(f"数据库备份日期目录越界: {date_dir}")

    db_dir = date_dir / "db"
    if target.parent != db_dir:
        raise OSError(f"数据库备份 db 路径不匹配: {target.parent}")
    if db_dir.is_symlink():
        raise OSError(f"数据库备份 db 目录不能是链接: {db_dir}")
    db_dir.mkdir(exist_ok=True)
    db_dir_resolved = db_dir.resolve()
    if not db_dir.is_dir() or db_dir_resolved != expected_date_dir / "db":
        raise OSError(f"数据库备份 db 目录越界: {db_dir}")

    if target.is_symlink():
        raise OSError(f"数据库备份目标不能是链接: {target}")
    if target.exists() and (not target.is_file() or target.resolve().parent != db_dir_resolved):
        raise OSError(f"数据库备份目标路径越界: {target}")
    return db_dir_resolved


def create_daily_backup(
    db_path: Path = DB_PATH,
    backup_root: Path = BACKUP_ROOT,
    now: datetime | None = None,
) -> Path | None:
    """创建当天的一致性快照；当天已存在时返回 None。"""
    db_path = Path(db_path).resolve()
    now = now or datetime.now()
    target = daily_backup_path(db_path=db_path, backup_root=backup_root, now=now)

    with _BACKUP_LOCK:
        if not db_path.is_file():
            raise FileNotFoundError(f"数据库不存在: {db_path}")
        db_dir_resolved = _ensure_backup_target_parent(target, backup_root)
        if target.is_file():
            return None

        temp = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        source = destination = None
        try:
            if _ensure_backup_target_parent(target, backup_root) != db_dir_resolved:
                raise OSError(f"数据库备份目录在创建期间发生变化: {target.parent}")
            if temp.resolve().parent != db_dir_resolved:
                raise OSError(f"数据库备份临时路径越界: {temp}")
            source_uri = f"{db_path.as_uri()}?mode=ro"
            source = sqlite3.connect(source_uri, uri=True, timeout=30)
            destination = sqlite3.connect(temp, timeout=30)
            source.backup(destination, pages=256, sleep=0.05)
            _validate_destination(destination)
            destination.close()
            destination = None
            source.close()
            source = None
            if _ensure_backup_target_parent(target, backup_root) != db_dir_resolved:
                raise OSError(f"数据库备份目录在发布前发生变化: {target.parent}")
            if temp.resolve().parent != db_dir_resolved:
                raise OSError(f"数据库备份临时路径在发布前越界: {temp}")
            os.replace(temp, target)
            return target
        finally:
            try:
                if destination is not None:
                    destination.close()
            finally:
                try:
                    if source is not None:
                        source.close()
                finally:
                    _cleanup_temp_files(temp)


def create_migration_backup(
    migration_name: str,
    db_path: Path = DB_PATH,
    backup_root: Path = BACKUP_ROOT,
    now: datetime | None = None,
) -> Path:
    """在任何 schema 写入前创建不可覆盖的迁移快照。

    每日备份同一天只保留一份；迁移快照必须带版本和时间，便于失败回滚与审计。
    """
    if not re.fullmatch(r"[a-z0-9._-]{1,64}", migration_name):
        raise ValueError("非法迁移名称")
    db_path = Path(db_path).resolve()
    now = now or datetime.now()
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    target = (
        Path(backup_root).resolve()
        / f"{now:%Y-%m-%d}"
        / "db"
        / f"{db_path.stem}.pre-{migration_name}.{stamp}{db_path.suffix}"
    )

    with _BACKUP_LOCK:
        if not db_path.is_file():
            raise FileNotFoundError(f"数据库不存在: {db_path}")
        db_dir_resolved = _ensure_backup_target_parent(target, backup_root)
        temp = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        source = destination = None
        try:
            if temp.resolve().parent != db_dir_resolved:
                raise OSError(f"数据库迁移备份临时路径越界: {temp}")
            source = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=30)
            destination = sqlite3.connect(temp, timeout=30)
            source.backup(destination, pages=256, sleep=0.05)
            _validate_destination(destination)
            destination.close()
            destination = None
            source.close()
            source = None
            if target.exists():
                raise FileExistsError(f"迁移备份目标已存在: {target}")
            os.replace(temp, target)
            return target
        finally:
            try:
                if destination is not None:
                    destination.close()
            finally:
                try:
                    if source is not None:
                        source.close()
                finally:
                    _cleanup_temp_files(temp)


_BACKUP_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_backup_date(name: str) -> date | None:
    """严格解析 YYYY-MM-DD 备份目录名。"""
    if not _BACKUP_DATE_PATTERN.fullmatch(name):
        return None
    try:
        parsed = datetime.strptime(name, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if parsed.strftime("%Y-%m-%d") == name else None


def prune_backups(
    backup_root: Path = BACKUP_ROOT,
    retention_days: int = BACKUP_RETENTION_DAYS,
    now: datetime | None = None,
    db_name: str = DB_PATH.name,
) -> list[Path]:
    """删除过期且确认完全位于备份根目录内的日期快照；0 表示永久保留。"""
    backup_root = Path(backup_root)
    if retention_days <= 0 or not backup_root.is_dir():
        return []

    backup_root_resolved = backup_root.resolve()
    cutoff = (now or datetime.now()).date() - timedelta(days=retention_days)
    removed: list[Path] = []
    for candidate in backup_root.iterdir():
        backup_date = _parse_backup_date(candidate.name)
        if backup_date is None:
            continue

        try:
            if candidate.is_symlink() or not candidate.is_dir():
                log.warning("跳过结构异常的数据库备份目录: %s", candidate)
                continue

            candidate_resolved = candidate.resolve()
            if candidate_resolved != backup_root_resolved / candidate.name:
                log.warning("跳过路径越界的数据库备份目录: %s", candidate)
                continue

            db_dir = candidate / "db"
            if db_dir.is_symlink() or not db_dir.is_dir():
                log.warning("跳过缺少有效 db 目录的数据库备份: %s", candidate)
                continue

            db_dir_resolved = db_dir.resolve()
            if db_dir_resolved != candidate_resolved / "db":
                log.warning("跳过 db 路径越界的数据库备份: %s", candidate)
                continue

            snapshot = db_dir / db_name
            if snapshot.is_symlink() or not snapshot.is_file():
                log.warning("跳过缺少有效数据库文件的备份: %s", candidate)
                continue
            if snapshot.resolve().parent != db_dir_resolved:
                log.warning("跳过数据库文件路径越界的备份: %s", candidate)
                continue

            if backup_date < cutoff:
                shutil.rmtree(candidate)
                removed.append(candidate)
        except (OSError, RuntimeError) as exc:
            log.warning("检查或删除过期数据库备份失败 %s: %s", candidate, exc)
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
            BACKUP_ROOT, f"{BACKUP_RETENTION_DAYS} 天" if BACKUP_RETENTION_DAYS else "永久",
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
                gpm_database = gpm_db_path()
                if gpm_database.resolve() != Path(DB_PATH).resolve() and gpm_database.is_file():
                    gpm_created = create_daily_backup(gpm_database)
                    if gpm_created:
                        log.info("GPMHeatmap 数据库每日备份完成: %s", gpm_created)
                removed = prune_backups()
                if removed:
                    log.info("数据库备份淘汰:删除 %d 个过期日期目录", len(removed))
            except Exception:  # noqa: BLE001
                log.exception("数据库每日备份失败,稍后自动重试")
            if self._stop.wait(BACKUP_CHECK_INTERVAL_SECONDS):
                break


backup_scheduler = DatabaseBackupScheduler()
