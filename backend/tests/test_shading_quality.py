def test_shading_quality_stored_and_labeled(client):
    r = client.post("/api/batches", json={
        "id": "bq5", "scene_id": "SceneA", "p4_version": 100,
        "platform": "Windows", "shading_quality": 5,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["shading_quality"] == 5
    assert body["shading_quality_label"] == "电影"


def test_shading_quality_defaults_to_extreme_when_missing(client):
    # 旧数据/未上报该字段 -> 按 4(极致)展示
    r = client.post("/api/batches", json={
        "id": "bqnone", "scene_id": "SceneA", "p4_version": 100, "platform": "Windows",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["shading_quality"] == 4
    assert body["shading_quality_label"] == "极致"

    # 列表 DTO 同样带标签
    listed = client.get("/api/batches").json()["items"]
    assert all("shading_quality_label" in b for b in listed)


def test_shading_quality_filter(client):
    client.post("/api/batches", json={
        "id": "f5", "scene_id": "SceneF", "p4_version": 1, "platform": "Windows", "shading_quality": 5})
    client.post("/api/batches", json={
        "id": "f2", "scene_id": "SceneF", "p4_version": 2, "platform": "Windows", "shading_quality": 2})
    # 无画质字段 -> 视为默认 4(极致)
    client.post("/api/batches", json={
        "id": "fnone", "scene_id": "SceneF", "p4_version": 3, "platform": "Windows"})

    assert client.get("/api/batches?shading_quality=5").json()["total"] == 1
    assert client.get("/api/batches?shading_quality=2").json()["total"] == 1
    # 筛「极致」(4) 命中显式 4 与 NULL 旧数据
    assert client.get("/api/batches?shading_quality=4").json()["total"] == 1
    assert client.get("/api/batches?shading_quality=0").json()["total"] == 0


def test_shading_quality_in_comparison_dto(client, png_bytes):
    for bid, p4 in (("qbase", 100), ("qcur", 200)):
        assert client.post("/api/batches", json={
            "id": bid, "scene_id": "SceneQ", "p4_version": p4,
            "platform": "Windows", "shading_quality": 3,
        }).status_code == 201
        assert client.post(
            f"/api/batches/{bid}/screenshots",
            data={"scene_name": "shot_01"},
            files={"file": ("shot_01.png", png_bytes(), "image/png")},
        ).status_code == 201

    r = client.post("/api/comparisons", json={"batch_id": "qcur", "ref_batch_id": "qbase"})
    assert r.status_code == 202, r.text
    body = r.json()
    if body.get("status") == "done":
        comp = body["comparison"]
    else:
        import time
        comp = None
        for _ in range(50):
            t = client.get(f"/api/comparisons/tasks/{body['task_id']}").json()
            if t["status"] == "done":
                comp = t["comparison"]
                break
            assert t["status"] != "error", t
            time.sleep(0.2)
        assert comp is not None
    assert comp["shading_quality"] == 3
    assert comp["shading_quality_label"] == "精美"
