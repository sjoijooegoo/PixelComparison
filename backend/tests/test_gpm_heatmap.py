"""GPMHeatmap 最终接口的端到端测试。"""

import io
import json
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app.gpm_common import safe_segment


SEGMENTS = [
    {"color": "#52e817", "expression": "<100"},
    {"color": "#b7f400", "expression": ">=100 & <200"},
    {"color": "#ffb20a", "expression": ">=200 & <300"},
    {"color": "#ff4a0a", "expression": ">=300 & <400"},
    {"color": "#ff1111", "expression": ">=400"},
]


def _captured_at(*, days_ago=0, hours_ago=0):
    """Keep retention-sensitive tests stable as wall-clock time advances."""

    return (
        datetime(2026, 8, 29, tzinfo=timezone.utc)
        - timedelta(days=days_ago, hours=hours_ago)
    ).isoformat(timespec="seconds")


def _report(
    *,
    map_name="Village_Dimension_Main",
    platform="Android",
    quality=5,
    p4_version=2960783,
    value=258,
):
    point = {
        "index": 1,
        "screenshot_id": "1",
        "position": [-192711, 240138, 0],
        "direction": [-0.94, 0.34],
        "heat_map_data": {"Scene_DC": value, "Scene_Tris": 344696},
        "trend_data": {"Scene_DC": value, "Scene_Tris": 344696},
        "detail_data": [{
            "name": "Total",
            "treeData": [],
            "table_data": {"cols": [{"key": "dc", "name": "DC"}], "data": [[value]]},
        }],
    }
    return {"data": [{
        "map_name": map_name,
        "platform": platform,
        "shading_quality": quality,
        "p4_version": p4_version,
        "show_direction": 1,
        "heat_map": [
            {"key": "Scene_DC", "name": "场景DC", "index": 0},
            {"key": "Scene_Tris", "name": "场景面数", "index": 1},
        ],
        "trend": [
            {"key": "Scene_DC", "summary_data": {"AvgSceneDrawCall": value}},
            {"key": "Scene_Tris", "summary_data": {"AvgSceneTriangle": 344696}},
        ],
        "detail": [point],
    }]}


def _archive(png_bytes):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("1.png", png_bytes)
    return buffer.getvalue()


def _upload(
    client,
    png_bytes,
    *,
    batch_id="gpm-1",
    captured_at=None,
    branch_tag="main",
    report=None,
    overwrite=False,
):
    return client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "pipeline_data": json.dumps({
                "batch_id": batch_id,
                "batch_url": f"https://example/pipeline/{batch_id}",
                "captured_at": captured_at or _captured_at(hours_ago=1),
                "branch_tag": branch_tag,
            }),
            "overwrite": str(overwrite).lower(),
        },
        files={
            "report": ("GPMHeatmap.json", json.dumps(report or _report()).encode(), "application/json"),
            "screenshots": ("GPMScreenshot.zip", _archive(png_bytes), "application/zip"),
        },
    )


def _save_map(client, *, map_name="Village_Dimension_Main", image=None, bindings=None, revision=None):
    configuration = {
        "description": "村庄维度",
        "origin": [-251954, 201148],
        "range": [76000, 72000],
        "x_reverse": False,
        "y_reverse": True,
        "bindings": bindings or [],
    }
    if revision is not None:
        configuration["expected_revision"] = revision
    files = {"image": ("map.png", image, "image/png")} if image else None
    return client.put(
        f"/api/gpm-heatmaps/configuration/maps/{map_name}",
        data={"configuration": json.dumps(configuration)},
        files=files,
    )


def _create_scale(client, name="场景 DC 标尺"):
    return client.post(
        "/api/gpm-heatmaps/configuration/scales",
        json={"name": name, "segments": SEGMENTS},
    )


def _create_scale_set(client, scale_id, name="村庄标尺集"):
    return client.post(
        "/api/gpm-heatmaps/configuration/scale-sets",
        json={"name": name, "items": [{"metric_key": "Scene_DC", "scale_id": scale_id}]},
    )


