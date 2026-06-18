import time


def _batch(client, bid, scene="S", p4=100, platform="Windows"):
    r = client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": p4, "platform": platform})
    assert r.status_code == 201, r.text


def _shot(client, bid, png_bytes, name="shot_01"):
    return client.post(
        f"/api/batches/{bid}/screenshots",
        data={"scene_name": name},
        files={"file": (f"{name}.png", png_bytes(), "image/png")},
    )


def _ids(client):
    return [b["id"] for b in client.get("/api/batches").json()["items"]]


def _run_compare(client, cur, ref):
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


def test_delete_unknown_batch_404(client):
    assert client.delete("/api/batches/nope").status_code == 404


def test_delete_batch_cascades_comparison_and_files(client, png_bytes):
    import app.db
    images = app.db.IMAGES_DIR

    _batch(client, "base", scene="X", p4=100)
    _batch(client, "cur", scene="X", p4=200)
    for bid in ("base", "cur"):
        assert _shot(client, bid, png_bytes).status_code == 201
    _run_compare(client, "cur", "base")
    assert client.get("/api/comparisons").json()["total"] == 1
    assert (images / "batches" / "cur").is_dir()

    r = client.delete("/api/batches/cur")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert r.json()["comparisons_removed"] == 1

    assert "cur" not in _ids(client)
    assert client.get("/api/comparisons").json()["total"] == 0
    assert not (images / "batches" / "cur").exists()


def test_delete_batch_used_as_ref_removes_comparison(client, png_bytes):
    _batch(client, "ref", scene="Y", p4=100)
    _batch(client, "new", scene="Y", p4=200)
    for bid in ("ref", "new"):
        assert _shot(client, bid, png_bytes).status_code == 201
    _run_compare(client, "new", "ref")
    assert client.get("/api/comparisons").json()["total"] == 1

    # 删的是被当作参照(ref)的批次
    assert client.delete("/api/batches/ref").status_code == 200
    assert "ref" not in _ids(client)
    assert client.get("/api/comparisons").json()["total"] == 0


def test_delete_blocked_when_comparison_running(client, png_bytes, monkeypatch):
    import app.main as m

    _batch(client, "rb", scene="Z", p4=100)
    _batch(client, "rc", scene="Z", p4=200)
    for bid in ("rb", "rc"):
        assert _shot(client, bid, png_bytes).status_code == 201
    cid = _run_compare(client, "rc", "rb")

    # 模拟该对比正在后台计算
    monkeypatch.setitem(m._RUNNING, cid, "fake-task")
    assert client.delete("/api/batches/rc").status_code == 409
    # 恢复后可正常删除
    m._RUNNING.pop(cid, None)
    assert client.delete("/api/batches/rc").status_code == 200
