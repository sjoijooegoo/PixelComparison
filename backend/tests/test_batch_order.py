"""批次列表默认排序:批次号大的在前(按数值,不是字符串字典序)。"""


def test_batches_sorted_by_numeric_id_desc(client):
    for bid in ("2", "100", "10", "37"):
        assert client.post("/api/batches", json={
            "id": bid, "scene_id": "S", "p4_version": 1, "platform": "Windows"}).status_code == 201

    ids = [b["id"] for b in client.get("/api/batches").json()["items"]]
    # 数值降序 100 > 37 > 10 > 2;若按字符串会得到 ["37","2","100","10"] 之类
    assert ids == ["100", "37", "10", "2"], ids


def test_batch_order_pagination_stable_when_time_collides(client):
    """created_at 全相同(模拟 --time 固定)时,靠 id 数值排序,分页仍不重不漏、全局有序。"""
    same = "2026-06-29T09:17:00"
    ids = [str(i) for i in (5, 50, 500, 3, 30, 300, 1)]
    for bid in ids:
        assert client.post("/api/batches", json={
            "id": bid, "scene_id": "S", "p4_version": 1,
            "platform": "Windows", "captured_at": same}).status_code == 201

    collected, page = [], 1
    while True:
        r = client.get(f"/api/batches?page={page}&page_size=2").json()
        collected += [b["id"] for b in r["items"]]
        if page * 2 >= r["total"]:
            break
        page += 1

    assert len(collected) == len(ids)                       # 不漏
    assert len(set(collected)) == len(ids)                  # 不重
    assert collected == sorted(ids, key=int, reverse=True)  # 全局数值降序


def test_batch_order_nonnumeric_id_does_not_crash(client):
    """混入非数字 id 不报错;数字按数值在前,非数字(CAST=0)沉底。"""
    for bid in ("7", "alpha", "3"):
        assert client.post("/api/batches", json={
            "id": bid, "scene_id": "S", "p4_version": 1, "platform": "Windows"}).status_code == 201
    ids = [b["id"] for b in client.get("/api/batches").json()["items"]]
    assert ids[:2] == ["7", "3"], ids          # 数字优先、数值降序
    assert "alpha" in ids                       # 非数字仍在列、不崩