def test_scale_set_keys_keep_their_submitted_order(client):
    scale = _create_scale(client, name="顺序测试标尺")
    assert scale.status_code == 201, scale.text
    items = [
        {"metric_key": "Scene_Tris", "scale_id": scale.json()["id"]},
        {"metric_key": "Drawcall", "scale_id": scale.json()["id"]},
        {"metric_key": "Scene_DC", "scale_id": scale.json()["id"]},
    ]

    created = client.post(
        "/api/gpm-heatmaps/configuration/scale-sets",
        json={"name": "保持添加顺序", "items": items},
    )
    assert created.status_code == 201, created.text
    assert [item["metric_key"] for item in created.json()["items"]] == [
        "Scene_Tris", "Drawcall", "Scene_DC",
    ]

    catalog = client.get("/api/gpm-heatmaps/configuration")
    assert catalog.status_code == 200, catalog.text
    restored = next(
        item for item in catalog.json()["scale_sets"] if item["id"] == created.json()["id"]
    )
    assert [item["metric_key"] for item in restored["items"]] == [
        "Scene_Tris", "Drawcall", "Scene_DC",
    ]


def test_safe_asset_segments_do_not_collapse_identifiers():
    assert safe_segment("batch", "fallback") == "batch"
    assert safe_segment(".batch", "fallback") != "batch"
    assert safe_segment("场景", "fallback") != safe_segment("地图", "fallback")


