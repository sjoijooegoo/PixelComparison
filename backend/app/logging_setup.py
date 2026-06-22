"""统一日志:控制台 + 本地滚动文件(中文友好)。

- 后端日志器 `pixelcomp` 与 uvicorn 日志一起输出到控制台与 `data/logs/backend.log`。
- 前端日志器 `pixelcomp.client`(经 /api/client-logs 上报)写入 `data/logs/frontend.log`。
- `setup_logging()` 幂等:多次调用(如测试反复 reload)不会重复挂 handler。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .db import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_FMT = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_MAX_BYTES = 5 * 1024 * 1024
_BACKUPS = 5

log = logging.getLogger("pixelcomp")             # 后端业务日志
client_log = logging.getLogger("pixelcomp.client")  # 前端上报日志

_configured = False


def _file_handler(name: str) -> RotatingFileHandler:
    h = RotatingFileHandler(LOG_DIR / name, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
    h.setFormatter(_FMT)
    return h


def setup_logging() -> None:
    """配置控制台 + 文件日志;幂等。"""
    global _configured
    if _configured:
        return

    console = logging.StreamHandler()
    console.setFormatter(_FMT)
    backend_file = _file_handler("backend.log")

    # 后端业务 + uvicorn:控制台 + backend.log
    for name in ("pixelcomp", "uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.handlers = [console, backend_file]
        lg.propagate = False

    # 前端上报日志:控制台 + frontend.log(独立文件)
    client_log.setLevel(logging.INFO)
    client_log.handlers = [console, _file_handler("frontend.log")]
    client_log.propagate = False

    _configured = True
    log.info("日志已启用 -> %s", LOG_DIR)
