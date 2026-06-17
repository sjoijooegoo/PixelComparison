def _seed(client, n):
    for i in range(n):
        r = client.post("/api/batches", json={
            "id": f"b{i:02d}", "scene_id": "S", "p4_version": i, "platform": "Windows"})
        assert r.status_code == 201, r.text


def test_no_params_returns_all(client):
    _seed(client, 5)
    body = client.get("/api/batches").json()
    assert body["total"] == 5
    assert len(body["items"]) == 5


def test_pagination_slices(client):
    _seed(client, 5)
    p1 = client.get("/api/batches", params={"page": 1, "page_size": 2}).json()
    assert p1["total"] == 5
    assert p1["page"] == 1 and p1["page_size"] == 2
    assert len(p1["items"]) == 2

    p3 = client.get("/api/batches", params={"page": 3, "page_size": 2}).json()
    assert len(p3["items"]) == 1

    ids_p1 = {b["id"] for b in p1["items"]}
    ids_p2 = {b["id"] for b in client.get(
        "/api/batches", params={"page": 2, "page_size": 2}).json()["items"]}
    assert ids_p1.isdisjoint(ids_p2)


def test_pagination_respects_filters(client):
    _seed(client, 3)
    client.post("/api/batches", json={
        "id": "other", "scene_id": "OTHER", "p4_version": 9, "platform": "Windows"})
    body = client.get("/api/batches", params={
        "scene_id": "S", "page": 1, "page_size": 10}).json()
    assert body["total"] == 3
