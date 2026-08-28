"""GPMHeatmap 独立上传、资源和读取链路。"""

import io
import json
import zipfile

import pytest

from app.gpm_common import safe_segment


def _report(
    *, point_key=None, embedded_metadata=False, summary_values=None, map_name=None,
    extra_metric=None,
):
    summary_values = summary_values or {
        "Scene_DC": 234.5,
        "Scene_Tris": 334627.5,
        "Drawcall": 311.25,
        "Triangle": 412532.5,
    }
    point = {
        "index": 1,
        "screenshot_id": 1,
        "position": [-192711, 240138, 0],
        "direction": [-0.94, 0.34],
        "view": {"PosX": 0, "PosY": 0},
        "heat_map_data": {"Scene_DC": 258, "Scene_Tris": 344696},
        "trend_data": {"Scene_DC": 258, "Scene_Tris": 344696},
        "detail_data": [{
            "name": "Total:当前画面总的DC和面数",
            "treeData": [],
            "table_data": {
                "cols": [{"key": "TotalDC", "name": "总DC"}],
                "data": [[258]],
            },
        }],
    }
    if point_key is not None:
        point["point_key"] = point_key
    scene = {
        "pic_id": 114,
        "pic_name": "Village_Dimension_Main",
        "show_z": 0,
        "show_direction": 1,
        "x_reverse": 0,
        "y_reverse": 1,
        "heat_map": [
            {"key": "Scene_DC", "name": "场景DC", "index": 0},
            {"key": "Scene_Tris", "name": "场景面数", "index": 1},
        ],
        "trend": [
            {
                "key": "Scene_DC", "name": "Scene_DC", "index": 0,
                "summary_data": {"AvgSceneDrawCall": summary_values["Scene_DC"]},
            },
            {
                "key": "Scene_Tris", "name": "Scene_Tris", "index": 1,
                "summary_data": {"AvgSceneTriangle": summary_values["Scene_Tris"]},
            },
            {
                "key": "Drawcall", "name": "Drawcall", "index": 2,
                "summary_data": {"AvgDrawCall": summary_values["Drawcall"]},
            },
            {
                "key": "Triangle", "name": "Triangle", "index": 3,
                "summary_data": {"AvgTriangle": summary_values["Triangle"]},
            },
        ],
        "detail": [point],
    }
    if extra_metric is not None:
        metric_key, metric_value = extra_metric
        scene["heat_map"].append({
            "key": metric_key, "name": metric_key, "index": len(scene["heat_map"]),
        })
        point["heat_map_data"][metric_key] = metric_value
    if map_name is not None:
        scene["map_name"] = map_name
    if embedded_metadata:
        scene.update({"p4_version": "2960783", "platform": "Android", "shading_quality": 5})
    return {
        "data": [{
            **scene,
        }],
    }


def _archive(png_bytes, *, screenshot_name="1.jpg"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(screenshot_name, png_bytes)
    return buffer.getvalue()


def _archive_entries(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _map_form(png_bytes, *, filename="map.png"):
    return {
        "data": {
            "origin_x": "-251954", "origin_y": "201148",
            "range_x": "76000", "range_y": "72000",
            "x_reverse": "false", "y_reverse": "true",
            "color_ranges": json.dumps({"Scene_DC": [150, 300, 450]}),
        },
        "files": {"image": (filename, png_bytes, "image/png")},
    }


def _project_config(*maps):
    return {
        "GpmConfig": list(maps) or [{
            "desc": "Village_Dimension_Main",
            "start_pos": [-251954, 201148],
            "map_size": [76000, 72000],
            "pic_name": "Village_Dimension_Main",
            "map_id": 114,
        }],
        "AreaNames": ["村庄"],
    }


def _import_project_config(client, payload, filename="DataForInstance.json"):
    return client.post(
        "/api/gpm-heatmaps/project-config/import",
        files={"config": (filename, json.dumps(payload).encode(), "application/json")},
    )


def test_gpm_safe_asset_segments_do_not_collapse_distinct_identifiers():
    assert safe_segment("batch", "fallback") == "batch"
    assert safe_segment(".batch", "fallback") != "batch"
    assert safe_segment("场景", "fallback") != safe_segment("地图", "fallback")


def _upload(
    client, png_bytes, *, batch_id="gpm-1", overwrite=False, point_key=None,
    captured_at="2026-08-26T15:00:00+08:00", p4_version="2960783",
    summary_values=None, branch_tag="main", map_name=None, extra_metric=None,
    platform="Android", report_payload=None,
):
    return client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "batch_id": batch_id,
            "branch_tag": branch_tag,
            "batch_url": "https://example/pipeline/gpm-1",
            "captured_at": captured_at,
            "p4_version": p4_version,
            "platform": platform,
            "shading_quality": "5",
            "overwrite": str(overwrite).lower(),
        },
        files={
            "report": (
                "GPMHeatmap.json",
                json.dumps(report_payload or _report(
                    point_key=point_key, summary_values=summary_values, map_name=map_name,
                    extra_metric=extra_metric,
                )).encode(),
                "application/json",
            ),
            "screenshots": ("GPMScreenshot.zip", _archive(png_bytes), "application/zip"),
        },
    )


