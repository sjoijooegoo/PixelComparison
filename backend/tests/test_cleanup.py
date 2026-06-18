import importlib

from PIL import Image


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))
    # Reload the whole app package against the temp data dir. app.models binds
    # Base from app.db at import, so app.db AND every module that imported Base
    # must be reloaded before app.main / app.cleanup, or create_all sees no tables.
    import app.db
    import app.models
    import app.service
    import app.settings
    import app.main
    import app.cleanup
    importlib.reload(app.db)
    importlib.reload(app.models)
    importlib.reload(app.service)
    importlib.reload(app.settings)
    importlib.reload(app.main)
    importlib.reload(app.cleanup)
    return app


def _png_file(path, color=(10, 20, 30)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path, format="PNG")


def test_orphan_dirs_and_files_removed(tmp_path, monkeypatch):
    app = _fresh(tmp_path, monkeypatch)
    images = app.db.IMAGES_DIR

    from fastapi.testclient import TestClient
    with TestClient(app.main.app) as client:
        client.post("/api/batches", json={
            "id": "live", "scene_id": "S", "p4_version": 1, "platform": "Windows"})
        import io
        buf = io.BytesIO(); Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, "PNG")
        client.post("/api/batches/live/screenshots",
                    data={"scene_name": "keep"},
                    files={"file": ("keep.png", buf.getvalue(), "image/png")})

    _png_file(images / "batches" / "ghost_batch" / "x.png")
    _png_file(images / "batches" / "live" / "stray.png")
    (images / "heatmaps" / "999").mkdir(parents=True, exist_ok=True)
    _png_file(images / "heatmaps" / "999" / "h.png")

    from app.cleanup import find_orphans, prune_orphans
    db = app.db.SessionLocal()
    try:
        before = find_orphans(db)
        assert any(d.name == "ghost_batch" for d in before["dirs"])
        assert any(d.name == "999" for d in before["dirs"])
        assert any(f.name == "stray.png" for f in before["files"])

        prune_orphans(db, dry_run=False)
        after = find_orphans(db)
        assert after["dirs"] == [] and after["files"] == []
    finally:
        db.close()

    assert (images / "batches" / "live" / "keep.png").exists()


def test_dry_run_deletes_nothing(tmp_path, monkeypatch):
    app = _fresh(tmp_path, monkeypatch)
    images = app.db.IMAGES_DIR
    _png_file(images / "batches" / "ghost" / "x.png")

    from app.cleanup import prune_orphans
    db = app.db.SessionLocal()
    try:
        prune_orphans(db, dry_run=True)
    finally:
        db.close()
    assert (images / "batches" / "ghost" / "x.png").exists()


def test_rerun_clears_stale_heatmaps(tmp_path, monkeypatch):
    import io, time
    app = _fresh(tmp_path, monkeypatch)
    images = app.db.IMAGES_DIR
    from fastapi.testclient import TestClient

    def png(c):
        b = io.BytesIO(); Image.new("RGB", (16, 16), c).save(b, "PNG"); return b.getvalue()

    def upload(client, bid, scene, c):
        return client.post(f"/api/batches/{bid}/screenshots",
                           data={"scene_name": scene},
                           files={"file": (f"{scene}.png", png(c), "image/png")})

    def run_and_wait(client, cur, ref, force=False):
        r = client.post("/api/comparisons",
                        json={"batch_id": cur, "ref_batch_id": ref, "force": force})
        body = r.json()
        if body.get("status") == "done":
            return body["comparison"]
        tid = body["task_id"]
        for _ in range(50):
            t = client.get(f"/api/comparisons/tasks/{tid}").json()
            if t["status"] == "done":
                return t["comparison"]
            assert t["status"] != "error", t
            time.sleep(0.2)
        raise AssertionError("compare did not finish")

    with TestClient(app.main.app) as client:
        for bid in ("base", "cur"):
            client.post("/api/batches", json={
                "id": bid, "scene_id": "S", "p4_version": 1, "platform": "Windows"})
        upload(client, "base", "a", (0, 0, 0)); upload(client, "cur", "a", (255, 0, 0))
        upload(client, "base", "b", (0, 0, 0)); upload(client, "cur", "b", (0, 255, 0))
        comp = run_and_wait(client, "cur", "base")
        hdir = images / "heatmaps" / str(comp["id"])
        assert (hdir / "a.webp").exists() and (hdir / "b.webp").exists()

    from sqlalchemy import delete
    from app.models import Screenshot
    db = app.db.SessionLocal()
    try:
        db.execute(delete(Screenshot).where(Screenshot.scene_name == "b"))
        db.commit()
    finally:
        db.close()

    with TestClient(app.main.app) as client:
        comp = run_and_wait(client, "cur", "base", force=True)
        hdir = images / "heatmaps" / str(comp["id"])
        assert (hdir / "a.webp").exists()
        assert not (hdir / "b.webp").exists()
