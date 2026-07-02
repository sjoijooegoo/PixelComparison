"""对比计算失败的健壮性:瞬时失败自动重试;持续失败删除空壳对比(不留'有对比没图')。"""
import time


def _make_pair(client, png_bytes):
    for bid in ("a", "b"):
        assert client.post("/api/batches", json={
            "id": bid, "scene_id": "S", "p4_version": 1,
            "platform": "Windows", "shading_quality": 4}).status_code == 201
        assert client.post(f"/api/batches/{bid}/screenshots",
                           data={"scene_name": "s1"},
                           files={"file": ("s1.png", png_bytes(), "image/png")}).status_code == 201


def _wait_task(client, task_id, timeout=20.0):
    deadline = time.time() + timeout
    t = {"status": "running"}
    while time.time() < deadline:
        t = client.get(f"/api/comparisons/tasks/{task_id}").json()
        if t.get("status") != "running":
            return t
        time.sleep(0.1)
    return t


def test_transient_failure_retries_then_succeeds(client, png_bytes, monkeypatch):
    import app.main as m
    _make_pair(client, png_bytes)

    real = m.run_comparison
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient IO")   # 第一次失败
        return real(*a, **k)                     # 之后正常算

    monkeypatch.setattr(m, "run_comparison", flaky)

    r = client.post("/api/comparisons", json={"batch_id": "b", "ref_batch_id": "a"})
    t = _wait_task(client, r.json()["task_id"])
    assert t["status"] == "done", t
    assert calls["n"] >= 2                        # 确实重试过
    assert t["comparison"]["id"]                  # 有结果
    # 热力图已生成
    lk = client.get("/api/comparisons/lookup?batch_id=b&ref_batch_id=a").json()
    assert lk["exists"] is True
    assert len(lk["heatmaps"]) >= 1


def test_persistent_failure_deletes_shell(client, png_bytes, monkeypatch):
    import app.main as m
    _make_pair(client, png_bytes)

    def always_fail(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(m, "run_comparison", always_fail)

    r = client.post("/api/comparisons", json={"batch_id": "b", "ref_batch_id": "a"})
    t = _wait_task(client, r.json()["task_id"])
    assert t["status"] == "error", t
    # 空壳对比已被删除:lookup 不存在、列表里也没有
    lk = client.get("/api/comparisons/lookup?batch_id=b&ref_batch_id=a").json()
    assert lk["exists"] is False
    listed = client.get("/api/comparisons").json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert all(not (c["batch_id"] == "b" and c["ref_batch_id"] == "a") for c in items)
