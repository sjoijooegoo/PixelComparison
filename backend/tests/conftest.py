import importlib
import io
import os
from datetime import datetime, timezone

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by an isolated temp data dir + fresh SQLite db."""
    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXELCOMP_BACKUP_ENABLED", "0")

    import app.db
    import app.backup
    import app.models
    import app.quality_runs
    import app.map_build
    import app.service
    import app.settings
    import app.cleanup
    import app.gpm_retention
    import app.thumbnails
    import app.main
    importlib.reload(app.db)
    importlib.reload(app.backup)
    importlib.reload(app.models)
    importlib.reload(app.quality_runs)
    importlib.reload(app.map_build)
    importlib.reload(app.service)
    importlib.reload(app.settings)
    importlib.reload(app.cleanup)   # app.main 从中导入 prune_orphans,须先于 app.main 重载
    importlib.reload(app.gpm_retention)
    importlib.reload(app.thumbnails)
    importlib.reload(app.main)
    # GPM 样本以 2026-08-26 为基准；固定保留策略时钟，避免测试随运行日期漂移。
    monkeypatch.setattr(
        app.gpm_retention,
        "_utc_now",
        lambda: datetime(2026, 8, 29, tzinfo=timezone.utc),
    )

    from fastapi.testclient import TestClient
    with TestClient(app.main.app) as c:
        yield c


@pytest.fixture()
def png_bytes():
    """Return a callable producing a solid-color PNG of a given size/color."""
    from PIL import Image

    def _make(color=(120, 130, 140), size=(64, 48)):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="PNG")
        return buf.getvalue()

    return _make
