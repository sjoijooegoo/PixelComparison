"""缩略图:快速回退 + 后台生成 + 缓存清理 + 可退出工作线程。"""
import io
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image


def _batch(client, bid, scene="S", overwrite=False):
    return client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": 1, "platform": "Windows", "overwrite": overwrite})


def _upload(client, bid, name, png):
    return client.post(f"/api/batches/{bid}/screenshots",
                       data={"scene_name": name},
                       files={"file": (f"{name}.png", png, "image/png")})


def _wait_for_file(path, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def test_thumb_generate_cache_and_cleanup(client, png_bytes):
    import app.db
    import app.main
    import app.cleanup

    big = png_bytes((20, 130, 200), size=(1600, 900))
    assert _batch(client, "b1").status_code == 201
    assert _upload(client, "b1", "shot_01", big).status_code == 201

    path = "batches/b1/shot_01.png"
    cache = app.main.THUMB_DIR / "batches" / "b1" / "shot_01.webp"
    assert not cache.exists()                       # 懒生成:访问前无缓存

    # 缓存未命中时不等待编码，立即回退原图；后台随后生成本地 WebP。
    fallback = client.get(f"/thumb/{path}", follow_redirects=False)
    assert fallback.status_code == 307
    assert fallback.headers["location"] == f"/images/{path}"
    assert fallback.headers["cache-control"] == "no-store"
    _wait_for_file(cache)

    r = client.get(f"/thumb/{path}", follow_redirects=False)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/webp"
    assert "max-age" in r.headers.get("cache-control", "")
    # 是合法 WebP、按宽缩到 <=600、体积小于原图
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "WEBP" and img.width <= 600
    assert len(r.content) < len(big)
    assert cache.is_file()                          # 已落盘缓存

    # 缺图同样快速回退，最终由 /images 返回 404。
    missing = client.get("/thumb/batches/b1/nope.png", follow_redirects=False)
    assert missing.status_code == 307
    assert client.get("/thumb/batches/b1/nope.png").status_code == 404

    # 覆盖同号批次:旧缩略图随之清掉
    assert _batch(client, "b1", overwrite=True).status_code == 201
    assert not cache.exists()

    # 孤儿清理:删批次后缩略图被 prune
    assert _upload(client, "b1", "shot_01", big).status_code == 201
    client.get(f"/thumb/{path}", follow_redirects=False)
    _wait_for_file(cache)
    assert client.delete("/api/batches/b1").status_code == 200
    # 级联删除已清掉该批次缩略图目录
    assert not cache.exists()
    # 再跑一次 prune_orphans 不应报错(幂等)
    import app.db as db
    s = db.SessionLocal()
    try:
        app.cleanup.prune_orphans(s)
    finally:
        s.close()


def test_thumb_rejects_paths_outside_source_and_cache_roots(client, png_bytes):
    import app.db
    import app.main

    # 路径校验不访问远程盘，直接拒绝父目录、反斜杠和缓存目录。
    with pytest.raises(HTTPException) as exc:
        app.main._thumb_relative_path("../outside.png")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        app.main._thumb_relative_path(r"batches\safe\shot.png")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        app.main._thumb_relative_path("thumbs/batches/safe/shot.webp")
    assert exc.value.status_code == 404
    assert app.main._thumb_relative_path("batches/safe/shot.png") == Path(
        "batches", "safe", "shot.png",
    )


def test_thumb_retention_evicts_stale_and_keeps_fresh(client, png_bytes):
    import app.main
    from app.cleanup import prune_thumbnails

    big = png_bytes((20, 130, 200), size=(1600, 900))
    assert _batch(client, "rb").status_code == 201
    for name in ("old", "new"):
        assert _upload(client, "rb", name, big).status_code == 201
        client.get(f"/thumb/batches/rb/{name}.png", follow_redirects=False)

    old_cache = app.main.THUMB_DIR / "batches" / "rb" / "old.webp"
    new_cache = app.main.THUMB_DIR / "batches" / "rb" / "new.webp"
    _wait_for_file(old_cache)
    _wait_for_file(new_cache)

    # 把 old 的 mtime 回拨到 70 天前(> 60 天保留期),new 保持新鲜
    stale = time.time() - 70 * 86400
    os.utime(old_cache, (stale, stale))

    removed = prune_thumbnails(days=60)
    assert removed == 1
    assert not old_cache.exists()        # 久未访问 → 淘汰
    assert new_cache.is_file()           # 新鲜 → 保留

    # 被淘汰的缩略图可由 /thumb 端点按原图重建(无损)
    assert client.get(
        "/thumb/batches/rb/old.png", follow_redirects=False,
    ).status_code == 307
    _wait_for_file(old_cache)


def test_thumb_hit_refreshes_mtime(client, png_bytes):
    """命中缓存时刷新 mtime:让"久未访问"按访问算,经常看的不会被 60 天淘汰误删。"""
    import app.db
    import app.main

    big = png_bytes((20, 130, 200), size=(1600, 900))
    assert _batch(client, "hb").status_code == 201
    assert _upload(client, "hb", "s1", big).status_code == 201
    assert client.get(
        "/thumb/batches/hb/s1.png", follow_redirects=False,
    ).status_code == 307

    orig = app.db.IMAGES_DIR / "batches" / "hb" / "s1.png"
    cache = app.main.THUMB_DIR / "batches" / "hb" / "s1.webp"
    _wait_for_file(cache)

    # 把原图与缩略图都回拨 2 天(保持 cache.mtime >= orig.mtime 以走命中分支,
    # 且 > 1 天阈值,命中时应刷新 mtime)
    old = time.time() - 2 * 86400
    os.utime(orig, (old, old))
    os.utime(cache, (old, old))
    assert cache.stat().st_mtime < time.time() - 86400

    assert client.get("/thumb/batches/hb/s1.png").status_code == 200   # 命中 → touch
    assert cache.stat().st_mtime >= time.time() - 60                   # mtime 已刷新到接近现在


def test_thumb_cache_miss_does_not_wait_for_generation(client, png_bytes, monkeypatch):
    """远程读取即使卡住，请求也应立即 307，不占 AnyIO 请求线程。"""
    import app.main

    assert _batch(client, "slow").status_code == 201
    assert _upload(client, "slow", "shot", png_bytes()).status_code == 201
    started = threading.Event()
    release = threading.Event()

    def blocked(_relative):
        started.set()
        release.wait(5)

    monkeypatch.setattr(app.main.thumbnail_service, "_generate", blocked)
    try:
        before = time.monotonic()
        response = client.get(
            "/thumb/batches/slow/shot.png", follow_redirects=False,
        )
        elapsed = time.monotonic() - before
        assert response.status_code == 307
        assert elapsed < 0.5
        assert started.wait(1)
    finally:
        release.set()


def test_thumbnail_service_stop_never_waits_for_stuck_io(tmp_path):
    """守护工作线程卡在共享盘时，应用 shutdown 仍须立即返回。"""
    from app.thumbnails import ThumbnailService

    service = ThumbnailService(tmp_path / "source", tmp_path / "cache", workers=1)
    started = threading.Event()
    release = threading.Event()

    def blocked(_relative):
        started.set()
        release.wait(5)

    service._generate = blocked
    service.start()
    assert service.submit(Path("batches/1/shot.png"))
    assert started.wait(1)
    threads = list(service._threads)
    try:
        before = time.monotonic()
        service.stop(join_timeout=0.01)
        assert time.monotonic() - before < 0.2
        assert threads[0].daemon and threads[0].is_alive()
    finally:
        release.set()
        threads[0].join(timeout=1)
