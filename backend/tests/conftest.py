import importlib
import io
import os

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by an isolated temp data dir + fresh SQLite db."""
    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))

    import app.db
    import app.models
    import app.service
    import app.settings
    import app.main
    importlib.reload(app.db)
    importlib.reload(app.models)
    importlib.reload(app.service)
    importlib.reload(app.settings)
    importlib.reload(app.main)

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
