"""创建时间范围筛选:created_to 含当天(截止日 +1 天零点之前)。"""


def _batch(client, bid, captured_at, scene="S"):
    r = client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "platform": "Windows", "captured_at": captured_at})
    assert r.status_code == 201, r.text


def _ids(client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return {b["id"] for b in client.get(f"/api/batches?{qs}").json()["items"]}


def test_created_to_includes_that_day(client):
    _batch(client, "d18", "2026-06-18T09:00:00")
    _batch(client, "d20", "2026-06-20T09:27:00")   # 当天有时间分量

    # 截止 6-20 应包含 6-20 当天的批次
    assert _ids(client, created_from="2026-06-13", created_to="2026-06-20") == {"d18", "d20"}
    # 截止 6-19 不应包含 6-20
    assert _ids(client, created_from="2026-06-13", created_to="2026-06-19") == {"d18"}
    # 截止 6-20 与 6-21 对 6-20 当天结果一致
    assert "d20" in _ids(client, created_from="2026-06-13", created_to="2026-06-21")