def _canonical_upload(client, png_bytes, *, batch_id="gpm-canonical", overwrite=False):
    return client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "pipeline_data": json.dumps({
                "batch_id": batch_id,
                "batch_url": f"https://example/pipeline/{batch_id}",
                "captured_at": "2026-08-26T15:00:00+08:00",
                "branch_tag": "main",
            }),
            "overwrite": str(overwrite).lower(),
        },
        files={
            "report": (
                "GPMHeatmap.json",
                json.dumps(_report(embedded_metadata=True)).encode(),
                "application/json",
            ),
            "screenshots": ("GPMScreenshot.zip", _archive(png_bytes), "application/zip"),
        },
    )


def test_gpm_upload_map_frame_detail_and_assets(client, png_bytes):
    uploaded = _upload(client, png_bytes())
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json() == {
        "id": 1,
        "batch_id": "gpm-1",
        "branch_tag": "main",
        "scene_count": 1,
        "point_count": 1,
        "updated": False,
    }

    map_response = client.post(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main",
        **_map_form(png_bytes(size=(775, 777))),
    )
    assert map_response.status_code == 201, map_response.text

    meta = client.get("/api/gpm-heatmaps/meta").json()
    assert meta["platforms"] == ["Android"]
    assert meta["shading_qualities"] == [{"value": 5, "label": "电影"}]
    assert meta["scene_ids"][0]["value"] == "Village_Dimension_Main"
    assert meta["scene_ids"][0]["point_count"] == 1

    frame_response = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame",
        params={"platform": "Android", "shading_quality": 5},
    )
    assert frame_response.status_code == 200, frame_response.text
    frame = frame_response.json()
    assert frame["batch"]["p4_version"] == 2960783
    assert frame["map_config"]["origin"] == [-251954.0, 201148.0]
    assert frame["map_config"]["range"] == [76000.0, 72000.0]
    assert frame["map_config"]["color_ranges"]["Scene_DC"] == [150, 300, 450]
    assert frame["points"][0]["heat_map_data"]["Scene_DC"] == 258

    thumb = client.get(frame["points"][0]["thumbnail_url"])
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/webp"
    assert thumb.headers["cache-control"] == "public, max-age=31536000, immutable"
    detail = client.get(f"/api/gpm-heatmaps/points/{frame['points'][0]['id']}").json()
    assert detail["detail_data"][0]["table_data"]["data"] == [[258]]
    assert client.get(detail["image_url"]).status_code == 200


def test_gpm_accepts_pipeline_data_and_report_scope_as_canonical_contract(client, png_bytes):
    response = _canonical_upload(client, png_bytes())

    assert response.status_code == 201, response.text
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    assert frame["batch"] == {
        "id": 1,
        "batch_id": "gpm-canonical",
        "branch_tag": "main",
        "batch_url": "https://example/pipeline/gpm-canonical",
        "captured_at": "2026-08-26T15:00:00+08:00",
        "p4_version": 2960783,
        "platform": "Android",
        "shading_quality": 5,
        "shading_quality_label": "电影",
    }


def test_gpm_explicit_map_name_dynamically_matches_active_map(client, png_bytes):
    assert _upload(client, png_bytes(), map_name="VillageOverview").status_code == 201
    before = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    assert before["scene"]["map_name"] == "VillageOverview"
    assert before["map_config"] is None

    configured = client.post(
        "/api/gpm-heatmaps/maps/VillageOverview",
        **_map_form(png_bytes(size=(775, 777))),
    )
    assert configured.status_code == 201, configured.text

    after = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    assert after["map_config"]["map_name"] == "VillageOverview"
    assert after["map_config"]["revision"] == 1


def test_gpm_project_config_import_lists_maps_and_reuses_existing_image(client, png_bytes):
    assert client.post(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main",
        **_map_form(png_bytes(size=(775, 777))),
    ).status_code == 201
    payload = _project_config(
        {
            "desc": "Village_Dimension_Main", "start_pos": [-251954, 201148],
            "map_size": [76000, 72000], "pic_name": "Village_Dimension_Main", "map_id": 114,
        },
        {
            "desc": "GatheringHall_2", "start_pos": [-17475, -16512],
            "map_size": [20000, 20000], "pic_name": "GatheringHall_2", "map_id": 99,
        },
    )
    imported = _import_project_config(client, payload)
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["latest_import"]["source_filename"] == "DataForInstance.json"
    assert body["summary"] == {"total": 2, "configured": 1, "missing": 1}
    assert [item["map_id"] for item in body["maps"]] == [99, 114]
    village = next(item for item in body["maps"] if item["map_name"] == "Village_Dimension_Main")
    assert village["image"]["revision"] == 1
    assert village["upload_status"] == "uploaded"
    assert village["ratio_difference"] == pytest.approx(0.055, abs=0.001)


