"""有界、可退出的缩略图后台生成器。

请求线程只负责命中本地缓存或回退原图；远程原图召回和 WebP 编码由少量守护线程
完成。即使共享盘 I/O 永久阻塞，守护线程也不会卡住 Python 进程退出。
"""
from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from pathlib import Path

from PIL import Image

from .cleanup import prune_thumbnails
from .logging_setup import log

THUMB_WIDTH = 600
THUMB_QUALITY = 80
THUMB_QUEUE_SIZE = max(1, int(os.environ.get("PIXELCOMP_THUMB_QUEUE_SIZE", "64")))
THUMB_WORKERS = max(1, min(8, int(os.environ.get("PIXELCOMP_THUMB_WORKERS", "2"))))
_PRUNE_INTERVAL_SECONDS = 6 * 3600


class ThumbnailService:
    """用守护线程生成缩略图；队列满时调用方直接回退原图。"""

    def __init__(
        self,
        source_root: Path,
        cache_root: Path,
        *,
        workers: int = THUMB_WORKERS,
        queue_size: int = THUMB_QUEUE_SIZE,
    ) -> None:
        self.source_root = Path(source_root)
        self.cache_root = Path(cache_root)
        self.workers = max(1, workers)
        self._queue: queue.Queue[Path | None] = queue.Queue(maxsize=max(1, queue_size))
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self._threads: list[threading.Thread] = []
        self._accepting = False
        self._last_pruned = 0.0

    def start(self) -> None:
        with self._lock:
            if any(thread.is_alive() for thread in self._threads):
                self._accepting = True
                return
            self.cache_root.mkdir(parents=True, exist_ok=True)
            self._accepting = True
            self._threads = [
                threading.Thread(
                    target=self._worker,
                    name=f"pixelcomp-thumb-{index + 1}",
                    daemon=True,
                )
                for index in range(self.workers)
            ]
            threads = list(self._threads)
        for thread in threads:
            thread.start()
        log.info(
            "缩略图后台生成已启用:目录=%s 并发=%d 队列=%d",
            self.cache_root, self.workers, self._queue.maxsize,
        )

    def stop(self, join_timeout: float = 0.1) -> None:
        """停止接收任务，但绝不等待卡死的远程 I/O。

        空闲线程会收到哨兵并退出；正在共享盘 I/O 的线程是 daemon，最多短暂等待后
        直接交给进程退出回收，避免 threading._shutdown 卡死。
        """
        with self._lock:
            self._accepting = False
            threads = list(self._threads)

        while True:
            try:
                pending = self._queue.get_nowait()
            except queue.Empty:
                break
            if pending is not None:
                with self._lock:
                    self._inflight.discard(pending.as_posix())
            self._queue.task_done()

        for _thread in threads:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break
        for thread in threads:
            thread.join(timeout=join_timeout)

    def submit(self, relative_path: Path) -> bool:
        relative_path = Path(relative_path)
        key = relative_path.as_posix()
        with self._lock:
            if not self._accepting or key in self._inflight:
                return False
            self._inflight.add(key)
        try:
            self._queue.put_nowait(relative_path)
            return True
        except queue.Full:
            with self._lock:
                self._inflight.discard(key)
            return False

    def cache_path(self, relative_path: Path) -> Path:
        return (self.cache_root / relative_path).with_suffix(".webp")

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            try:
                self._generate(item)
            except Exception as error:  # noqa: BLE001
                log.warning("缩略图后台生成失败 %s: %s", item.as_posix(), error)
            finally:
                with self._lock:
                    self._inflight.discard(item.as_posix())
                self._queue.task_done()

    def _generate(self, relative_path: Path) -> None:
        original = self.source_root / relative_path
        cache = self.cache_path(relative_path)
        if cache.is_file() and cache.stat().st_mtime >= original.stat().st_mtime:
            return

        with Image.open(original) as source:
            image = source.convert("RGB")
        image.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 10))
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_name(f".{cache.name}.{uuid.uuid4().hex}.tmp")
        try:
            image.save(temporary, format="WEBP", quality=THUMB_QUALITY)
            os.replace(temporary, cache)
        finally:
            temporary.unlink(missing_ok=True)

        now = time.monotonic()
        if now - self._last_pruned >= _PRUNE_INTERVAL_SECONDS:
            self._last_pruned = now
            prune_thumbnails()
