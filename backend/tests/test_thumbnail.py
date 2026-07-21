"""缩略图:上传预热 + 快速回退 + 缓存清理 + 可退出工作线程。"""
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


def _wait_for_idle(service, relative_path, timeout=3):
    key = Path(relative_path).as_posix()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with service._lock:
            if key not in service._inflight:
                return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for thumbnail task {key}")


def _block_first_thumbnail_resize(monkeypatch):
    """让首个工作线程在已读入旧图、尚未发布缓存的位置暂停。"""
    started = threading.Event()
    release = threading.Event()
    original_thumbnail = Image.Image.thumbnail
    calls_lock = threading.Lock()
    calls = 0

    def controlled_thumbnail(image, *args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
            first = calls == 1
        if first:
            started.set()
            release.wait(5)
        return original_thumbnail(image, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "thumbnail", controlled_thumbnail)
    return started, release


def test_thumb_generate_cache_and_cleanup(client, png_bytes):
    import app.db
    import app.main
    import app.cleanup

    big = png_bytes((20, 130, 200), size=(1600, 900))
    assert _batch(client, "b1").status_code == 201
    assert _upload(client, "b1", "shot_01", big).status_code == 201

    path = "batches/b1/shot_01.png"
    cache = app.main.THUMB_DIR / "batches" / "b1" / "shot_01.webp"
    _wait_for_file(cache)                           # 上传后后台预热，无需先访问列表图

    r = client.get(f"/thumb/{path}", follow_redirects=False)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/webp"
    assert "max-age" in r.headers.get("cache-control", "")
    # 是合法 WebP、按宽缩到 <=600、体积小于原图
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "WEBP" and img.width <= 600
    assert len(r.content) < len(big)
    assert cache.is_file()                          # 已落盘缓存

    # 历史图片/队列遗漏仍保留懒生成兜底；缺图会快速回退，最终由 /images 返回 404。
    missing = client.get("/thumb/batches/b1/nope.png", follow_redirects=False)
    assert missing.status_code == 307
    assert missing.headers["location"] == "/images/batches/b1/nope.png"
    assert missing.headers["cache-control"] == "no-store"
    assert client.get("/thumb/batches/b1/nope.png").status_code == 404

    # 批次画廊使用严格模式：缓存未生成时只排队，不允许 307 偷偷加载原图。
    strict = client.get(f"/thumb/batches/b1/nope.png?strict=true", follow_redirects=False)
    assert strict.status_code == 202
    assert "location" not in strict.headers
    assert strict.headers["cache-control"] == "no-store"
    assert strict.headers["retry-after"] == "1"

    # 覆盖同号批次:旧缩略图随之清掉
    assert _batch(client, "b1", overwrite=True).status_code == 201
    assert not cache.exists()

    # 孤儿清理:删批次后缩略图被 prune
    assert _upload(client, "b1", "shot_01", big).status_code == 201
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


def test_strict_thumb_miss_never_redirects_and_eventually_serves_webp(client, png_bytes):
    """批次画廊首次只排队，后台完成后仍从同一 strict URL 命中缩略图。"""
    import app.main

    big = png_bytes((70, 120, 190), size=(1600, 900))
    assert _batch(client, "strict-preview").status_code == 201
    assert _upload(client, "strict-preview", "shot_01", big).status_code == 201

    relative = Path("batches/strict-preview/shot_01.png")
    cache = app.main.thumbnail_service.cache_path(relative)
    _wait_for_file(cache)
    _wait_for_idle(app.main.thumbnail_service, relative)
    cache.unlink()  # 模拟历史图片或缓存淘汰后的首次画廊访问

    url = "/thumb/batches/strict-preview/shot_01.png?strict=true"
    pending = client.get(url, follow_redirects=False)
    assert pending.status_code == 202
    assert "location" not in pending.headers
    assert pending.headers["cache-control"] == "no-store"

    _wait_for_file(cache)
    ready = client.get(url, follow_redirects=False)
    assert ready.status_code == 200
    assert ready.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(ready.content)).format == "WEBP"


def test_overwrite_while_prewarming_publishes_only_new_thumbnail(
    client, png_bytes, monkeypatch,
):
    """旧任务已读图时覆盖同号批次，缓存最终必须对应新原图。"""
    import app.main

    path = Path("batches", "same", "shot.png")
    cache = app.main.THUMB_DIR / path.with_suffix(".webp")
    started, release = _block_first_thumbnail_resize(monkeypatch)

    assert _batch(client, "same").status_code == 201
    assert _upload(client, "same", "shot", png_bytes((255, 0, 0))).status_code == 201
    assert started.wait(1)
    try:
        assert _batch(client, "same", overwrite=True).status_code == 201
        assert _upload(client, "same", "shot", png_bytes((0, 0, 255))).status_code == 201
    finally:
        release.set()

    _wait_for_file(cache)
    _wait_for_idle(app.main.thumbnail_service, path)
    with Image.open(cache) as generated:
        red, _green, blue = generated.convert("RGB").getpixel((10, 10))
    assert blue > 200 and red < 30