def test_gpm_project_map_image_uses_imported_coordinates_and_runtime_updates(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    first = _project_config()
    assert _import_project_config(client, first).status_code == 201

    uploaded = client.post(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/image",
        files={"image": ("village.png", png_bytes(size=(760, 720)), "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["upload_status"] == "uploaded"
    frame = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame",
        params={"platform": "Android", "shading_quality": 5},
    ).json()
    assert frame["map_config"]["origin"] == [-251954.0, 201148.0]
    assert frame["map_config"]["range"] == [76000.0, 72000.0]

    changed = _project_config({
        "desc": "Village moved", "start_pos": [-250000, 200000],
        "map_size": [80000, 70000], "pic_name": "Village_Dimension_Main", "map_id": 114,
    })
    assert _import_project_config(client, changed, "DataForInstance-v2.json").status_code == 201
    refreshed = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame",
        params={"platform": "Android", "shading_quality": 5},
    ).json()
    assert refreshed["map_config"]["origin"] == [-250000.0, 200000.0]
    assert refreshed["map_config"]["range"] == [80000.0, 70000.0]
    assert refreshed["map_config"]["revision"] == 1


def test_gpm_project_config_preview_and_authoritative_replace(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    assert _import_project_config(client, _project_config()).status_code == 201
    image = client.post(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/image",
        files={"image": ("village.png", png_bytes(), "image/png")},
    ).json()
    preview = client.get(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/preview"
    ).json()
    assert preview["point_count"] == 1
    assert preview["in_bounds_count"] == 1
    assert preview["source"]["batch_id"] == "gpm-1"

    replacement = _project_config({
        "desc": "GatheringHall_2", "start_pos": [-17475, -16512],
        "map_size": [20000, 20000], "pic_name": "GatheringHall_2", "map_id": 99,
    })
    assert _import_project_config(client, replacement).status_code == 201
    catalog = client.get("/api/gpm-heatmaps/project-config").json()
    assert [item["map_name"] for item in catalog["maps"]] == ["GatheringHall_2"]
    assert client.get(image["image_url"]).status_code == 200
    frame = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame",
        params={"platform": "Android", "shading_quality": 5},
    ).json()
    assert frame["map_config"] is None
    batch = client.get(
        "/api/gpm-heatmaps/uploads", params={"branch_tag": "main"},
    ).json()["items"][0]
    assert batch["map_status"] == "missing"
    assert batch["configured_map_count"] == 0


def test_gpm_project_config_rejects_duplicate_maps_atomically(client):
    valid = _project_config()
    assert _import_project_config(client, valid).status_code == 201
    duplicated = _project_config(valid["GpmConfig"][0], valid["GpmConfig"][0])
    rejected = _import_project_config(client, duplicated)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "DUPLICATE_GPM_MAP_NAME"
    catalog = client.get("/api/gpm-heatmaps/project-config").json()
    assert catalog["summary"]["total"] == 1
    assert catalog["latest_import"]["map_count"] == 1


def test_gpm_upload_catalog_filters_and_reports_map_status(client, png_bytes):
    assert _upload(client, png_bytes(), batch_id="gpm-main", map_name="ConfiguredMap").status_code == 201
    assert _upload(
        client, png_bytes(color=(2, 3, 4)), batch_id="gpm-engine",
        branch_tag="engine-ue5", map_name="MissingMap",
    ).status_code == 201
    assert client.post(
        "/api/gpm-heatmaps/maps/ConfiguredMap", **_map_form(png_bytes()),
    ).status_code == 201

    meta = client.get("/api/gpm-heatmaps/uploads/meta", params={"branch_tag": "main"}).json()
    assert meta["branch_tags"] == ["engine-ue5", "main"]
    assert meta["scene_ids"] == ["Village_Dimension_Main"]

    catalog = client.get(
        "/api/gpm-heatmaps/uploads",
        params={
            "branch_tag": "main", "platform": "Android",
            "scene_id": "Village_Dimension_Main", "shading_quality": 5,
            "captured_from": "2026-08-26", "captured_to": "2026-08-26",
        },
    )
    assert catalog.status_code == 200, catalog.text
    payload = catalog.json()
    assert payload["total"] == 1
    assert payload["items"][0] == {
        **payload["items"][0],
        "batch_id": "gpm-main",
        "scene_ids": ["Village_Dimension_Main"],
        "map_names": ["ConfiguredMap"],
        "scene_count": 1,
        "point_count": 1,
        "screenshot_count": 1,
        "map_count": 1,
        "configured_map_count": 1,
        "map_status": "configured",
    }


def test_gpm_upload_catalog_filters_by_reported_local_date(client, png_bytes):
    assert _upload(
        client,
        png_bytes(),
        batch_id="gpm-local-date",
        captured_at="2026-08-26T00:30:00+08:00",
    ).status_code == 201

    same_day = client.get(
        "/api/gpm-heatmaps/uploads",
        params={"branch_tag": "main", "captured_from": "2026-08-26", "captured_to": "2026-08-26"},
    )
    assert same_day.status_code == 200
    assert [item["batch_id"] for item in same_day.json()["items"]] == ["gpm-local-date"]

    previous_day = client.get(
        "/api/gpm-heatmaps/uploads",
        params={"branch_tag": "main", "captured_from": "2026-08-25", "captured_to": "2026-08-25"},
    )
    assert previous_day.status_code == 200
    assert previous_day.json()["items"] == []


def test_gpm_rejects_partially_embedded_scope_metadata(client, png_bytes):
    report = _report(embedded_metadata=True)
    second = json.loads(json.dumps(report["data"][0]))
    second["pic_name"] = "SecondScene"
    second["pic_id"] = 115
    second["detail"][0]["index"] = 2
    second["detail"][0]["screenshot_id"] = 2
    second.pop("platform")
    report["data"].append(second)

    response = client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "pipeline_data": json.dumps({
                "batch_id": "partial-scope",
                "captured_at": "2026-08-26T15:00:00+08:00",
                "branch_tag": "main",
            }),
        },
        files={
            "report": ("GPMHeatmap.json", json.dumps(report).encode(), "application/json"),
            "screenshots": (
                "GPMScreenshot.zip",
                _archive_entries({"1.jpg": png_bytes(), "2.jpg": png_bytes()}),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INCONSISTENT_GPM_SCOPE"


def test_gpm_rejects_conflicting_canonical_and_legacy_metadata(client, png_bytes):
    response = client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "pipeline_data": json.dumps({
                "batch_id": "canonical", "captured_at": "2026-08-26T15:00:00+08:00",
            }),
            "batch_id": "legacy",
            "platform": "Android",
            "shading_quality": "5",
        },
        files={
            "report": ("GPMHeatmap.json", json.dumps(_report()).encode(), "application/json"),
            "screenshots": ("GPMScreenshot.zip", _archive(png_bytes()), "application/zip"),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "CONFLICTING_UPLOAD_METADATA"


def test_gpm_upload_is_idempotent_only_with_explicit_overwrite(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    old_frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    old_image_url = old_frame["points"][0]["image_url"]
    duplicate = _upload(client, png_bytes(color=(1, 2, 3)))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "GPM_BATCH_EXISTS"
    replaced = _upload(client, png_bytes(color=(3, 2, 1)), overwrite=True)
    assert replaced.status_code == 201
    assert replaced.json()["updated"] is True
    new_frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    assert new_frame["points"][0]["image_url"] != old_image_url
    assert client.get(new_frame["points"][0]["image_url"]).status_code == 200
    assert client.get(old_image_url).status_code == 404


def test_gpm_batch_id_is_unique_across_branches(client, png_bytes):
    assert _upload(client, png_bytes(), batch_id="global-gpm", branch_tag="main").status_code == 201

    duplicate = _upload(
        client, png_bytes(color=(3, 2, 1)), batch_id="global-gpm", branch_tag="engine-ue5",
    )
    overwrite = _upload(
        client, png_bytes(color=(3, 2, 1)), batch_id="global-gpm",
        branch_tag="engine-ue5", overwrite=True,
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "GPM_BATCH_BRANCH_IMMUTABLE"
    assert overwrite.status_code == 409
    assert overwrite.json()["detail"]["code"] == "GPM_BATCH_BRANCH_IMMUTABLE"


def test_gpm_overwrite_rolls_back_database_and_keeps_old_assets(client, png_bytes, monkeypatch):
    import app.gpm_upload as gpm_module

    assert _upload(client, png_bytes()).status_code == 201
    old_frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    old_image_url = old_frame["points"][0]["image_url"]

    def fail_after_publish(*_args, **_kwargs):
        raise gpm_module.http_error(500, "TEST_INSERT_FAILED", "simulated failure")

    monkeypatch.setattr(gpm_module, "_insert_upload_graph", fail_after_publish)
    failed = _upload(client, png_bytes(color=(9, 8, 7)), overwrite=True)

    assert failed.status_code == 500
    restored = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    assert restored["points"][0]["image_url"] == old_image_url
    assert client.get(old_image_url).status_code == 200


def test_gpm_rejects_screenshot_set_mismatch(client, png_bytes):
    response = client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "batch_id": "bad", "captured_at": "2026-08-26T15:00:00",
            "p4_version": "2960783", "platform": "Android", "shading_quality": "5",
        },
        files={
            "report": ("GPMHeatmap.json", json.dumps(_report()).encode(), "application/json"),
            "screenshots": ("GPMScreenshot.zip", _archive(png_bytes(), screenshot_name="2.jpg"), "application/zip"),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SCREENSHOT_SET_MISMATCH"


def test_gpm_rejects_unsafe_zip_path_before_publishing_assets(client, png_bytes):
    response = client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "batch_id": "unsafe", "captured_at": "2026-08-26T15:00:00+08:00",
            "p4_version": "2960783", "platform": "Android", "shading_quality": "5",
        },
        files={
            "report": ("GPMHeatmap.json", json.dumps(_report()).encode(), "application/json"),
            "screenshots": (
                "GPMScreenshot.zip", _archive_entries({"../1.jpg": png_bytes()}), "application/zip",
            ),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNSAFE_SCREENSHOT_PATH"
    assert client.get("/api/gpm-heatmaps/meta").json()["scene_ids"] == []


def test_gpm_rejects_duplicate_stable_point_key_in_same_scene(client, png_bytes):
    report = _report(point_key="teleport-42")
    duplicate = dict(report["data"][0]["detail"][0])
    duplicate.update({"index": 2, "screenshot_id": 2})
    report["data"][0]["detail"].append(duplicate)
    response = client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "batch_id": "duplicate-key", "captured_at": "2026-08-26T15:00:00+08:00",
            "p4_version": "2960783", "platform": "Android", "shading_quality": "5",
        },
        files={
            "report": ("GPMHeatmap.json", json.dumps(report).encode(), "application/json"),
            "screenshots": (
                "GPMScreenshot.zip",
                _archive_entries({"1.jpg": png_bytes(), "2.jpg": png_bytes()}),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DUPLICATE_GPM_POINT_KEY"


def test_gpm_map_revisions_switch_atomically_and_invalid_image_keeps_active_map(client, png_bytes):
    first = client.post(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main",
        **_map_form(png_bytes(color=(1, 2, 3))),
    )
    second = client.post(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main",
        **_map_form(png_bytes(color=(4, 5, 6))),
    )
    assert first.json()["revision"] == 1
    assert second.json()["revision"] == 2

    assert _upload(client, png_bytes()).status_code == 201
    active_before = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame",
    ).json()["map_config"]
    assert active_before["revision"] == 2
    assert "/r2.png" in active_before["image_url"]

    invalid = client.post(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main",
        **_map_form(b"not-an-image"),
    )
    assert invalid.status_code == 422
    active_after = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame",
    ).json()["map_config"]
    assert active_after["id"] == active_before["id"]
    assert client.get(active_after["image_url"]).status_code == 200


def test_gpm_trend_requires_stable_point_key(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    trend = client.get(f"/api/gpm-heatmaps/points/{frame['points'][0]['id']}/trends").json()
    assert trend["available"] is False
    assert "point_key" in trend["reason"]
    assert trend["points"][0]["metrics"]["Scene_DC"] == 258


def test_gpm_delete_uses_independent_batch_identity(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    assert client.post(
        "/api/gpm-heatmaps/maps/Village_Dimension_Main", **_map_form(png_bytes()),
    ).status_code == 201
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    image_url = frame["points"][0]["image_url"]
    map_url = frame["map_config"]["image_url"]

    deleted = client.delete("/api/gpm-heatmaps/uploads/gpm-1", params={"branch_tag": "main"})

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["assets_removed"] is True
    assert client.get("/api/gpm-heatmaps/meta").json()["scene_ids"] == []
    assert client.get(image_url).status_code == 404
    assert client.get(map_url).status_code == 200
    assert client.delete("/api/gpm-heatmaps/uploads/gpm-1").status_code == 404


def test_gpm_stable_point_trend_is_anchored_to_latest_collection(client, png_bytes):
    assert _upload(
        client, png_bytes(), batch_id="old", point_key="teleport-42",
        captured_at="2020-01-01T09:00:00+08:00", p4_version="100",
    ).status_code == 201
    assert _upload(
        client, png_bytes(color=(1, 2, 3)), batch_id="new", point_key="teleport-42",
        captured_at="2020-01-05T09:00:00+08:00", p4_version="200",
    ).status_code == 201
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()

    trend = client.get(
        f"/api/gpm-heatmaps/points/{frame['points'][0]['id']}/trends",
        params={"days": 7},
    ).json()

    assert trend["available"] is True
    assert [point["batch_id"] for point in trend["points"]] == ["old", "new"]


def test_gpm_batch_and_trend_order_use_absolute_time_across_offsets(client, png_bytes):
    assert _upload(
        client, png_bytes(), batch_id="offset-old", point_key="teleport-42",
        captured_at="2026-08-26T23:00:00+08:00", p4_version="100",
    ).status_code == 201
    assert _upload(
        client, png_bytes(color=(1, 2, 3)), batch_id="offset-new", point_key="teleport-42",
        captured_at="2026-08-26T16:00:00Z", p4_version="200",
    ).status_code == 201

    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    trend = client.get(
        f"/api/gpm-heatmaps/points/{frame['points'][0]['id']}/trends",
        params={"days": 7},
    ).json()

    assert frame["batch"]["batch_id"] == "offset-new"
    assert [point["batch_id"] for point in trend["points"]] == ["offset-old", "offset-new"]
    assert [point["p4_version"] for point in trend["points"]] == [100, 200]


def test_gpm_scene_average_trend_reads_stored_summaries_and_anchors_latest(client, png_bytes):
    assert _upload(
        client, png_bytes(), batch_id="old", captured_at="2020-01-01T09:00:00+08:00",
        p4_version="100", summary_values={
            "Scene_DC": 100.5, "Scene_Tris": 200.5, "Drawcall": 300.5, "Triangle": 400.5,
        },
    ).status_code == 201
    assert _upload(
        client, png_bytes(color=(1, 2, 3)), batch_id="new",
        captured_at="2020-01-05T09:00:00+08:00", p4_version="200",
        summary_values={
            "Scene_DC": 101.5, "Scene_Tris": 201.5, "Drawcall": 301.5, "Triangle": 401.5,
        },
    ).status_code == 201

    response = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/trends",
        params={"platform": "Android", "shading_quality": 5, "days": 7},
    )

    assert response.status_code == 200, response.text
    trend = response.json()
    assert trend["available"] is True
    assert trend["days"] == 7
    assert [point["batch_id"] for point in trend["points"]] == ["old", "new"]
    assert trend["points"][0]["metrics"] == {
        "Scene_DC": 100.5,
        "Scene_Tris": 200.5,
        "Drawcall": 300.5,
        "Triangle": 400.5,
    }


def test_gpm_trends_only_accept_supported_windows(client, png_bytes):
    assert _upload(client, png_bytes(), point_key="teleport-42").status_code == 201
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    point_id = frame["points"][0]["id"]

    point_response = client.get(
        f"/api/gpm-heatmaps/points/{point_id}/trends", params={"days": 60},
    )
    scene_response = client.get(
        "/api/gpm-heatmaps/scenes/Village_Dimension_Main/trends",
        params={"platform": "Android", "shading_quality": 5, "days": 60},
    )

    assert point_response.status_code == 422
    assert scene_response.status_code == 422
    assert point_response.json()["detail"]["code"] == "INVALID_GPM_TREND_DAYS"


def _create_metric_scale(client, name, thresholds, colors=None):
    return client.post(
        "/api/gpm-heatmaps/project-config/metric-scales",
        json={
            "name": name,
            "thresholds": thresholds,
            "colors": colors or ["#52e817", "#b7f400", "#ffb20a", "#ff4a0a", "#ff1111"],
            "direction": "lower_is_better",
        },
    )


def test_gpm_scale_config_matches_scale_set_keys_and_uses_dynamic_fallback(client, png_bytes):
    assert _upload(client, png_bytes(), extra_metric=("GPU Time/ms", 17)).status_code == 201
    assert _import_project_config(client, _project_config()).status_code == 201

    catalog = client.get("/api/gpm-heatmaps/project-config/scales").json()
    assert "metrics" not in catalog

    scene_scale = _create_metric_scale(client, "通用场景DC", [100, 200, 300, 400])
    assert scene_scale.status_code == 201, scene_scale.text

    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "通用开放世界",
            "items": [
                {"metric_key": "Scene_DC", "scale_id": scene_scale.json()["id"]},
                {"metric_key": "GPU Time/ms", "scale_id": scene_scale.json()["id"]},
            ],
        },
    )
    assert scale_set.status_code == 201, scale_set.text
    bound = client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": "Android", "shading_quality": 5,
            "scale_set_id": scale_set.json()["id"],
        }]},
    )
    assert bound.status_code == 200, bound.text

    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    metrics = {item["key"]: item["scale"] for item in frame["heat_map"]}
    assert metrics["Scene_DC"]["mode"] == "configured"
    assert metrics["Scene_DC"]["source"] == {
        "type": "scale_set",
        "scale_id": scene_scale.json()["id"],
        "scale_name": "通用场景DC",
        "scale_set_id": scale_set.json()["id"],
        "scale_set_name": "通用开放世界",
    }
    assert metrics["Scene_Tris"]["mode"] == "dynamic"
    assert metrics["Scene_Tris"]["range"] == [344696.0, 344696.0]
    assert metrics["GPU Time/ms"]["mode"] == "configured"


