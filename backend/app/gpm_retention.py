"""GPMHeatmap 上报数据的固定 30 天保留策略。

地图定义、地图图片和颜色标尺属于独立配置域，不参与这里的淘汰。
"""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterable

from .gpm_storage import connect_gpm_database, gpm_assets_dir


GPM_DATA_RETENTION_DAYS = 30
GPM_RETENTION_CHECK_INTERVAL_SECONDS = 60 * 60

_LOG = logging.getLogger("pixelcomp")


@dataclass(frozen=True)
class GpmRetentionResult:
    cutoff: str
    deleted_uploads: int
    removed_asset_dirs: int
    failed_asset_dirs: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("GPM captured_at 必须包含时区")
    return parsed.astimezone(timezone.utc)


def retention_cutoff(now: datetime | None = None) -> datetime:
    current = now or _utc_now()
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    return current - timedelta(days=GPM_DATA_RETENTION_DAYS)


def is_expired_capture(captured_at: str, *, now: datetime | None = None) -> bool:
    """边界值属于保留窗口；只有严格早于边界的数据才过期。"""

    return _as_utc(captured_at) < retention_cutoff(now)


def remove_gpm_point_assets(asset_paths: Iterable[str | None]) -> tuple[int, int]:
    """只删除数据库所引用的旧版本目录，不删除可被同名重传复用的批次根目录。"""

    assets_root = gpm_assets_dir().resolve()
    uploads_root = (assets_root / "uploads").resolve()
    targets: set[Path] = set()
    invalid_paths = 0
    for raw_path in asset_paths:
        if not raw_path:
            continue
        relative = PurePosixPath(raw_path)
        target = (assets_root / Path(*relative.parent.parts)).resolve()
        valid_layout = (
            not relative.is_absolute()
            and ".." not in relative.parts
            and len(relative.parts) >= 6
            and relative.parts[0] == "uploads"
            and relative.parts[-2] in {"originals", "thumbs"}
        )
        if not valid_layout or target == uploads_root or uploads_root not in target.parents:
            _LOG.error("跳过越界的 GPMHeatmap 点位资源路径: %s", raw_path)
            invalid_paths += 1
            continue
        targets.add(target)

    removed = 0
    failed = invalid_paths
    revision_roots: set[Path] = set()
    for target in sorted(targets, key=lambda item: len(item.parts), reverse=True):
        try:
            if target.exists():
                shutil.rmtree(target)
            removed += 1
            revision_roots.add(target.parent)
        except OSError:
            failed += 1
            _LOG.exception("GPMHeatmap 批次已删除，但资源目录清理失败: %s", target)

    # uploads/<branch>/<batch>/<uuid> 仅是一次发布的版本目录；最多清到这一层，
    # 不删除 batch 根目录，避免与同名批次的并发重传发生竞争。
    for revision_root in revision_roots:
        try:
            revision_root.rmdir()
        except OSError:
            pass
    return removed, failed


def prune_expired_gpm_uploads(*, now: datetime | None = None) -> GpmRetentionResult:
    """事务性删除过期上报，再清理其点位截图目录。

    外键级联只覆盖 gpm_uploads -> upload_maps -> points；配置域没有到上传域的
    级联关系，因此地图、地图图片和标尺不会被本保留策略误删。
    """

    cutoff_time = retention_cutoff(now)
    cutoff = cutoff_time.isoformat(timespec="seconds")
    cutoff_epoch = int(cutoff_time.timestamp())
    connection = connect_gpm_database()
    rows = []
    asset_paths: list[str | None] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT id, branch_tag, batch_id
            FROM gpm_uploads
            WHERE captured_at_epoch < ?
            ORDER BY id
            """,
            (cutoff_epoch,),
        ).fetchall()
        if rows:
            asset_rows = connection.execute(
                """
                SELECT p.screenshot_path, p.thumbnail_path
                FROM gpm_points p
                JOIN gpm_upload_maps m ON m.id = p.upload_map_id
                JOIN gpm_uploads u ON u.id = m.upload_id
                WHERE u.captured_at_epoch < ?
                """,
                (cutoff_epoch,),
            ).fetchall()
            asset_paths = [
                row[key]
                for row in asset_rows
                for key in ("screenshot_path", "thumbnail_path")
            ]
            connection.executemany(
                "DELETE FROM gpm_uploads WHERE id = ?",
                ((row["id"],) for row in rows),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    removed, failed = remove_gpm_point_assets(asset_paths)

    result = GpmRetentionResult(
        cutoff=cutoff,
        deleted_uploads=len(rows),
        removed_asset_dirs=removed,
        failed_asset_dirs=failed,
    )
    if rows:
        _LOG.info(
            "GPMHeatmap 保留最近 %d 天，淘汰 %d 个过期批次，资源清理失败 %d 个",
            GPM_DATA_RETENTION_DAYS,
            result.deleted_uploads,
            result.failed_asset_dirs,
        )
    return result


class GpmRetentionScheduler:
    """启动即清理，此后每小时检查，避免无新上报时过期数据长期滞留。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="pixelcomp-gpm-retention",
                daemon=True,
            )
            self._thread.start()

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
                prune_expired_gpm_uploads()
            except Exception:  # noqa: BLE001 - 后台清理失败不能拖垮其他数据域
                _LOG.exception("GPMHeatmap 过期数据清理失败，稍后自动重试")
            if self._stop.wait(GPM_RETENTION_CHECK_INTERVAL_SECONDS):
                break


gpm_retention_scheduler = GpmRetentionScheduler()