def test_delete_while_prewarming_does_not_recreate_thumbnail(
    client, png_bytes, monkeypatch,
):
    """删除批次必须使运行中的旧任务失效，结束后不能重新写回缓存。"""
    import app.main

    path = Path("batches", "gone", "shot.png")
    cache = app.main.THUMB_DIR / path.with_suffix(".webp")
    started, release = _block_first_thumbnail_resize(monkeypatch)

    assert _batch(client, "gone").status_code == 201
    assert _upload(client, "gone", "shot", png_bytes()).status_code == 201
    assert started.wait(1)
    try:
        assert client.delete("/api/batches/gone").status_code == 200
    finally:
        release.set()

    _wait_for_idle(app.main.thumbnail_service, path)
    assert not cache.exists()


def test_source_rewrite_during_prewarm_retries_latest_file(
    client, png_bytes, monkeypatch,
):
    """绕过 API 直接改写原图时，前后版本校验也必须丢弃旧编码并重读。"""
    import app.db
    import app.main

    path = Path("batches", "rewrite", "shot.png")
    original = app.db.IMAGES_DIR / path
    cache = app.main.THUMB_DIR / path.with_suffix(".webp")
    started, release = _block_first_thumbnail_resize(monkeypatch)

    assert _batch(client, "rewrite").status_code == 201
    assert _upload(client, "rewrite", "shot", png_bytes((255, 0, 0))).status_code == 201
    assert started.wait(1)
    try:
        original.write_bytes(png_bytes((0, 0, 255)))
        changed = original.stat().st_mtime_ns + 1_000_000_000
        os.utime(original, ns=(changed, changed))
    finally:
        release.set()

    _wait_for_file(cache)
    _wait_for_idle(app.main.thumbnail_service, path)
    with Image.open(cache) as generated:
        red, _green, blue = generated.convert("RGB").getpixel((10, 10))
    assert blue > 200 and red < 30


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
    """预热读取即使卡住，上传和缓存未命中请求也都不能等待生成。"""
    import app.main

    assert _batch(client, "slow").status_code == 201
    started = threading.Event()
    release = threading.Event()

    def blocked(_relative, _generation):
        started.set()
        release.wait(5)
        return True

    monkeypatch.setattr(app.main.thumbnail_service, "_generate", blocked)
    try:
        before = time.monotonic()
        assert _upload(client, "slow", "shot", png_bytes()).status_code == 201
        upload_elapsed = time.monotonic() - before
        assert upload_elapsed < 0.5
        assert started.wait(1)

        before = time.monotonic()
        response = client.get(
            "/thumb/batches/slow/shot.png", follow_redirects=False,
        )
        elapsed = time.monotonic() - before
        assert response.status_code == 307
        assert elapsed < 0.5
    finally:
        release.set()


def test_upload_succeeds_when_thumbnail_queue_rejects(client, png_bytes, monkeypatch):
    """队列满或服务停止只跳过预热，不能把已成功落盘的截图上报改成失败。"""
    import app.main

    assert _batch(client, "full").status_code == 201
    monkeypatch.setattr(app.main.thumbnail_service, "submit", lambda _path: False)

    response = _upload(client, "full", "shot", png_bytes())
    assert response.status_code == 201
    assert client.get("/api/batches/full/screenshots").json()["total"] == 1
    assert not (
        app.main.THUMB_DIR / "batches" / "full" / "shot.webp"
    ).exists()


def test_upload_prewarms_sample_batch_and_reduces_grid_payload(client):
    """模拟一批高细节压力样本：首次打开列表图前已命中缓存，传输体积明显下降。"""
    import numpy as np
    import app.main

    assert _batch(client, "sample", scene="SampleScene").status_code == 201
    originals: list[bytes] = []
    caches: list[Path] = []

    for index in range(6):
        # 固定随机种子生成可复现的高细节压力样本，而不是极小的纯色 PNG。
        pixels = np.random.default_rng(index).integers(
            0, 256, size=(540, 960, 3), dtype=np.uint8,
        )
        buffer = io.BytesIO()
        Image.fromarray(pixels, mode="RGB").save(buffer, format="PNG")
        original = buffer.getvalue()
        name = f"shot_{index:02d}"
        originals.append(original)
        caches.append(
            app.main.THUMB_DIR / "batches" / "sample" / f"{name}.webp"
        )
        assert _upload(client, "sample", name, original).status_code == 201

    for cache in caches:
        _wait_for_file(cache, timeout=10)

    responses = [
        client.get(
            f"/thumb/batches/sample/shot_{index:02d}.png",
            follow_redirects=False,
        )
        for index in range(len(originals))
    ]
    assert all(response.status_code == 200 for response in responses)
    assert all(response.headers["content-type"] == "image/webp" for response in responses)

    original_bytes = sum(map(len, originals))
    thumbnail_bytes = sum(len(response.content) for response in responses)
    assert thumbnail_bytes < original_bytes * 0.5


def test_thumbnail_service_stop_never_waits_for_stuck_io(tmp_path):
    """守护工作线程卡在共享盘时，应用 shutdown 仍须立即返回。"""
    from app.thumbnails import ThumbnailService

    service = ThumbnailService(tmp_path / "source", tmp_path / "cache", workers=1)
    started = threading.Event()
    release = threading.Event()

    def blocked(_relative, _generation):
        started.set()
        release.wait(5)
        return True

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