def test_gpm_scale_set_matches_report_key_and_map_scope_exactly(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    assert _import_project_config(client, _project_config()).status_code == 201
    scale = _create_metric_scale(client, "精确匹配标尺", [100, 200, 300, 400]).json()
    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "精确匹配标尺集",
            "items": [{"metric_key": "scene_dc", "scale_id": scale["id"]}],
        },
    ).json()
    client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": "Android", "shading_quality": 5,
            "scale_set_id": scale_set["id"],
        }]},
    )

    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    scene_metric = next(item for item in frame["heat_map"] if item["key"] == "Scene_DC")
    assert scene_metric["scale"]["mode"] == "dynamic"

    updated = client.put(
        f"/api/gpm-heatmaps/project-config/metric-scale-sets/{scale_set['id']}",
        json={
            "name": "精确匹配标尺集",
            "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        },
    )
    assert updated.status_code == 200, updated.text
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    scene_metric = next(item for item in frame["heat_map"] if item["key"] == "Scene_DC")
    assert scene_metric["scale"]["mode"] == "configured"

    rebound = client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": "Android", "shading_quality": 4,
            "scale_set_id": scale_set["id"],
        }]},
    )
    assert rebound.status_code == 200, rebound.text
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    scene_metric = next(item for item in frame["heat_map"] if item["key"] == "Scene_DC")
    assert scene_metric["scale"]["mode"] == "dynamic"


