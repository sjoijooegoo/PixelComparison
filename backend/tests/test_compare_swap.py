"""换向:同一对批次正反向只存一行,反向请求命中后返回 flip=true。"""
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
    """返回完整响应体(含 flip / comparison)。"""
    r = client.post("/api/comparisons", json={"batch_id": cur, "ref_batch_id": ref})
    assert r.status_code == 202, r.text
    body = r.json()
    if body.get("status") == "done":
        return body
    for _ in range(50):
        t = client.get(f"/api/comparisons/tasks/{body['task_id']}").json()
        if t["status"] == "done":
            return {**body, "status": "done", "comparison": t["comparison"]}
        assert t["status"] != "error", t
        time.sleep(0.2)
    raise AssertionError("comparison did not finish")


def test_reverse_hits_same_row_with_flip(client, png_bytes):
    _batch(client, "A")
    _batch(client, "B")
    # 公共检查点 + 各自独有检查点 -> A 方向:onlyA=added、onlyB=missing
    _upload(client, "A", "common", png_bytes((10, 10, 10)))
    _upload(client, "A", "onlyA", png_bytes((20, 20, 20)))
    _upload(client, "B", "common", png_bytes((200, 10, 10)))
    _upload(client, "B", "onlyB", png_bytes((30, 30, 30)))

    fwd = _run(client, "A", "B")
    assert fwd["status"] == "done"
    assert fwd.get("flip") is False
    cid = fwd["comparison"]["id"]

    # 正向(A vs B):onlyA=added(1)、onlyB=missing(1)
    counts = client.get(f"/api/comparisons/{cid}/scenes").json()["counts"]
    assert counts["added"] == 1 and counts["missing"] == 1

    # 反向请求(B vs A):命中同一行、不新建、不计算,返回 flip=true
    rev = _run(client, "B", "A")
    assert rev["status"] == "done"
    assert rev.get("flip") is True
    assert rev["comparison"]["id"] == cid

    # 全库只有一条对比记录(正反向合并)
    assert client.get("/api/comparisons").json()["total"] == 1
