"""列表图热力图列:只读查找端点——对比前 exists=false 不计算,对比后(正/反向)返回各检查点热力图。"""
import threading
import time


def _batch(client, bid, scene="S"):
    r = client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": 1, "platform": "Windows"})
    assert r.status_code == 201, r.text


def _upload(client, bid, name, data):
    r = client.post(f"/api/batches/{bid}/screenshots",
                    data={"scene_name": name},
                    files={"file": (f"{name}.png", data, "image/png")})
    assert r.status_code == 201, r.text


def _run(client, cur, ref, force=False):
    r = client.post("/api/comparisons", json={
        "batch_id": cur, "ref_batch_id": ref, "force": force,
    })
    assert r.status_code == 202, r.text
    body = r.json()
    if body.get("status") == "done":
        return
    for _ in range(50):
        t = client.get(f"/api/comparisons/tasks/{body['task_id']}").json()
        if t["status"] == "done":
            return
        assert t["status"] != "error", t
        time.sleep(0.2)
    raise AssertionError("comparison did not finish")


def test_lookup_before_and_after_compare(client, png_bytes):
    _batch(client, "A")
    _batch(client, "B")
    # 同名检查点、不同颜色 -> 有差异 -> 会产出热力图
    _upload(client, "A", "shot_01", png_bytes((10, 10, 10)))
    _upload(client, "B", "shot_01", png_bytes((200, 10, 10)))

    # 对比前:无缓存,不计算
    r = client.get("/api/comparisons/lookup", params={"batch_id": "A", "ref_batch_id": "B"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "exists": False,
        "status": "missing",
        "ready": False,
        "task_id": None,
        "done": 0,
        "total": 0,
    }
    assert client.get("/api/comparisons").json()["total"] == 0   # 查找未触发计算

    _run(client, "A", "B")

    # 对比后:正向与反向(忽略方向)都命中同一条,含该检查点热力图 url
    for cur, ref in (("A", "B"), ("B", "A")):
        body = client.get("/api/comparisons/lookup",
                          params={"batch_id": cur, "ref_batch_id": ref}).json()
        assert body["exists"] is True
        assert "shot_01" in body["heatmaps"]
        assert body["heatmaps"]["shot_01"].startswith("/images/")

    before = body["heatmaps"]["shot_01"]
    _run(client, "A", "B", force=True)
    after = client.get("/api/comparisons/lookup", params={
        "batch_id": "A", "ref_batch_id": "B",
    }).json()["heatmaps"]["shot_01"]
    assert before.split("?", 1)[0] == after.split("?", 1)[0]
    assert before != after


def test_lookup_and_duplicate_create_report_the_same_running_task(
    client, png_bytes, monkeypatch
):
    import app.main as main

    _batch(client, "running-current")
    _batch(client, "running-baseline")
    _upload(client, "running-current", "shot_01", png_bytes((10, 10, 10)))
    _upload(client, "running-baseline", "shot_01", png_bytes((200, 10, 10)))

    started = threading.Event()
    release = threading.Event()
    real_run = main.run_comparison

    def blocked_run(*args, **kwargs):
        started.set()
        assert release.wait(5), "test comparison was not released"
        return real_run(*args, **kwargs)

    monkeypatch.setattr(main, "run_comparison", blocked_run)
    first = client.post(
        "/api/comparisons",
        json={"batch_id": "running-current", "ref_batch_id": "running-baseline"},
    )
    assert first.status_code == 202, first.text
    task_id = first.json()["task_id"]
    assert started.wait(2)

    lookup = client.get(
        "/api/comparisons/lookup",
        params={"batch_id": "running-current", "ref_batch_id": "running-baseline"},
    ).json()
    duplicate = client.post(
        "/api/comparisons",
        json={"batch_id": "running-current", "ref_batch_id": "running-baseline"},
    ).json()

    assert lookup["exists"] is True
    assert lookup["status"] == "running"
    assert lookup["ready"] is False
    assert lookup["task_id"] == task_id
    assert lookup["heatmaps"] == {}
    assert duplicate["status"] == "running"
    assert duplicate["task_id"] == task_id

    release.set()
    deadline = time.time() + 10
    while time.time() < deadline:
        task = client.get(f"/api/comparisons/tasks/{task_id}").json()
        if task["status"] == "done":
            break
        time.sleep(0.05)
    assert task["status"] == "done", task

    completed = client.get(
        "/api/comparisons/lookup",
        params={"batch_id": "running-current", "ref_batch_id": "running-baseline"},
    ).json()
    assert completed["status"] == "done"
    assert completed["ready"] is True
    assert completed["done"] == completed["total"] == 1


def test_orphaned_empty_comparison_is_recomputed(client, png_bytes):
    _batch(client, "orphan-current")
    _batch(client, "orphan-baseline")
    _upload(client, "orphan-current", "shot_01", png_bytes((10, 10, 10)))
    _upload(client, "orphan-baseline", "shot_01", png_bytes((200, 10, 10)))

    from app.db import SessionLocal
    from app.models import Comparison

    with SessionLocal() as db:
        db.add(Comparison(batch_id="orphan-current", ref_batch_id="orphan-baseline"))
        db.commit()

    orphan = client.get(
        "/api/comparisons/lookup",
        params={"batch_id": "orphan-current", "ref_batch_id": "orphan-baseline"},
    ).json()
    assert orphan["status"] == "missing"
    assert orphan["exists"] is False
    assert orphan["ready"] is False

    _run(client, "orphan-current", "orphan-baseline")
    recovered = client.get(
        "/api/comparisons/lookup",
        params={"batch_id": "orphan-current", "ref_batch_id": "orphan-baseline"},
    ).json()
    assert recovered["status"] == "done"
    assert recovered["ready"] is True