def test_gpm_scale_set_rejects_duplicate_keys_and_bound_set_deletion(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    assert _import_project_config(client, _project_config()).status_code == 201
    scale = _create_metric_scale(client, "标尺集校验标尺", [100, 200, 300, 400]).json()
    duplicated = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "重复Key标尺集",
            "items": [
                {"metric_key": "Scene_DC", "scale_id": scale["id"]},
                {"metric_key": "Scene_DC", "scale_id": scale["id"]},
            ],
        },
    )
    assert duplicated.status_code == 422
    assert duplicated.json()["detail"]["code"] == "DUPLICATE_GPM_METRIC_SCALE_SET_KEY"

    empty = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={"name": "空标尺集", "items": []},
    )
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "INVALID_GPM_METRIC_SCALE_SET"

    custom_key = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "用户自定义Key标尺集",
            "items": [{"metric_key": "GPU Time/ms", "scale_id": scale["id"]}],
        },
    )
    assert custom_key.status_code == 201, custom_key.text
    assert custom_key.json()["items"][0]["metric_key"] == "GPU Time/ms"

    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "被引用标尺集",
            "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        },
    ).json()
    client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": "Android", "shading_quality": 5,
            "scale_set_id": scale_set["id"],
        }]},
    )
    rejected = client.delete(
        f"/api/gpm-heatmaps/project-config/metric-scale-sets/{scale_set['id']}"
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "GPM_METRIC_SCALE_SET_IN_USE"


def test_gpm_metric_scale_updates_are_shared_and_in_use_scales_cannot_be_deleted(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    assert _import_project_config(client, _project_config()).status_code == 201
    scale = _create_metric_scale(client, "共享SceneDC", [100, 200, 300, 400])
    scale_id = scale.json()["id"]
    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "共享标尺集",
            "items": [{
                "metric_key": "Scene_DC", "scale_id": scale_id,
            }],
        },
    ).json()
    client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": "Android", "shading_quality": 5,
            "scale_set_id": scale_set["id"],
        }]},
    )

    updated = client.put(
        f"/api/gpm-heatmaps/project-config/metric-scales/{scale_id}",
        json={
            "name": "共享SceneDC",
            "thresholds": [110, 220, 330, 440], "direction": "lower_is_better",
            "colors": ["#52e817", "#b7f400", "#ffb20a", "#ff4a0a", "#ff1111"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    scene_metric = next(item for item in frame["heat_map"] if item["key"] == "Scene_DC")
    assert scene_metric["scale"]["thresholds"] == [110.0, 220.0, 330.0, 440.0]

    rejected = client.delete(f"/api/gpm-heatmaps/project-config/metric-scales/{scale_id}")
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "GPM_METRIC_SCALE_IN_USE"


def test_gpm_scale_validation_rejects_non_increasing_thresholds(client):
    response = _create_metric_scale(client, "无效标尺", [100, 90, 300, 400])
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_GPM_SCALE_THRESHOLDS"


def test_gpm_scale_supports_custom_colors_segments_and_cross_metric_reuse(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    scale = _create_metric_scale(
        client, "三级通用标尺", [100, 300], ["#00ff00", "#ffaa00", "#ff0000"],
    )
    assert scale.status_code == 201, scale.text
    assert scale.json()["colors"] == ["#00ff00", "#ffaa00", "#ff0000"]
    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "跨指标标尺集",
            "items": [
                {"metric_key": "Scene_DC", "scale_id": scale.json()["id"]},
                {"metric_key": "Drawcall", "scale_id": scale.json()["id"]},
            ],
        },
    )
    assert scale_set.status_code == 201, scale_set.text


def test_gpm_scale_rejects_color_threshold_count_mismatch(client):
    response = _create_metric_scale(
        client, "数量不匹配", [100, 200], ["#00ff00", "#ffff00", "#ff8800", "#ff0000"],
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_GPM_SCALE_THRESHOLDS"


def test_gpm_metric_scale_accepts_interval_expressions_and_compiles_runtime_thresholds(client):
    response = client.post(
        "/api/gpm-heatmaps/project-config/metric-scales",
        json={
            "name": "表达式标尺",
            "segments": [
                {"color": "#00ff00", "expression": "<365"},
                {"color": "#00ffff", "expression": ">=365 & <390"},
                {"color": "#ff0000", "expression": ">=390"},
            ],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["segments"] == [
        {"color": "#00ff00", "expression": "<365"},
        {"color": "#00ffff", "expression": ">=365 & <390"},
        {"color": "#ff0000", "expression": ">=390"},
    ]
    assert response.json()["thresholds"] == [365.0, 390.0]
    assert response.json()["boundary_owners"] == ["upper", "upper"]
    assert response.json()["colors"] == ["#00ff00", "#00ffff", "#ff0000"]
    assert response.json()["direction"] == "lower_is_better"


def test_gpm_metric_scale_rejects_expression_gaps_before_save(client):
    response = client.post(
        "/api/gpm-heatmaps/project-config/metric-scales",
        json={
            "name": "有断档的表达式标尺",
            "segments": [
                {"color": "#00ff00", "expression": "<365"},
                {"color": "#00ffff", "expression": ">365 & <390"},
                {"color": "#ff0000", "expression": ">=390"},
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_GPM_SCALE_EXPRESSIONS"
    assert "边界 365 不属于任何颜色段" in response.json()["detail"]["message"]


def test_gpm_configured_scale_preserves_inclusive_boundary_ownership(client, png_bytes):
    assert _upload(client, png_bytes()).status_code == 201
    assert _import_project_config(client, _project_config()).status_code == 201
    scale = client.post(
        "/api/gpm-heatmaps/project-config/metric-scales",
        json={
            "name": "含边界标尺",
            "segments": [
                {"color": "#00ff00", "expression": "<=258"},
                {"color": "#ff0000", "expression": ">258"},
            ],
        },
    ).json()
    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "含边界标尺集",
            "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        },
    ).json()
    assert client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": "Android", "shading_quality": 5,
            "scale_set_id": scale_set["id"],
        }]},
    ).status_code == 200

    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    configured = next(item for item in frame["heat_map"] if item["key"] == "Scene_DC")["scale"]
    assert configured["boundary_owners"] == ["lower"]


def test_gpm_scale_updates_reject_stale_revisions(client):
    scale = _create_metric_scale(client, "并发标尺", [100, 200, 300, 400]).json()
    body = {
        "name": "并发标尺", "thresholds": [110, 220, 330, 440],
        "colors": ["#52e817", "#b7f400", "#ffb20a", "#ff4a0a", "#ff1111"],
        "expected_revision": scale["revision"],
    }
    assert client.put(
        f"/api/gpm-heatmaps/project-config/metric-scales/{scale['id']}", json=body,
    ).status_code == 200
    stale = client.put(
        f"/api/gpm-heatmaps/project-config/metric-scales/{scale['id']}", json=body,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "GPM_METRIC_SCALE_REVISION_CONFLICT"


def test_gpm_scale_set_and_map_bindings_reject_stale_revisions(client):
    assert _import_project_config(client, _project_config()).status_code == 201
    scale = _create_metric_scale(client, "并发集合标尺", [100, 200, 300, 400]).json()
    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "并发标尺集",
            "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        },
    ).json()
    set_body = {
        "name": "并发标尺集已更新",
        "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        "expected_revision": scale_set["revision"],
    }
    assert client.put(
        f"/api/gpm-heatmaps/project-config/metric-scale-sets/{scale_set['id']}",
        json=set_body,
    ).status_code == 200
    stale_set = client.put(
        f"/api/gpm-heatmaps/project-config/metric-scale-sets/{scale_set['id']}",
        json=set_body,
    )
    assert stale_set.status_code == 409
    assert stale_set.json()["detail"]["code"] == "GPM_METRIC_SCALE_SET_REVISION_CONFLICT"

    catalog = client.get("/api/gpm-heatmaps/project-config/scales").json()
    map_config = next(item for item in catalog["maps"] if item["map_name"] == "Village_Dimension_Main")
    binding_body = {
        "expected_revision": map_config["binding_revision"],
        "bindings": [{
            "platform": "Android", "shading_quality": 5,
            "scale_set_id": scale_set["id"],
        }],
    }
    assert client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json=binding_body,
    ).status_code == 200
    stale_binding = client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json=binding_body,
    )
    assert stale_binding.status_code == 409
    assert stale_binding.json()["detail"]["code"] == "GPM_MAP_BINDING_REVISION_CONFLICT"


def test_gpm_project_reimport_removes_hidden_scale_bindings(client):
    assert _import_project_config(client, _project_config()).status_code == 201
    scale = _create_metric_scale(client, "待清理标尺", [100, 200, 300, 400]).json()
    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "待清理标尺集",
            "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        },
    ).json()
    assert client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": "Android", "shading_quality": 5,
            "scale_set_id": scale_set["id"],
        }]},
    ).status_code == 200

    replacement = _project_config({
        "desc": "Other_Map", "start_pos": [0, 0], "map_size": [100, 100],
        "pic_name": "Other_Map", "map_id": 999,
    })
    assert _import_project_config(client, replacement).status_code == 201
    deleted = client.delete(
        f"/api/gpm-heatmaps/project-config/metric-scale-sets/{scale_set['id']}"
    )
    assert deleted.status_code == 200


