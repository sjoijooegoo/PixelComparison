def _batch(client, bid, captured_at, scene="S", platform="Windows"):
    r = client.post("/api/batches", json={
        "id": bid, "scene_id": scene, "p4_version": 1, "platform": platform,
        "captured_at": captured_at})
    assert r.status_code == 201, r.text


def _shot(client, bid, name, png_bytes, frame_index=None):
    data = {"scene_name": name}
    if frame_index is not None:
        data["frame_index"] = frame_index
    return client.post(f"/api/batches/{bid}/screenshots", data=data,
                       files={"file": (f"{name}.png", png_bytes(), "image/png")})


def test_scene_grid_alignment_and_order(client, png_bytes):
    # old 早于 new(按 captured_at);old 有 shot_01/shot_02,new 缺 shot_02
    _batch(client, "old", "2024-01-01T10:00:00")
    _batch(client, "new", "2024-02-01T10:00:00")
    assert _shot(client, "old", "shot_01", png_bytes, 0).status_code == 201
    assert _shot(client, "old", "shot_02", png_bytes, 1).status_code == 201
    assert _shot(client, "new", "shot_01", png_bytes, 0).status_code == 201

    g = client.get("/api/scenes/S/grid").json()
    # 列:创建时间升序(左早右晚)
    assert [b["id"] for b in g["batches"]] == ["old", "new"]
    # 行:按 frame_index -> shot_01, shot_02
    assert [r["scene_name"] for r in g["rows"]] == ["shot_01", "shot_02"]
    # shot_01 两批都有
    row1 = g["rows"][0]
    assert row1["cells"][0] and row1["cells"][1]
    assert row1["cells"][0].startswith("/images/")
    # shot_02 仅 old 有 -> new 那格为 null
    row2 = g["rows"][1]
    assert row2["cells"][0] and row2["cells"][1] is None


def test_scene_grid_platform_filter(client, png_bytes):
    _batch(client, "w", "2024-01-01T10:00:00", platform="Windows")
    _batch(client, "a", "2024-01-02T10:00:00", platform="Android")
    _shot(client, "w", "s", png_bytes)
    _shot(client, "a", "s", png_bytes)
    g = client.get("/api/scenes/S/grid", params={"platform": "Windows"}).json()
    assert [b["id"] for b in g["batches"]] == ["w"]


def test_scene_grid_unknown_scene_empty(client):
    g = client.get("/api/scenes/nope/grid").json()
    assert g["batches"] == [] and g["rows"] == []