def test_canonical_upload_frame_detail_and_assets(client, png_bytes):
    uploaded = _upload(client, png_bytes())
    assert uploaded.status_code == 201, uploaded.text
    saved_map = _save_map(client, image=png_bytes(size=(775, 777)), revision=1)
    assert saved_map.status_code == 200, saved_map.text
    assert saved_map.json()["id"] == 0

    frame = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/frame",
        params={"platform": "Android", "shading_quality": 5},
    )
    assert frame.status_code == 200, frame.text
    payload = frame.json()
    assert payload["map"] == {
        "map_name": "Village_Dimension_Main",
        "show_direction": True,
    }
    assert payload["map_config"]["origin"] == [-251954, 201148]
    assert payload["points"][0]["position"] == [-192711, 240138]
    assert "detail_data" not in payload["points"][0]
    assert "trend_data" not in payload["points"][0]

    detail = client.get(f"/api/gpm-heatmaps/points/{payload['points'][0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["map_name"] == "Village_Dimension_Main"
    assert detail.json()["detail_data"][0]["name"] == "Total"
    assert client.get(payload["points"][0]["image_url"]).status_code == 200


def test_upload_is_canonical_only(client, png_bytes):
    missing_pipeline = client.post(
        "/api/gpm-heatmaps/uploads",
        files={
            "report": ("GPMHeatmap.json", json.dumps(_report()).encode(), "application/json"),
            "screenshots": ("GPMScreenshot.zip", _archive(png_bytes()), "application/zip"),
        },
    )
    assert missing_pipeline.status_code == 422

    missing_map = _report()
    missing_map["data"][0].pop("map_name")
    assert _upload(client, png_bytes(), report=missing_map).status_code == 422

    legacy_map_name = _report()
    legacy_map_name["data"][0]["pic_name"] = legacy_map_name["data"][0].pop("map_name")
    assert _upload(
        client,
        png_bytes(),
        batch_id="legacy-map-name",
        report=legacy_map_name,
    ).status_code == 201

    conflicting_map_names = _report()
    conflicting_map_names["data"][0]["pic_name"] = "Forest_WP"
    conflict = _upload(
        client,
        png_bytes(),
        batch_id="conflicting-map-name",
        report=conflicting_map_names,
    )
    assert conflict.status_code == 422
    assert conflict.json()["detail"]["code"] == "GPM_MAP_NAME_CONFLICT"

    missing_scope = _report()
    missing_scope["data"][0].pop("platform")
    assert _upload(client, png_bytes(), report=missing_scope).status_code == 422

    no_timezone = _upload(client, png_bytes(), captured_at="2026-08-26T15:00:00")
    assert no_timezone.status_code == 422
    assert no_timezone.json()["detail"]["code"] == "INVALID_CAPTURED_AT"

    non_integer_scope = _report()
    non_integer_scope["data"][0]["p4_version"] = "2960783"
    response = _upload(client, png_bytes(), report=non_integer_scope)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_P4_VERSION"

    invalid_detail = _report()
    invalid_detail["data"][0]["detail"][0]["detail_data"] = {}
    response = _upload(client, png_bytes(), report=invalid_detail)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_GPM_REPORT"

    mismatched_screenshot = _report()
    mismatched_screenshot["data"][0]["detail"][0]["screenshot_id"] = "shot-1"
    response = _upload(client, png_bytes(), report=mismatched_screenshot)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "GPM_POINT_SCREENSHOT_ID_MISMATCH"

    for field in ("heat_map_data", "trend_data", "detail_data"):
        missing_point_payload = _report()
        missing_point_payload["data"][0]["detail"][0].pop(field)
        response = _upload(
            client,
            png_bytes(),
            batch_id=f"missing-{field}",
            report=missing_point_payload,
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "INVALID_GPM_REPORT"

    mixed_scope_types = _report()
    second_map = deepcopy(mixed_scope_types["data"][0])
    second_map["map_name"] = "Forest_WP"
    second_map["shading_quality"] = "5"
    second_map["detail"][0]["index"] = 2
    second_map["detail"][0]["screenshot_id"] = "2"
    mixed_scope_types["data"].append(second_map)
    response = _upload(
        client,
        png_bytes(),
        batch_id="mixed-scope-types",
        report=mixed_scope_types,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INCONSISTENT_GPM_SCOPE"


def test_upload_enforces_point_and_decoded_image_limits(client, png_bytes, monkeypatch):
    monkeypatch.setattr("app.gpm_upload.MAX_POINT_COUNT", 0)
    too_many_points = _upload(client, png_bytes(), batch_id="too-many-points")
    assert too_many_points.status_code == 413
    assert too_many_points.json()["detail"]["code"] == "TOO_MANY_GPM_POINTS"

    monkeypatch.setattr("app.gpm_upload.MAX_POINT_COUNT", 5_000)
    monkeypatch.setattr("app.gpm_upload.MAX_SCREENSHOT_PIXELS", 1)
    oversized_pixels = _upload(client, png_bytes(), batch_id="oversized-pixels")
    assert oversized_pixels.status_code == 413
    assert oversized_pixels.json()["detail"]["code"] == "SCREENSHOT_PIXEL_LIMIT_EXCEEDED"


def test_map_upload_handles_decompression_bomb_as_validation_error(client, png_bytes, monkeypatch):
    raw_image = png_bytes()

    def raise_bomb(*_args, **_kwargs):
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr("app.gpm_map_config.Image.open", raise_bomb)
    response = _save_map(client, image=raw_image)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_MAP_IMAGE"


def test_map_name_is_the_only_map_identity(client, png_bytes):
    report = _report()
    report["data"].append(_report()["data"][0])
    response = _upload(client, png_bytes(), report=report)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DUPLICATE_GPM_MAP"


def test_catalog_uses_configured_map_order_and_batch_filters(client, png_bytes):
    assert _save_map(client, map_name="Forest_WP").status_code == 200
    assert _save_map(client, map_name="Village_Dimension_Main").status_code == 200
    assert _upload(client, png_bytes(), report=_report(map_name="Village_Dimension_Main")).status_code == 201

    catalog = client.get("/api/gpm-heatmaps/catalog").json()
    assert "scene_ids" not in catalog
    assert [item["value"] for item in catalog["maps"]] == ["Forest_WP", "Village_Dimension_Main"]
    assert catalog["maps"][0]["has_data"] is False
    assert catalog["maps"][1]["has_data"] is True

    uploads = client.get("/api/gpm-heatmaps/uploads").json()
    assert uploads["items"][0]["map_names"] == ["Village_Dimension_Main"]
    assert "scene_ids" not in uploads["items"][0]
    assert catalog["platforms"] == ["IOS", "Android", "Windows"]

    matched = client.get("/api/gpm-heatmaps/uploads", params={"map_name": "Village_Dimension_Main"})
    assert matched.status_code == 200
    assert matched.json()["total"] == 1
    assert matched.json()["items"][0]["map_names"] == ["Village_Dimension_Main"]
    assert client.get("/api/gpm-heatmaps/uploads", params={"map_name": "Forest_WP"}).json()["total"] == 0


def test_upload_list_uses_database_id_desc_instead_of_capture_time(client, png_bytes):
    assert _upload(
        client,
        png_bytes(),
        batch_id="reported-first",
        captured_at=_captured_at(hours_ago=1),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="reported-second",
        captured_at=_captured_at(days_ago=1),
    ).status_code == 201

    items = client.get("/api/gpm-heatmaps/uploads").json()["items"]

    assert [item["batch_id"] for item in items] == ["reported-second", "reported-first"]
    assert items[0]["id"] > items[1]["id"]


def test_removed_gpm_compatibility_endpoints_are_not_routable(client):
    for path in (
        "/api/gpm-heatmaps/meta",
        "/api/gpm-heatmaps/uploads/meta",
        "/api/gpm-heatmaps/project-config",
        "/api/gpm-heatmaps/project-config/scales",
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame",
    ):
        assert client.get(path).status_code == 404


def test_global_batch_identity_and_explicit_overwrite(client, png_bytes):
    assert _upload(client, png_bytes(), batch_id="shared").status_code == 201
    assert _upload(client, png_bytes(), batch_id="shared").status_code == 409
    assert _upload(client, png_bytes(), batch_id="shared", branch_tag="release").status_code == 409
    replaced = _upload(client, png_bytes(color=(1, 2, 3)), batch_id="shared", overwrite=True)
    assert replaced.status_code == 201
    assert replaced.json()["updated"] is True


def test_delete_isolated_gpm_batch(client, png_bytes):
    assert _upload(client, png_bytes(), batch_id="delete-me").status_code == 201
    deleted = client.delete("/api/gpm-heatmaps/uploads/delete-me?branch_tag=main")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get("/api/gpm-heatmaps/uploads").json()["total"] == 0


def test_unknown_upload_registers_map_and_configuration_delete_keeps_data(client, png_bytes):
    uploaded = _upload(
        client,
        png_bytes(),
        report=_report(map_name="Forest_WP"),
    )
    assert uploaded.status_code == 201, uploaded.text

    catalog = client.get("/api/gpm-heatmaps/configuration").json()
    assert catalog["maps"] == [{
        "id": 0,
        "map_name": "Forest_WP",
        "description": "Forest_WP",
        "origin": [0.0, 0.0],
        "range": [1.0, 1.0],
        "x_reverse": False,
        "y_reverse": True,
        "revision": 1,
        "image": None,
        "bindings": [],
        "created_at": catalog["maps"][0]["created_at"],
        "updated_at": catalog["maps"][0]["updated_at"],
    }]
    filters = client.get("/api/gpm-heatmaps/catalog").json()
    assert [(item["value"], item["has_data"]) for item in filters["maps"]] == [
        ("Forest_WP", True),
    ]

    scale = _create_scale(client)
    scale_set = _create_scale_set(client, scale.json()["id"])
    configured = _save_map(
        client,
        map_name="Forest_WP",
        image=png_bytes(),
        revision=1,
        bindings=[{
            "platform": "Android",
            "shading_quality": 5,
            "scale_set_id": scale_set.json()["id"],
        }],
    )
    assert configured.status_code == 200, configured.text
    image_url = configured.json()["image"]["url"]
    assert client.get(image_url).status_code == 200

    stale = client.delete(
        "/api/gpm-heatmaps/configuration/maps/Forest_WP?expected_revision=1"
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "GPM_MAP_REVISION_CONFLICT"

    deleted = client.delete(
        f"/api/gpm-heatmaps/configuration/maps/Forest_WP"
        f"?expected_revision={configured.json()['revision']}"
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "deleted": True,
        "map_name": "Forest_WP",
        "id": 0,
        "retained_upload_data": True,
    }
    assert client.get("/api/gpm-heatmaps/configuration").json()["maps"] == []
    assert client.get("/api/gpm-heatmaps/uploads").json()["total"] == 1
    assert client.get(image_url).status_code == 404

    frame = client.get(
        "/api/gpm-heatmaps/maps/Forest_WP/frame",
        params={"platform": "Android", "shading_quality": 5},
    )
    assert frame.status_code == 200, frame.text
    assert frame.json()["map_config"] is None

    repeated = client.delete(
        "/api/gpm-heatmaps/configuration/maps/Forest_WP?expected_revision=1"
    )
    assert repeated.status_code == 404

    rediscovered = _upload(
        client,
        png_bytes(),
        batch_id="gpm-2",
        report=_report(map_name="Forest_WP"),
    )
    assert rediscovered.status_code == 201, rediscovered.text
    restored = client.get("/api/gpm-heatmaps/configuration").json()["maps"]
    assert [(item["id"], item["map_name"], item["revision"]) for item in restored] == [
        (0, "Forest_WP", 1),
    ]
    assert restored[0]["bindings"] == []


def test_unknown_map_registration_rolls_back_when_upload_graph_fails(
    client, png_bytes, monkeypatch,
):
    import app.gpm_upload as gpm_upload

    insert_upload_graph = gpm_upload._insert_upload_graph

    def fail_after_insert(*args, **kwargs):
        insert_upload_graph(*args, **kwargs)
        raise RuntimeError("force transaction rollback")

    monkeypatch.setattr(gpm_upload, "_insert_upload_graph", fail_after_insert)
    with pytest.raises(RuntimeError, match="force transaction rollback"):
        _upload(
            client,
            png_bytes(),
            report=_report(map_name="Transient_WP"),
        )

    assert client.get("/api/gpm-heatmaps/configuration").json()["maps"] == []
    assert client.get("/api/gpm-heatmaps/uploads").json()["total"] == 0


def test_map_configuration_is_atomic(client, png_bytes):
    failed = _save_map(
        client,
        image=png_bytes(),
        bindings=[{"platform": "Android", "shading_quality": 5, "scale_set_id": 999}],
    )
    assert failed.status_code == 404
    assert client.get("/api/gpm-heatmaps/configuration").json()["maps"] == []

    created = _save_map(client, image=png_bytes())
    assert created.status_code == 200
    duplicate_create = _save_map(client)
    assert duplicate_create.status_code == 409
    assert duplicate_create.json()["detail"]["code"] == "GPM_MAP_NAME_EXISTS"
    stale = _save_map(client, revision=0)
    assert stale.status_code == 409
    assert client.get("/api/gpm-heatmaps/configuration").json()["maps"][0]["revision"] == 1


def test_scale_segments_sets_and_map_binding(client, png_bytes):
    scale = _create_scale(client)
    assert scale.status_code == 201, scale.text
    assert scale.json()["id"] == 0
    assert set(scale.json()) >= {"id", "name", "segments", "revision"}
    assert "thresholds" not in scale.json()
    scale_set = _create_scale_set(client, scale.json()["id"])
    assert scale_set.status_code == 201, scale_set.text
    assert scale_set.json()["id"] == 0

    # Editing ID 0 with its own unchanged name must remain an update, not be
    # mistaken for a duplicate create.  This is the exact first-row workflow
    # used by the configuration UI.
    updated_scale = client.put(
        "/api/gpm-heatmaps/configuration/scales/0",
        json={"name": scale.json()["name"], "segments": SEGMENTS, "expected_revision": 1},
    )
    assert updated_scale.status_code == 200, updated_scale.text
    assert updated_scale.json()["revision"] == 2
    updated_set = client.put(
        "/api/gpm-heatmaps/configuration/scale-sets/0",
        json={
            "name": scale_set.json()["name"],
            "items": [{"metric_key": "Scene_DC", "scale_id": 0}],
            "expected_revision": 1,
        },
    )
    assert updated_set.status_code == 200, updated_set.text
    assert updated_set.json()["revision"] == 2

    stale_set = client.put(
        "/api/gpm-heatmaps/configuration/scale-sets/0",
        json={
            "name": "不会覆盖新版本",
            "items": [{"metric_key": "Scene_DC", "scale_id": 0}],
            "expected_revision": 1,
        },
    )
    assert stale_set.status_code == 409
    assert stale_set.json()["detail"]["code"] == "GPM_METRIC_SCALE_SET_REVISION_CONFLICT"

    second_set = _create_scale_set(client, 0, name="另一套标尺集")
    assert second_set.status_code == 201, second_set.text
    duplicate_name = client.put(
        f"/api/gpm-heatmaps/configuration/scale-sets/{second_set.json()['id']}",
        json={
            "name": scale_set.json()["name"],
            "items": [{"metric_key": "Scene_DC", "scale_id": 0}],
            "expected_revision": second_set.json()["revision"],
        },
    )
    assert duplicate_name.status_code == 409
    assert duplicate_name.json()["detail"]["code"] == "GPM_METRIC_SCALE_SET_NAME_EXISTS"

    configured = _save_map(
        client,
        image=png_bytes(),
        bindings=[{"platform": "Android", "shading_quality": 5, "scale_set_id": 0}],
    )
    assert configured.status_code == 200, configured.text
    assert _upload(client, png_bytes()).status_code == 201
    frame = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/frame",
        params={"platform": "Android", "shading_quality": 5},
    ).json()
    scale_payload = frame["heat_map"][0]["scale"]
    assert scale_payload["mode"] == "configured"
    assert scale_payload["segments"] == SEGMENTS
    assert "thresholds" not in scale_payload
    assert frame["heat_map"][1]["scale"]["mode"] == "dynamic"


def test_scale_expression_gaps_are_rejected(client):
    invalid = [
        {"color": "#00ff00", "expression": "<100"},
        {"color": "#ff0000", "expression": ">=200"},
    ]
    response = client.post(
        "/api/gpm-heatmaps/configuration/scales",
        json={"name": "broken", "segments": invalid},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_GPM_SCALE_EXPRESSIONS"


def test_map_and_point_trends_use_map_name(client, png_bytes):
    assert _upload(
        client,
        png_bytes(),
        batch_id="older",
        captured_at=_captured_at(days_ago=8),
        report=_report(value=200),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="newer",
        captured_at=_captured_at(days_ago=2),
        report=_report(value=300),
    ).status_code == 201
    frame = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/frame",
        params={"platform": "Android", "shading_quality": 5},
    ).json()
    assert frame["previous_batch"]["batch_id"] == "older"
    assert frame["points"][0]["metric_change_percent"]["Scene_DC"] == 50
    assert frame["points"][0]["metric_change_percent"]["Scene_Tris"] == 0

    oldest_frame = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/frame",
        params={
            "platform": "Android", "shading_quality": 5, "batch_id": "older",
        },
    ).json()
    assert oldest_frame["previous_batch"] is None
    assert oldest_frame["points"][0]["metric_change_percent"] == {}
    scene_trend = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/trends",
        params={"platform": "Android", "shading_quality": 5, "days": 14},
    ).json()
    assert [item["metrics"]["Scene_DC"] for item in scene_trend["points"]] == [200, 300]
    point_trend = client.get(
        f"/api/gpm-heatmaps/points/{frame['points'][0]['id']}/trends",
        params={"days": 14},
    ).json()
    assert [item["metrics"]["Scene_DC"] for item in point_trend["points"]] == [200, 300]


def test_frame_uses_platform_latest_p4_and_falls_back_to_scope_highest_p4(
    client,
    png_bytes,
):
    assert _upload(
        client,
        png_bytes(),
        batch_id="scope-high-p4",
        captured_at=_captured_at(hours_ago=3),
        report=_report(p4_version=300),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="scope-newer-time-low-p4",
        captured_at=_captured_at(hours_ago=1),
        report=_report(p4_version=200),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="platform-latest-other-map",
        captured_at=_captured_at(hours_ago=4),
        report=_report(map_name="Forest_WP", quality=3, p4_version=400),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="other-platform-higher-p4",
        captured_at=_captured_at(hours_ago=1),
        report=_report(platform="IOS", p4_version=900),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="other-branch-higher-p4",
        branch_tag="develop",
        captured_at=_captured_at(hours_ago=1),
        report=_report(p4_version=1000),
    ).status_code == 201

    frame = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/frame",
        params={"branch_tag": "main", "platform": "Android", "shading_quality": 5},
    ).json()

    assert frame["latest_p4_version"] == 400
    assert frame["batch"]["batch_id"] == "scope-high-p4"
    assert [item["batch_id"] for item in frame["available_batches"]] == [
        "scope-high-p4",
        "scope-newer-time-low-p4",
    ]


