"""同号批次覆盖:overwrite=false 冲突 409;overwrite=true 删旧建新(连带清对比/热力图)。"""
import time


def _batch(client, bid, scene="S", overwrite=False):
    return client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": 1, "platform": "Windows",
        "overwrite": overwrite})


def _upload(client, bid, name, data):
    return client.post(f"/api/batches/{bid}/screenshots",
                       data={"scene_name": name},
                       files={"file": (f"{name}.png", data, "image/png")})


def _run(client, cur, ref):
    r = client.post("/api/comparisons", json={"batch_id": cur, "ref_batch_id": ref})
    assert r.status_code == 202, r.text
    body = r.json()
    if body.get("status") == "done":
        return body["comparison"]["id"]
    for _ in range(50):
        t = client.get(f"/api/comparisons/tasks/{body['task_id']}").json()
        if t["status"] == "done":
            return t["comparison"]["id"]
        assert t["status"] != "error", t
        time.sleep(0.2)
    raise AssertionError("comparison did not finish")


def test_image_url_version_does_not_depend_on_file_mtime(client, png_bytes):
    """图片 URL 版本来自数据库；触碰远程文件 mtime 不应改变接口结果。"""
    import os
    import app.db
    assert _batch(client, "cb1").status_code == 201
    r = _upload(client, "cb1", "shot_01", png_bytes((10, 10, 10)))
    assert r.status_code == 201
    url1 = r.json()["url"]
    assert "/images/batches/cb1/shot_01.png?v=" in url1, url1

    # 直接改文件 mtime，接口 URL 仍保持稳定；正常覆盖会创建新的数据库缓存版本。
    p = app.db.IMAGES_DIR / "batches" / "cb1" / "shot_01.png"
    future = int(p.stat().st_mtime) + 1000
    os.utime(p, (future, future))
    url2 = client.get("/api/batches/cb1/screenshots").json()["items"][0]["url"]
    assert url2 == url1


def test_overwrite_replaces_batch_and_cascades(client, png_bytes):
    import app.db
    assert _batch(client, "b1").status_code == 201
    assert _batch(client, "b2").status_code == 201
    assert _upload(client, "b1", "shot_01", png_bytes((10, 10, 10))).status_code == 201
    assert _upload(client, "b2", "shot_01", png_bytes((200, 10, 10))).status_code == 201

    cid = _run(client, "b1", "b2")
    assert client.get("/api/comparisons").json()["total"] == 1
    heat_dir = app.db.IMAGES_DIR / "heatmaps" / str(cid)

    # 不带 overwrite:同号 -> 409
    assert _batch(client, "b1").status_code == 409

    # 带 overwrite:删旧建新 -> 201
    assert _batch(client, "b1", overwrite=True).status_code == 201
    # 旧截图已清:同名可重新上传而不 409
    assert _upload(client, "b1", "shot_01", png_bytes((20, 20, 20))).status_code == 201
    # 涉及 b1 的对比已删
    assert client.get("/api/comparisons").json()["total"] == 0
    # 热力图目录已清
    assert not heat_dir.exists()


def test_overwrite_cannot_change_batch_scene_or_platform(client):
    assert _batch(client, "scope").status_code == 201

    changed_scene = client.post("/api/batches", json={
        "id": "scope", "scene_id": "OtherScene", "platform": "Windows",
        "overwrite": True,
    })
    assert changed_scene.status_code == 409
    assert changed_scene.json()["code"] == "BATCH_SCOPE_IMMUTABLE"

    changed_platform = client.post("/api/batches", json={
        "id": "scope", "scene_id": "S", "platform": "Android",
        "overwrite": True,
    })
    assert changed_platform.status_code == 409
    assert changed_platform.json()["code"] == "BATCH_SCOPE_IMMUTABLE"

    detail = client.get("/api/batches/scope").json()
    assert (detail["scene_id"], detail["platform"]) == ("S", "Windows")
