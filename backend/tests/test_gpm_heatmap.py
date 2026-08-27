"""GPMHeatmap 独立上传、资源和读取链路。"""

import io
import json
import zipfile

from app.gpm_common import safe_segment


def _report(*, point_key=None, embedded_metadata=False, summary_values=None):
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


def test_gpm_safe_asset_segments_do_not_collapse_distinct_identifiers():
    assert safe_segment("batch", "fallback") == "batch"
    assert safe_segment(".batch", "fallback") != "batch"
    assert safe_segment("场景", "fallback") != safe_segment("地图", "fallback")


def _upload(
    client, png_bytes, *, batch_id="gpm-1", overwrite=False, point_key=None,
    captured_at="2026-08-26T15:00:00+08:00", p4_version="2960783",
    summary_values=None, branch_tag="main",
):
    return client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "batch_id": batch_id,
            "branch_tag": branch_tag,
            "batch_url": "https://example/pipeline/gpm-1",
            "captured_at": captured_at,
            "p4_version": p4_version,
            "platform": "Android",
            "shading_quality": "5",
            "overwrite": str(overwrite).lower(),
        },
        files={
            "report": (
                "GPMHeatmap.json",
                json.dumps(_report(point_key=point_key, summary_values=summary_values)).encode(),
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
    frame = client.get("/api/gpm-heatmaps/scenes/Village_Dimension_Main/frame").json()
    image_url = frame["points"][0]["image_url"]

    deleted = client.delete("/api/gpm-heatmaps/uploads/gpm-1", params={"branch_tag": "main"})

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["assets_removed"] is True
    assert client.get("/api/gpm-heatmaps/meta").json()["scene_ids"] == []
    assert client.get(image_url).status_code == 404
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
