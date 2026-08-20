"""有界守护线程任务池；停止服务时不会因远程图片 I/O 阻塞进程退出。"""
from __future__ import annotations

import os
import queue
import threading
import logging
from collections.abc import Callable


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


class BoundedDaemonExecutor:
    def __init__(self, name: str, workers_env: str, default_workers: int = 2) -> None:
        self.name = name
        self.max_workers = _env_int(workers_env, default_workers, 1, 4)
        self.max_queue = _env_int(
            f"{workers_env}_QUEUE", self.max_workers * 8, self.max_workers, 128
        )
        self._queue: queue.Queue = queue.Queue(maxsize=self.max_queue)
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._sentinel = object()

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        with self._lock:
            if any(thread.is_alive() for thread in self._threads):
                return
            self._threads = []
            for index in range(self.max_workers):
                thread = threading.Thread(
                    target=self._worker,
                    name=f"{self.name}-{index + 1}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)

    def submit(self, fn: Callable, *args, **kwargs) -> bool:
        self.start()
        try:
            self._queue.put_nowait((fn, args, kwargs))
            return True
        except queue.Full:
            return False

    def stop(self) -> None:
        with self._lock:
            threads = list(self._threads)
            self._threads = []
        for _ in threads:
            try:
                self._queue.put_nowait(self._sentinel)
            except queue.Full:
                break
        for thread in threads:
            thread.join(timeout=1)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._sentinel:
                    return
                fn, args, kwargs = item
                try:
                    fn(*args, **kwargs)
                except Exception:  # noqa: BLE001
                    logging.getLogger("pixelcomp").exception(
                        "后台任务执行器 %s 的任务异常", self.name
                    )
            finally:
                self._queue.task_done()
