"""对比按时间保留:超过 COMPARISON_RETENTION_DAYS 的对比整条淘汰(记录 + 本地热力图);
近期对比保留;正在计算(_RUNNING)的即便过期也不淘汰。替代旧的「最新 100 条」计数上限。"""
import time
from datetime import datetime, timedelta


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


def _backdate(comparison_id, days):
    """把某条对比的 created_at 改到 days 天前(模拟时间流逝)。"""
    from app.db import SessionLocal
    from app.models import Comparison
    db = SessionLocal()
    db.get(Comparison, comparison_id).created_at = datetime.now() - timedelta(days=days)
    db.commit()
    db.close()


def test_evicts_expired_and_cleans_heatmap(client, png_bytes):
    import app.db
    images = app.db.IMAGES_DIR
    for bid in ("a", "b", "c", "d"):
        _batch_with_shot(client, bid, png_bytes)

    old = _run_compare(client, "b", "a")
    _keep = _run_compare(client, "c", "a")
    old_id = old["id"]
    assert (images / "heatmaps" / str(old_id)).exists()

    # 把第一条改到保留期之前(20 天 > 默认 14 天)
    _backdate(old_id, 20)

    # 再发起一条新对比 -> 创建时同步淘汰过期者 + prune 热力图(create_comparison 锁外调用)
    _run_compare(client, "d", "a")

    data = client.get("/api/comparisons").json()
    ids = [c["id"] for c in data["items"]]
    assert old_id not in ids                                     # 过期的被整条淘汰
    assert not (images / "heatmaps" / str(old_id)).exists()      # 其本地热力图已清


def test_skips_running_even_if_expired(client, png_bytes):
    import app.main
    for bid in ("a", "b", "c"):
        _batch_with_shot(client, bid, png_bytes)

    first = _run_compare(client, "b", "a")
    first_id = first["id"]
    _backdate(first_id, 20)                # 过期(> 14 天)

    # 标记为「正在计算」-> 即便过期也不该被淘汰
    app.main._RUNNING[first_id] = "fake-task"
    try:
        _run_compare(client, "c", "a")     # 触发淘汰
        ids = [c["id"] for c in client.get("/api/comparisons").json()["items"]]
        assert first_id in ids, "正在计算的对比不应被淘汰"
    finally:
        app.main._RUNNING.pop(first_id, None)
