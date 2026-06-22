"""缩略图:懒生成 + 缓存 + 随批次清理 + 孤儿清理。"""
import io

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