def test_gpm_platform_validation_matches_upload_and_bindings(client, png_bytes):
    platform = "Windows Editor 中文"
    assert _upload(client, png_bytes(), platform=platform).status_code == 201
    assert _import_project_config(client, _project_config()).status_code == 201
    scale = _create_metric_scale(client, "平台标尺", [100, 200, 300, 400]).json()
    scale_set = client.post(
        "/api/gpm-heatmaps/project-config/metric-scale-sets",
        json={
            "name": "平台标尺集",
            "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        },
    ).json()
    bound = client.put(
        "/api/gpm-heatmaps/project-config/maps/Village_Dimension_Main/scale-bindings",
        json={"bindings": [{
            "platform": platform, "shading_quality": 5, "scale_set_id": scale_set["id"],
        }]},
    )
    assert bound.status_code == 200, bound.text


@pytest.mark.parametrize(("field", "value", "code"), [
    ("position", [float("nan"), 1], "INVALID_GPM_POSITION"),
    ("direction", [True, 0], "INVALID_GPM_DIRECTION"),
])
def test_gpm_upload_rejects_non_finite_coordinates(client, png_bytes, field, value, code):
    report = _report()
    report["data"][0]["detail"][0][field] = value
    response = _upload(client, png_bytes(), report_payload=report)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
