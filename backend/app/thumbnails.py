"""有界、可退出的缩略图后台生成器。

请求线程只负责命中本地缓存或回退原图；远程原图召回和 WebP 编码由少量守护线程
完成。即使共享盘 I/O 永久阻塞，守护线程也不会卡住 Python 进程退出。
"""
from __future__ import annotations

import io
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
        # generation 负责使覆盖/删除前启动的任务失效；desired 表示该路径当前仍需要
        # 一个缩略图。同路径新上传发生在旧任务执行中时无需重复入队，旧任务会丢弃
        # 结果并在原工作线程内处理最新版本。
        self._generations: dict[str, int] = {}
        self._desired: set[str] = set()
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
            for key in self._inflight:
                self._generations[key] = self._generations.get(key, 0) + 1
            self._desired.clear()
            threads = list(self._threads)

        while True:
            try:
                pending = self._queue.get_nowait()
            except queue.Empty:
                break
            if pending is not None:
                with self._lock:
                    key = pending.as_posix()
                    self._inflight.discard(key)
                    self._generations.pop(key, None)
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
            if not self._accepting:
                return False
            if key in self._inflight:
                # 普通重复请求继续去重；若路径刚被 invalidate_prefix 失效，重新标记
                # desired 即可，正在运行的工作线程会在丢弃旧结果后处理新文件。
                if key not in self._desired:
                    self._desired.add(key)
                    return True
                return False
            self._generations[key] = self._generations.get(key, 0) + 1
            self._desired.add(key)
            self._inflight.add(key)
        try:
            self._queue.put_nowait(relative_path)
            return True
        except queue.Full:
            with self._lock:
                self._inflight.discard(key)
                self._desired.discard(key)
                self._generations.pop(key, None)
            return False

    def invalidate_prefix(self, relative_prefix: Path) -> None:
        """使某目录下已排队/运行的任务失效，且与最终缓存发布互斥。

        批次删除或覆盖必须先调用本方法再删除缓存目录。若随后有同路径新上传，
        submit 会把该路径重新标记为 desired，原工作线程自动转而生成最新版本。
        """
        prefix_parts = Path(relative_prefix).parts
        with self._lock:
            for key in tuple(self._inflight):
                if Path(key).parts[:len(prefix_parts)] != prefix_parts:
                    continue
                self._generations[key] = self._generations.get(key, 0) + 1
                self._desired.discard(key)

    def cache_path(self, relative_path: Path) -> Path:
        return (self.cache_root / relative_path).with_suffix(".webp")

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            key = item.as_posix()
            try:
                while True:
                    with self._lock:
                        if not self._accepting or key not in self._desired:
                            break
                        generation = self._generations[key]
                    completed = self._generate(item, generation)
                    with self._lock:
                        if not self._accepting or key not in self._desired:
                            break
                        if self._generations.get(key) != generation:
                            continue
                        if completed:
                            self._desired.discard(key)
                            break
                        # 原图在编码期间被外部改写但没有经过 invalidate_prefix；
                        # 保持 desired，在当前工作线程中重新读取最新版本。
            except Exception as error:  # noqa: BLE001
                log.warning("缩略图后台生成失败 %s: %s", item.as_posix(), error)
            finally:
                with self._lock:
                    self._inflight.discard(key)
                    self._desired.discard(key)
                    self._generations.pop(key, None)
                self._queue.task_done()

    def _generate(self, relative_path: Path, generation: int) -> bool:
        """编码当前原图；仅在任务代次和原图版本都未变化时发布缓存。"""
        key = relative_path.as_posix()
        original = self.source_root / relative_path
        cache = self.cache_path(relative_path)
        source_stat = original.stat()
        source_version = (source_stat.st_mtime_ns, source_stat.st_size)
        if cache.is_file() and cache.stat().st_mtime_ns >= source_stat.st_mtime_ns:
            return True

        with Image.open(original) as source:
            image = source.convert("RGB")
        image.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 10))
        encoded = io.BytesIO()
        image.save(encoded, format="WEBP", quality=THUMB_QUALITY)

        # 远程 stat 仍在锁外，避免共享盘卡顿阻塞 submit/invalidate；API 覆盖和删除
        # 会先改变 generation，外部直接改文件则由前后版本比较识别。
        current_stat = original.stat()
        if (current_stat.st_mtime_ns, current_stat.st_size) != source_version:
            return False

        with self._lock:
            if (
                not self._accepting
                or key not in self._desired
                or self._generations.get(key) != generation
            ):
                return False
            cache.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_name(f".{cache.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(encoded.getvalue())
                os.replace(temporary, cache)
            finally:
                temporary.unlink(missing_ok=True)

        now = time.monotonic()
        if now - self._last_pruned >= _PRUNE_INTERVAL_SECONDS:
            self._last_pruned = now
            prune_thumbnails()
        return True
