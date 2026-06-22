import time


def _batch_with_shot(client, bid, png_bytes, scene="S"):
    r = client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": 1, "platform": "Windows"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/batches/{bid}/screenshots",
                    data={"scene_name": "shot_01"},
                    files={"file": ("shot_01.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text


def _run_compare(client, cur, ref):
    r = client.post("/api/comparisons", json={"batch_id": cur, "ref_batch_id": ref})
    assert r.status_code == 202, r.text
    body = r.json()
    if body.get("status") == "done":
        return body["comparison"]
    for _ in range(50):
        t = client.get(f"/api/comparisons/tasks/{body['task_id']}").json()
        if t["status"] == "done":
            return t["comparison"]
        assert t["status"] != "error", t
        time.sleep(0.2)
    raise AssertionError("comparison did not finish")


def test_cap_evicts_oldest(client, png_bytes, monkeypatch):
    import app.main
    import app.db
    monkeypatch.setattr(app.main, "_MAX_COMPARISONS", 3)
    images = app.db.IMAGES_DIR

    for bid in ("a", "b", "c", "d"):
        _batch_with_shot(client, bid, png_bytes)

    # 4 对不同的无方向批次对(正反向视作同一对),按顺序创建;cap=3 -> 第 4 次淘汰最早的一条
    pairs = [("b", "a"), ("c", "a"), ("c", "b"), ("d", "a")]
    comps = [_run_compare(client, cur, ref) for cur, ref in pairs]
    first_id = comps[0]["id"]

    data = client.get("/api/comparisons").json()
    assert data["total"] == 3
    ids = [c["id"] for c in data["items"]]
    assert first_id not in ids                       # 最早的被淘汰
    assert not (images / "heatmaps" / str(first_id)).exists()   # 其热力图目录已清


def test_cap_skips_running(client, png_bytes, monkeypatch):
    import app.main
    monkeypatch.setattr(app.main, "_MAX_COMPARISONS", 2)

    for bid in ("a", "b", "c"):
        _batch_with_shot(client, bid, png_bytes)

    comps = [_run_compare(client, cur, ref) for cur, ref in (("b", "a"), ("c", "a"))]
    first_id = comps[0]["id"]

    # 把最早的一条标记为"正在计算" -> 即便最旧也不该被淘汰
    app.main._RUNNING[first_id] = "fake-task"
    try:
        _run_compare(client, "c", "b")   # 第 3 条 -> 触发淘汰
        data = client.get("/api/comparisons").json()
        assert data["total"] == 2
        assert first_id in [c["id"] for c in data["items"]]
    finally:
        app.main._RUNNING.pop(first_id, None)
