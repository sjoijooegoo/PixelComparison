"""缩略图:懒生成 + 缓存 + 随批次清理 + 孤儿清理 + 久未访问淘汰。"""
import io
import os
import time

from PIL import Image


def _batch(client, bid, scene="S", overwrite=False):
    return client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": 1, "platform": "Windows", "overwrite": overwrite})


def _upload(client, bid, name, png):
    return client.post(f"/api/batches/{bid}/screenshots",
                       data={"scene_name": name},
                       files={"file": (f"{name}.png", png, "image/png")})


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

    r = client.get(f"/thumb/{path}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/webp"
    assert "max-age" in r.headers.get("cache-control", "")
    # 是合法 WebP、按宽缩到 <=600、体积小于原图
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "WEBP" and img.width <= 600
    assert len(r.content) < len(big)
    assert cache.is_file()                          # 已落盘缓存

    # 缺图 -> 404
    assert client.get("/thumb/batches/b1/nope.png").status_code == 404

    # 覆盖同号批次:旧缩略图随之清掉
    assert _batch(client, "b1", overwrite=True).status_code == 201
    assert not cache.exists()

    # 孤儿清理:删批次后缩略图被 prune
    assert _upload(client, "b1", "shot_01", big).status_code == 201
    client.get(f"/thumb/{path}")
    assert cache.is_file()
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


def test_thumb_retention_evicts_stale_and_keeps_fresh(client, png_bytes):
    import app.main
    from app.cleanup import prune_thumbnails

    big = png_bytes((20, 130, 200), size=(1600, 900))
    assert _batch(client, "rb").status_code == 201
    for name in ("old", "new"):
        assert _upload(client, "rb", name, big).status_code == 201
        client.get(f"/thumb/batches/rb/{name}.png")

    old_cache = app.main.THUMB_DIR / "batches" / "rb" / "old.webp"
    new_cache = app.main.THUMB_DIR / "batches" / "rb" / "new.webp"
    assert old_cache.is_file() and new_cache.is_file()

    # 把 old 的 mtime 回拨到 70 天前(> 60 天保留期),new 保持新鲜
    stale = time.time() - 70 * 86400
    os.utime(old_cache, (stale, stale))

    removed = prune_thumbnails(days=60)
    assert removed == 1
    assert not old_cache.exists()        # 久未访问 → 淘汰
    assert new_cache.is_file()           # 新鲜 → 保留

    # 被淘汰的缩略图可由 /thumb 端点按原图重建(无损)
    assert client.get("/thumb/batches/rb/old.png").status_code == 200
    assert old_cache.is_file()


def test_thumb_hit_refreshes_mtime(client, png_bytes):
    """命中缓存时刷新 mtime:让"久未访问"按访问算,经常看的不会被 60 天淘汰误删。"""
    import app.db
    import app.main

    big = png_bytes((20, 130, 200), size=(1600, 900))
    assert _batch(client, "hb").status_code == 201
    assert _upload(client, "hb", "s1", big).status_code == 201
    assert client.get("/thumb/batches/hb/s1.png").status_code == 200   # 生成

    orig = app.db.IMAGES_DIR / "batches" / "hb" / "s1.png"
    cache = app.main.THUMB_DIR / "batches" / "hb" / "s1.webp"

    # 把原图与缩略图都回拨 2 天(保持 cache.mtime >= orig.mtime 以走命中分支,
    # 且 > 1 天阈值,命中时应刷新 mtime)
    old = time.time() - 2 * 86400
    os.utime(orig, (old, old))
    os.utime(cache, (old, old))
    assert cache.stat().st_mtime < time.time() - 86400

    assert client.get("/thumb/batches/hb/s1.png").status_code == 200   # 命中 → touch
    assert cache.stat().st_mtime >= time.time() - 60                   # mtime 已刷新到接近现在