def test_frame_selects_newest_capture_within_latest_p4(client, png_bytes):
    assert _upload(
        client,
        png_bytes(),
        batch_id="latest-p4-older-capture",
        captured_at=_captured_at(hours_ago=3),
        report=_report(p4_version=500),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="latest-p4-newer-capture",
        captured_at=_captured_at(hours_ago=2),
        report=_report(p4_version=500),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="lower-p4-newest-capture",
        captured_at=_captured_at(hours_ago=1),
        report=_report(p4_version=499),
    ).status_code == 201

    frame = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/frame",
        params={"branch_tag": "main", "platform": "Android", "shading_quality": 5},
    ).json()

    assert frame["latest_p4_version"] == 500
    assert frame["batch"]["batch_id"] == "latest-p4-newer-capture"
    assert [item["batch_id"] for item in frame["available_batches"]] == [
        "latest-p4-newer-capture",
        "latest-p4-older-capture",
        "lower-p4-newest-capture",
    ]


def test_frame_compares_with_previous_upload_id_in_the_same_scope(client, png_bytes):
    assert _upload(
        client,
        png_bytes(),
        batch_id="reported-first",
        captured_at=_captured_at(hours_ago=1),
        report=_report(value=200),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="other-platform",
        captured_at=_captured_at(hours_ago=2),
        report=_report(platform="IOS", value=900),
    ).status_code == 201
    assert _upload(
        client,
        png_bytes(),
        batch_id="reported-second-backfill",
        captured_at=_captured_at(days_ago=1),
        report=_report(value=300),
    ).status_code == 201

    frame = client.get(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main/frame",
        params={
            "platform": "Android",
            "shading_quality": 5,
            "batch_id": "reported-second-backfill",
        },
    ).json()

    assert frame["previous_batch"]["batch_id"] == "reported-first"
    assert frame["points"][0]["metric_change_percent"]["Scene_DC"] == 50


