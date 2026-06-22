"""列表图热力图列:只读查找端点——对比前 exists=false 不计算,对比后(正/反向)返回各检查点热力图。"""
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


def _run(client, cur, ref):
    r = client.post("/api/comparisons", json={"batch_id": cur, "ref_batch_id": ref})
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
    assert r.json() == {"exists": False}
    assert client.get("/api/comparisons").json()["total"] == 0   # 查找未触发计算

    _run(client, "A", "B")

    # 对比后:正向与反向(忽略方向)都命中同一条,含该检查点热力图 url
    for cur, ref in (("A", "B"), ("B", "A")):
        body = client.get("/api/comparisons/lookup",
                          params={"batch_id": cur, "ref_batch_id": ref}).json()
        assert body["exists"] is True
        assert "shot_01" in body["heatmaps"]
        assert body["heatmaps"]["shot_01"].startswith("/images/")
