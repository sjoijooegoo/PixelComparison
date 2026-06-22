"""/images 静态原图带缓存头(放大/详情二次查看走浏览器缓存)。"""


def test_images_have_cache_control(client, png_bytes):
    assert client.post("/api/batches", json={
        "id": "c1", "scene_id": "S", "platform": "Windows"}).status_code == 201
    assert client.post("/api/batches/c1/screenshots",
                       data={"scene_name": "shot_01"},
                       files={"file": ("shot_01.png", png_bytes(), "image/png")}).status_code == 201

    r = client.get("/images/batches/c1/shot_01.png")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "max-age" in cc, cc
    # StaticFiles 仍提供条件请求所需的校验头
    assert r.headers.get("etag") or r.headers.get("last-modified")