def test_map_preview_uses_latest_batch(client, png_bytes):
    assert _save_map(client).status_code == 200
    assert _upload(client, png_bytes()).status_code == 201
    preview = client.get(
        "/api/gpm-heatmaps/configuration/maps/Village_Dimension_Main/preview"
    )
    assert preview.status_code == 200
    assert preview.json()["source"]["batch_id"] == "gpm-1"
    assert preview.json()["points"] == [{
        "id": 1,
        "index": 1,
        "position": [-192711.0, 240138.0],
    }]


def test_retention_rejects_expired_and_prunes_graph_but_keeps_configuration(client, png_bytes):
    expired = _upload(client, png_bytes(), captured_at=_captured_at(days_ago=31))
    assert expired.status_code == 422
    assert expired.json()["detail"]["code"] == "GPM_CAPTURE_EXPIRED"

    assert _save_map(client, image=png_bytes()).status_code == 200
    assert _upload(
        client,
        png_bytes(),
        batch_id="old",
        captured_at=_captured_at(hours_ago=1),
    ).status_code == 201
    from app.gpm_retention import prune_expired_gpm_uploads

    result = prune_expired_gpm_uploads(now=datetime.now(timezone.utc) + timedelta(days=31))
    assert result.deleted_uploads == 1
    assert client.get("/api/gpm-heatmaps/uploads").json()["total"] == 0
    assert len(client.get("/api/gpm-heatmaps/configuration").json()["maps"]) == 1
