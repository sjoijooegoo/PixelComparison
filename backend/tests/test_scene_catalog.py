"""外部场景目录同步、未知场景和未配置场景显示规则。"""
import pytest


def _batch(client, batch_id: str, scene_id: str):
    response = client.post("/api/batches", json={
        "id": batch_id,
        "scene_id": scene_id,
        "platform": "Windows",
    })
    assert response.status_code == 201, response.text


def _catalog(client, scene_ids):
    response = client.put("/api/scene-catalog", json={"scene_id_order": scene_ids})
    assert response.status_code == 200, response.text
    return response.json()


def test_unconfigured_catalog_falls_back_to_sorted_discovered_scenes(client):
    _batch(client, "1", "zScene")
    _batch(client, "2", "AScene")
    _batch(client, "3", "bScene")

    catalog = client.get("/api/scene-catalog").json()
    assert catalog == {"configured": False, "scene_id_order": None}

    meta = client.get("/api/meta").json()
    assert meta["scene_ids"] == ["AScene", "bScene", "zScene"]
    assert meta["unlisted_scene_ids"] == []
    assert meta["scene_catalog_configured"] is False


def test_catalog_is_authoritative_and_keeps_unknown_scene_ids(client):
    _batch(client, "1", "ExistingVisible")
    _batch(client, "2", "ExistingHidden")

    body = _catalog(client, ["UnknownFirst", "ExistingVisible"])
    assert body == {
        "configured": True,
        "scene_id_order": ["UnknownFirst", "ExistingVisible"],
    }

    meta = client.get("/api/meta").json()
    assert meta["scene_ids"] == ["UnknownFirst", "ExistingVisible"]
    assert meta["unlisted_scene_ids"] == ["ExistingHidden"]
    assert meta["show_unlisted_scene_ids"] is False

    # 未知场景可以被选中，但当前没有批次数据。
    batches = client.get("/api/batches", params={"scene_id": "UnknownFirst"}).json()
    assert batches["total"] == 0


def test_show_unlisted_appends_discovered_scenes_after_catalog(client):
    _batch(client, "1", "zHidden")
    _batch(client, "2", "AHidden")
    _batch(client, "3", "Configured")
    _catalog(client, ["Unknown", "Configured"])

    response = client.put("/api/settings", json={"show_unlisted_scene_ids": True})
    assert response.status_code == 200, response.text

    meta = client.get("/api/meta").json()
    assert meta["scene_ids"] == ["Unknown", "Configured", "AHidden", "zHidden"]
    assert meta["unlisted_scene_ids"] == ["AHidden", "zHidden"]
    assert meta["show_unlisted_scene_ids"] is True


def test_empty_catalog_intentionally_hides_all_discovered_scenes(client):
    _batch(client, "1", "Existing")
    _catalog(client, [])

    meta = client.get("/api/meta").json()
    assert meta["scene_ids"] == []
    assert meta["unlisted_scene_ids"] == ["Existing"]

    client.put("/api/settings", json={"show_unlisted_scene_ids": True})
    assert client.get("/api/meta").json()["scene_ids"] == ["Existing"]


@pytest.mark.parametrize("scene_ids", [
    ["Scene", "Scene"],
    [""],
    [" Scene"],
    ["Scene "],
    ["x" * 256],
])
def test_invalid_catalog_is_rejected_without_changing_previous_value(client, scene_ids):
    _catalog(client, ["Kept"])

    response = client.put("/api/scene-catalog", json={"scene_id_order": scene_ids})
    assert response.status_code == 422
    assert client.get("/api/scene-catalog").json()["scene_id_order"] == ["Kept"]
