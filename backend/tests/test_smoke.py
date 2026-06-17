import time


def test_meta_and_empty_batches(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"scene_ids", "platforms", "baselines"}

    r = client.get("/api/batches")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def _create_batch(client, batch_id, scene_id="SceneA", p4=100, platform="Windows"):
    r = client.post("/api/batches", json={
        "id": batch_id, "scene_id": scene_id,
        "p4_version": p4, "platform": platform,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, batch_id, scene_name, data):
    return client.post(
        f"/api/batches/{batch_id}/screenshots",
        data={"scene_name": scene_name},
        files={"file": (f"{scene_name}.png", data, "image/png")},
    )


def test_create_batch_and_upload(client, png_bytes):
    _create_batch(client, "b1")
    r = _upload(client, "b1", "shot_01", png_bytes())
    assert r.status_code == 201, r.text

    r = client.post("/api/batches", json={
        "id": "b1", "scene_id": "SceneA", "p4_version": 1, "platform": "Windows"})
    assert r.status_code == 409

    r = _upload(client, "b1", "shot_01", png_bytes())
    assert r.status_code == 409

    r = client.get("/api/batches/b1/screenshots")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_platform_normalized(client):
    body = _create_batch(client, "bwin", platform="WindowsEditor")
    assert body["platform"] == "Windows"


def test_path_traversal_rejected(client, png_bytes):
    _create_batch(client, "b2")
    r = _upload(client, "b2", "../evil", png_bytes())
    assert r.status_code == 400


def test_full_compare_flow(client, png_bytes):
    _create_batch(client, "base", scene_id="SceneX", p4=100)
    _create_batch(client, "cur", scene_id="SceneX", p4=200)
    for bid, color in (("base", (10, 10, 10)), ("cur", (200, 10, 10))):
        assert _upload(client, bid, "shot_01", png_bytes(color)).status_code == 201

    r = client.post("/api/comparisons", json={"batch_id": "cur", "ref_batch_id": "base"})
    assert r.status_code == 202, r.text
    body = r.json()

    if body.get("status") == "done":
        comp = body["comparison"]
    else:
        task_id = body["task_id"]
        comp = None
        for _ in range(50):
            t = client.get(f"/api/comparisons/tasks/{task_id}").json()
            if t["status"] == "done":
                comp = t["comparison"]
                break
            assert t["status"] != "error", t
            time.sleep(0.2)
        assert comp is not None, "comparison task did not finish in time"

    assert comp["scene_count"] == 1
    r = client.get(f"/api/comparisons/{comp['id']}/scenes")
    assert r.status_code == 200
    scenes = r.json()
    assert scenes["total"] == 1
    item = scenes["items"][0]
    assert item["name"] == "shot_01"
    assert item["diff_pct"] is not None

    r = client.get(f"/api/items/{item['id']}")
    assert r.status_code == 200
    assert r.json()["heatmap_url"]
