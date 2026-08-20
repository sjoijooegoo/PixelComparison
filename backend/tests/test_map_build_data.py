"""map_build_data 上报、规范化查询、趋势与批次生命周期。"""

import importlib
import json
import sqlite3
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter


def _batch(client, batch_id, created_at, quality=5, scene="MapScene", platform="Windows"):
    response = client.post(
        "/api/batches",
        json={
            "id": batch_id,
            "scene_id": scene,
            "platform": platform,
            "p4_version": int(batch_id) if batch_id.isdigit() else 1,
            "shading_quality": quality,
            "captured_at": created_at,
        },
    )
    assert response.status_code == 201, response.text


def _metrics(total, *, lightmap=None, hue=None, shadow=None, textures=1):
    # 刻意使用字符串，覆盖 UE 当前 JSON 的 64 位整数编码方式。
    lightmap = total // 2 if lightmap is None else lightmap
    hue = total // 10 if hue is None else hue
    shadow = total // 4 if shadow is None else shadow
    return {
        "residentBytes": str(total),
        "allMipsBytes": str(total + 10),
        "cookEstimateBytes": str(total - 5 if total >= 5 else total),
        "textureCount": str(textures),
        "breakdown": {
            "lightmapTextures": {
                "residentBytes": str(lightmap),
                "allMipsBytes": str(lightmap + 1),
                "cookEstimateBytes": str(lightmap),
            },
            "hueTextures": {
                "residentBytes": str(hue),
                "allMipsBytes": str(hue + 1),
                "cookEstimateBytes": str(hue),
            },
            "shadowmapTextures": {
                "residentBytes": str(shadow),
                "allMipsBytes": str(shadow + 1),
                "cookEstimateBytes": str(shadow),
            },
            "meshMapBuildDataBytes": str(total + 1),
            "precomputedLightVolumeBytes": str(total + 2),
            "precomputedReflectionVolumeBytes": str(total + 3),
            "volumetricLightmapBytes": str(total + 4),
            "lightBuildDataBytes": str(total + 5),
            "reflectionCaptureBytes": str(total + 6),
            "precomputedInstancedILCBytes": str(total + 7),
            "precomputedInstancedPRBytes": str(total + 8),
            "lightmapResourceClusterBytes": str(total + 9),
            "futureBreakdownField": "preserved",
        },
    }


def _aggregate(total, textures=1):
    return {
        "residentBytes": str(total),
        "allMipsBytes": str(total + 10),
        "cookEstimateBytes": str(total - 5 if total >= 5 else total),
        "textureCount": str(textures),
    }


def _registry(path, total, *, block=None, sub=None, subtree=None):
    return {
        "path": path,
        "parentPath": None,
        "blockIndex": block,
        "subBlockIndex": sub,
        "self": _metrics(total),
        "subtreeAggregate": _aggregate(subtree if subtree is not None else total),
    }


def _payload(scale=1):
    return {
        "worldAggregate": _aggregate(100 * scale, textures=8),
        "registries": [
            _registry("/Game/Map/Root", 10 * scale, subtree=100 * scale),
            _registry(
                "/Game/Map/Block0",
                10 * scale,
                block=0,
                subtree=100 * scale,
            ),
            _registry("/Game/Map/Block0_0x00", 30 * scale, block=0, sub=0),
            _registry("/Game/Map/Block0_0x01", 60 * scale, block=0, sub=1),
        ],
        "futureTopLevelField": {"kept": True},
    }


def _payload_with_reflection_block(scale=1):
    payload = _payload(scale)
    reflection = _registry(
        "/Game/Map/Root_BlockRefl.Root_BlockRefl",
        12 * scale,
    )
    reflection["parentPath"] = "/Game/Map/Root"
    payload["registries"].append(reflection)
    payload["worldAggregate"] = _aggregate(112 * scale, textures=8)
    return payload


def _realistic_partitioned_payload(scale=1):
    """接近当前大世界产物：主分块 + 4 个分块 + 64 个子分块 + 反射分块。"""

    root_path = "/Game/Map/Root"
    registries = [_registry(root_path, 100 * scale, subtree=10_000 * scale)]
    for block_index in range(4):
        block_path = f"/Game/Map/Block{block_index}"
        header = _registry(
            block_path,
            (block_index + 1) * 10 * scale,
            block=block_index,
            subtree=2_000 * scale,
        )
        header["parentPath"] = root_path
        registries.append(header)
        for sub_block_index in range(16):
            cell = _registry(
                f"{block_path}_0x{sub_block_index:02X}",
                (sub_block_index + 1) * scale,
                block=block_index,
                sub=sub_block_index,
            )
            cell["parentPath"] = block_path
            registries.append(cell)
    reflection = _registry("/Game/Map/Root_BlockRefl", 50 * scale)
    reflection["parentPath"] = root_path
    registries.append(reflection)
    return {
        "worldAggregate": _aggregate(10_000 * scale, textures=512),
        "registries": registries,
    }


def _upload(client, batch_id, payload, format="map-build-data/v2"):
    return client.post(
        f"/api/batches/{batch_id}/map-build-data",
        params={"format": format},
        json=payload,
    )


def test_map_build_migration_backfills_existing_trend_metrics(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-map-build.db"
    db = sqlite3.connect(db_path)
    db.executescript(
        """
        CREATE TABLE map_build_snapshots (
            batch_id VARCHAR PRIMARY KEY,
            raw_payload JSON NOT NULL
        );
        CREATE TABLE map_build_registries (
            id INTEGER PRIMARY KEY,
            batch_id VARCHAR NOT NULL,
            path VARCHAR NOT NULL
        );
        """
    )
    db.execute(
        "INSERT INTO map_build_snapshots(batch_id, raw_payload) VALUES (?, ?)",
        ("legacy", json.dumps(_payload(1))),
    )
    db.execute(
        "INSERT INTO map_build_registries(batch_id, path) VALUES (?, ?)",
        ("legacy", "/Game/Map/Block0"),
    )
    db.commit()
    db.close()

    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXELCOMP_DB_PATH", str(db_path))
    import app.db

    importlib.reload(app.db)
    app.db.migrate_columns()
    app.db.migrate_columns()  # 重复启动时迁移必须保持幂等。
    with sqlite3.connect(db_path) as migrated:
        row = migrated.execute(
            """
            SELECT lightmap_all_mips_bytes,
                   shadowmap_all_mips_bytes,
                   hue_all_mips_bytes,
                   precomputed_light_volume_bytes
            FROM map_build_registries
            WHERE batch_id = 'legacy' AND path = '/Game/Map/Block0'
            """
        ).fetchone()
    app.db.engine.dispose()

    assert row == (6, 3, 2, 12)


def test_map_build_overview_trend_and_meta(client):
    _batch(client, "101", "2026-08-01T09:00:00")
    _batch(client, "102", "2026-08-02T09:00:00")
    first = _upload(client, "101", _payload(1))
    second = _upload(client, "102", _payload(2))
    assert first.status_code == 201, first.text
    assert first.json() == {
        "batch_id": "101",
        "scene_id": "MapScene",
        "format": "map-build-data/v2",
        "registry_count": 4,
        "updated": False,
    }
    assert second.status_code == 201, second.text

    meta = client.get("/api/map-build/meta").json()
    assert meta["scene_ids"] == [
        {
            "value": "MapScene",
            "batch_count": 2,
            "latest_at": "2026-08-02T09:00",
            "platforms": ["Windows"],
            "shading_qualities": [{"value": 5, "label": "电影"}],
        }
    ]
    assert meta["platforms"] == ["Windows"]
    assert meta["shading_qualities"] == [{"value": 5, "label": "电影"}]

    overview = client.get(
        "/api/map-build/scenes/MapScene/overview",
        params={"platform": "Windows", "shading_quality": 5},
    ).json()
    assert overview["batch"]["id"] == "102"
    assert overview["world"]["label"] == "主分块"
    assert overview["world"]["path"] == "/Game/Map/Root"
    assert [item["id"] for item in overview["available_batches"]] == ["102", "101"]
    assert overview["world"]["has_children"] is True
    assert overview["world"]["self_metrics"]["total_bytes"] == 20
    assert overview["world"]["self_metrics"]["precomputed_light_volume_bytes"] == 22
    assert overview["world"]["subtree_metrics"]["total_bytes"] == 200
    assert (
        overview["world"]["subtree_metrics"]["precomputed_light_volume_bytes"]
        == 228
    )
    # 旧 metrics 字段继续指向含子级汇总，避免旧客户端突然改变口径。
    assert overview["world"]["metrics"]["total_bytes"] == 200
    assert "previous_batch" not in overview
    assert "delta" not in overview["world"]["metrics"]
    block = overview["blocks"][0]
    assert block["path"] == "/Game/Map/Block0"
    assert block["has_children"] is True
    assert block["self_metrics"]["total_bytes"] == 20
    assert block["subtree_metrics"]["total_bytes"] == 200
    assert block["subtree_metrics"]["precomputed_light_volume_bytes"] == 206
    assert block["metrics"]["total_bytes"] == 200
    assert "delta" not in block["metrics"]
    assert [(cell["label"], cell["metrics"]["total_bytes"]) for cell in block["sub_blocks"]] == [
        ("0x00", 60),
        ("0x01", 120),
    ]
    first_cell_metrics = block["sub_blocks"][0]["metrics"]
    assert block["sub_blocks"][0]["has_children"] is False
    assert block["sub_blocks"][0]["self_metrics"] == first_cell_metrics
    assert block["sub_blocks"][0]["subtree_metrics"] == first_cell_metrics
    assert first_cell_metrics["lightmap_all_mips_bytes"] == 31
    assert first_cell_metrics["hue_all_mips_bytes"] == 7
    assert first_cell_metrics["shadowmap_all_mips_bytes"] == 16
    assert {
        key: first_cell_metrics[key]
        for key in (
            "mesh_map_build_data_bytes",
            "precomputed_light_volume_bytes",
            "precomputed_reflection_volume_bytes",
            "volumetric_lightmap_bytes",
            "light_build_data_bytes",
            "reflection_capture_bytes",
            "precomputed_instanced_ilc_bytes",
            "precomputed_instanced_pr_bytes",
            "lightmap_resource_cluster_bytes",
        )
    } == {
        "mesh_map_build_data_bytes": 61,
        "precomputed_light_volume_bytes": 62,
        "precomputed_reflection_volume_bytes": 63,
        "volumetric_lightmap_bytes": 64,
        "light_build_data_bytes": 65,
        "reflection_capture_bytes": 66,
        "precomputed_instanced_ilc_bytes": 67,
        "precomputed_instanced_pr_bytes": 68,
        "lightmap_resource_cluster_bytes": 69,
    }

    world_trend = client.get(
        "/api/map-build/scenes/MapScene/trend", params={"days": 30}
    ).json()
    assert world_trend["selection"] == {
        "scope": "main_block",
        "metric_scope": "self",
        "label": "主分块 · 自身数据",
    }
    assert [point["metrics"]["total_bytes"] for point in world_trend["points"]] == [
        10,
        20,
    ]

    world_subtree_trend = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"days": 30, "metric_scope": "subtree"},
    ).json()
    assert world_subtree_trend["selection"]["label"] == "主分块 · 含子级汇总"
    assert [
        point["metrics"]["total_bytes"]
        for point in world_subtree_trend["points"]
    ] == [100, 200]

    sub_trend = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"block_index": 0, "sub_block_index": 0, "days": 30},
    ).json()
    assert sub_trend["selection"]["label"] == "分块 0 / 子分块 0x00"
    assert [point["batch"]["id"] for point in sub_trend["points"]] == ["101", "102"]
    assert [point["metrics"]["total_bytes"] for point in sub_trend["points"]] == [30, 60]
    assert sub_trend["window"] == {
        "days": 30,
        "start_date": "2026-07-04",
        "end_date": "2026-08-02",
        "truncated": False,
    }

    block_trend = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"block_index": 0},
    ).json()
    assert block_trend["selection"]["label"] == "分块 0 · 自身数据"
    assert [point["metrics"]["total_bytes"] for point in block_trend["points"]] == [10, 20]
    assert [
        {
            key: point["metrics"][key]
            for key in (
                "lightmap_all_mips_bytes",
                "shadowmap_all_mips_bytes",
                "hue_all_mips_bytes",
            )
        }
        for point in block_trend["points"]
    ] == [
        {
            "lightmap_all_mips_bytes": 6,
            "shadowmap_all_mips_bytes": 3,
            "hue_all_mips_bytes": 2,
        },
        {
            "lightmap_all_mips_bytes": 11,
            "shadowmap_all_mips_bytes": 6,
            "hue_all_mips_bytes": 3,
        },
    ]

    block_subtree_trend = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"block_index": 0, "metric_scope": "subtree"},
    ).json()
    assert block_subtree_trend["selection"]["label"] == "分块 0 · 含子级汇总"
    assert [
        point["metrics"]["total_bytes"]
        for point in block_subtree_trend["points"]
    ] == [100, 200]


def test_unindexed_reflection_block_is_selectable_in_overview_and_trend(client):
    _batch(client, "103", "2026-08-03T09:00:00")
    _batch(client, "104", "2026-08-04T09:00:00")
    assert _upload(client, "103", _payload_with_reflection_block(1)).status_code == 201
    assert _upload(client, "104", _payload_with_reflection_block(2)).status_code == 201

    overview = client.get("/api/map-build/scenes/MapScene/overview").json()
    assert len(overview["blocks"]) == 1
    assert overview["world"]["metrics"]["total_bytes"] == 224
    assert overview["world"]["has_children"] is True
    assert len(overview["auxiliary_blocks"]) == 1
    reflection = overview["auxiliary_blocks"][0]
    assert reflection["label"] == "反射分块"
    assert reflection["path"] == "/Game/Map/Root_BlockRefl.Root_BlockRefl"
    assert reflection["has_children"] is False
    assert reflection["self_metrics"]["total_bytes"] == 24
    assert reflection["subtree_metrics"]["total_bytes"] == 24

    trend = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={
            "registry_path": reflection["path"],
            "metric_scope": "self",
            "days": 30,
        },
    )
    assert trend.status_code == 200, trend.text
    body = trend.json()
    assert body["selection"] == {
        "scope": "auxiliary_block",
        "registry_path": reflection["path"],
        "metric_scope": "self",
        "label": "反射分块 · 自身数据",
    }
    assert [point["metrics"]["total_bytes"] for point in body["points"]] == [12, 24]

    invalid = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"registry_path": reflection["path"], "block_index": 0},
    )
    assert invalid.status_code == 400
    assert "registry_path" in invalid.json()["detail"]


def test_map_build_upload_is_idempotent_and_rejects_different_content(client):
    _batch(client, "201", "2026-08-01T09:00:00")
    payload = _payload(1)
    assert _upload(client, "201", payload).json()["updated"] is False
    retry = _upload(client, "201", payload)
    assert retry.status_code == 201, retry.text
    assert retry.json()["updated"] is False
    assert retry.json()["idempotent"] is True

    conflict = _upload(client, "201", _payload(3), format="map-build-data/v2.1")
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "MAP_BUILD_CONTENT_CONFLICT"

    overview = client.get("/api/map-build/scenes/MapScene/overview").json()
    assert overview["world"]["metrics"]["total_bytes"] == 100
    assert overview["world"]["self_metrics"]["total_bytes"] == 10
    assert len(overview["blocks"][0]["sub_blocks"]) == 2
    assert "previous_batch" not in overview
    assert "delta" not in overview["world"]["metrics"]


def test_invalid_replacement_is_rejected_without_damaging_previous_snapshot(client):
    _batch(client, "203", "2026-08-01T11:00:00")
    assert _upload(client, "203", _payload()).status_code == 201

    empty = _payload(2)
    empty["registries"] = []

    negative = _payload(2)
    negative["registries"][0]["self"]["residentBytes"] = -1

    overflow = _payload(2)
    overflow["worldAggregate"]["allMipsBytes"] = 9_223_372_036_854_775_808

    duplicate_cell = _payload(2)
    copied_cell = deepcopy(duplicate_cell["registries"][-1])
    copied_cell["path"] = "/Game/Map/AnotherCell"
    duplicate_cell["registries"].append(copied_cell)

    for invalid_payload in (empty, negative, overflow, duplicate_cell):
        response = _upload(client, "203", invalid_payload)
        assert response.status_code == 422, response.text

        overview = client.get("/api/map-build/scenes/MapScene/overview")
        assert overview.status_code == 200, overview.text
        assert overview.json()["world"]["metrics"]["total_bytes"] == 100
        assert len(overview.json()["blocks"][0]["sub_blocks"]) == 2


def test_registry_count_limit_rejects_oversized_payload_without_partial_snapshot(client):
    _batch(client, "204", "2026-08-01T12:00:00")
    payload = _payload()
    template = payload["registries"][0]
    payload["registries"] = []
    for index in range(5001):
        item = deepcopy(template)
        item["path"] = f"/Game/Map/Oversized/{index}"
        payload["registries"].append(item)

    response = _upload(client, "204", payload)

    assert response.status_code == 422, response.text
    assert "不能超过 5000 条" in response.text
    assert client.get("/api/map-build/meta").json()["scene_ids"] == []


def test_explicit_batch_selection_cannot_escape_requested_scene(client):
    _batch(client, "205", "2026-08-01T13:00:00", scene="SceneA")
    _batch(client, "206", "2026-08-01T14:00:00", scene="SceneB")
    assert _upload(client, "205", _payload()).status_code == 201
    assert _upload(client, "206", _payload(2)).status_code == 201

    response = client.get(
        "/api/map-build/scenes/SceneA/overview",
        params={"batch_id": "206"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "当前筛选没有烘培数据"


def test_unknown_scene_trend_returns_an_empty_stable_window(client):
    response = client.get(
        "/api/map-build/scenes/UnknownScene/trend",
        params={"days": 30, "metric_scope": "subtree"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "selection": {
            "scope": "main_block",
            "metric_scope": "subtree",
            "label": "主分块 · 含子级汇总",
        },
        "points": [],
        "window": {
            "days": 30,
            "start_date": None,
            "end_date": None,
            "truncated": False,
        },
    }


def test_map_build_accepts_legacy_breakdown_without_optional_resource_fields(client):
    _batch(client, "202", "2026-08-01T10:00:00")
    payload = _payload()
    optional_fields = {
        "meshMapBuildDataBytes",
        "precomputedLightVolumeBytes",
        "precomputedReflectionVolumeBytes",
        "volumetricLightmapBytes",
        "lightBuildDataBytes",
        "reflectionCaptureBytes",
        "precomputedInstancedILCBytes",
        "precomputedInstancedPRBytes",
        "lightmapResourceClusterBytes",
    }
    for registry in payload["registries"]:
        breakdown = registry["self"]["breakdown"]
        for field in optional_fields:
            breakdown.pop(field)

    assert _upload(client, "202", payload).status_code == 201
    metrics = client.get("/api/map-build/scenes/MapScene/overview").json()[
        "world"
    ]["metrics"]
    assert all(
        metrics[field] == 0
        for field in (
            "mesh_map_build_data_bytes",
            "precomputed_light_volume_bytes",
            "precomputed_reflection_volume_bytes",
            "volumetric_lightmap_bytes",
            "light_build_data_bytes",
            "reflection_capture_bytes",
            "precomputed_instanced_ilc_bytes",
            "precomputed_instanced_pr_bytes",
            "lightmap_resource_cluster_bytes",
        )
    )


def test_map_build_validation_and_missing_batch(client):
    missing = _upload(client, "missing", _payload())
    assert missing.status_code == 404

    _batch(client, "301", "2026-08-01T09:00:00")
    duplicate = _payload()
    duplicate["registries"].append(dict(duplicate["registries"][-1]))
    response = _upload(client, "301", duplicate)
    assert response.status_code == 422
    assert "registry path 重复" in response.text

    bad_topology = _payload()
    bad_topology["registries"][2]["blockIndex"] = None
    response = _upload(client, "301", bad_topology)
    assert response.status_code == 422
    assert "subBlockIndex" in response.text

    response = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"sub_block_index": 1},
    )
    assert response.status_code == 400
    assert client.get(
        "/api/map-build/scenes/MapScene/trend", params={"days": 0}
    ).status_code == 422
    assert client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"metric_scope": "children_only"},
    ).status_code == 422


def test_map_build_respects_filters_and_missing_cells_are_trend_gaps(client):
    _batch(client, "401", "2026-08-01T09:00:00", quality=4)
    _batch(client, "402", "2026-08-02T09:00:00", quality=5)
    assert _upload(client, "401", _payload(1)).status_code == 201
    payload = _payload(2)
    payload["registries"] = [
        row for row in payload["registries"] if row["subBlockIndex"] != 1
    ]
    assert _upload(client, "402", payload).status_code == 201

    quality_four = client.get(
        "/api/map-build/scenes/MapScene/overview",
        params={"shading_quality": 4},
    ).json()
    assert quality_four["batch"]["id"] == "401"

    # 页面不传平台或画质时，应按场景把不同产出条件的批次串成一条历史。
    scene_overview = client.get("/api/map-build/scenes/MapScene/overview").json()
    assert scene_overview["batch"]["id"] == "402"
    assert "previous_batch" not in scene_overview

    trend = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"block_index": 0, "sub_block_index": 1},
    ).json()
    assert trend["points"][0]["metrics"]["total_bytes"] == 60
    assert trend["points"][1]["metrics"] is None


def test_trend_uses_calendar_days_and_keeps_multiple_batches_on_same_day(client):
    samples = [
        ("801", "2026-07-31T18:00:00"),
        ("802", "2026-08-01T09:00:00"),
        ("803", "2026-08-01T17:00:00"),
        ("804", "2026-08-03T10:00:00"),
    ]
    for batch_id, created_at in samples:
        _batch(client, batch_id, created_at)
        assert _upload(client, batch_id, _payload(int(batch_id) - 800)).status_code == 201

    trend = client.get(
        "/api/map-build/scenes/MapScene/trend", params={"days": 3}
    ).json()
    assert [point["batch"]["id"] for point in trend["points"]] == ["802", "803", "804"]
    assert trend["window"] == {
        "days": 3,
        "start_date": "2026-08-01",
        "end_date": "2026-08-03",
        "truncated": False,
    }

    one_day = client.get(
        "/api/map-build/scenes/MapScene/trend", params={"days": 1}
    ).json()
    assert [point["batch"]["id"] for point in one_day["points"]] == ["804"]


def test_trend_supports_an_inclusive_custom_date_range_up_to_90_days(client):
    samples = [
        ("811", "2026-05-31T18:00:00"),
        ("812", "2026-06-01T09:00:00"),
        ("813", "2026-06-01T17:00:00"),
        ("814", "2026-06-30T10:00:00"),
        ("815", "2026-07-01T09:00:00"),
    ]
    for batch_id, created_at in samples:
        _batch(client, batch_id, created_at)
        assert _upload(client, batch_id, _payload(int(batch_id) - 810)).status_code == 201

    response = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"start_date": "2026-06-01", "end_date": "2026-06-30"},
    )

    assert response.status_code == 200
    trend = response.json()
    assert [point["batch"]["id"] for point in trend["points"]] == ["812", "813", "814"]
    assert trend["window"] == {
        "days": 30,
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "truncated": False,
    }

    assert client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"start_date": "2026-06-01"},
    ).status_code == 400
    assert client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"start_date": "2026-06-02", "end_date": "2026-06-01"},
    ).status_code == 400
    assert client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"start_date": "2026-01-01", "end_date": "2026-04-01"},
    ).status_code == 400


def test_map_build_snapshot_follows_batch_delete_and_overwrite(client):
    _batch(client, "501", "2026-08-01T09:00:00")
    assert _upload(client, "501", _payload()).status_code == 201
    assert client.delete("/api/batches/501").status_code == 200
    assert client.get("/api/map-build/meta").json()["scene_ids"] == []

    _batch(client, "502", "2026-08-01T09:00:00")
    assert _upload(client, "502", _payload()).status_code == 201
    overwrite = client.post(
        "/api/batches",
        json={
            "id": "502",
            "scene_id": "MapScene",
            "platform": "Windows",
            "overwrite": True,
        },
    )
    assert overwrite.status_code == 201, overwrite.text
    assert client.get("/api/map-build/meta").json()["scene_ids"] == []


def test_map_build_snapshot_coexists_with_existing_screenshot_flow(client, png_bytes):
    _batch(client, "503", "2026-08-01T10:00:00")
    assert _upload(client, "503", _payload()).status_code == 201

    uploaded = client.post(
        "/api/batches/503/screenshots",
        data={"scene_name": "Seq_MapScene_0000", "frame_index": "0"},
        files={
            "file": (
                "Seq_MapScene_0000.png",
                png_bytes((20, 40, 60)),
                "image/png",
            )
        },
    )

    assert uploaded.status_code == 201, uploaded.text
    screenshots = client.get("/api/batches/503/screenshots")
    assert screenshots.status_code == 200, screenshots.text
    assert screenshots.json()["total"] == 1
    assert screenshots.json()["items"][0]["scene_name"] == "Seq_MapScene_0000"
    assert client.get("/api/map-build/scenes/MapScene/overview").status_code == 200


def test_map_build_meta_follows_authoritative_scene_catalog(client):
    _batch(client, "601", "2026-08-01T09:00:00", scene="Unlisted")
    _batch(client, "602", "2026-08-01T10:00:00", scene="Listed")
    assert _upload(client, "601", _payload()).status_code == 201
    assert _upload(client, "602", _payload()).status_code == 201

    assert client.put(
        "/api/scene-catalog", json={"scene_id_order": ["Listed"]}
    ).status_code == 200
    assert [item["value"] for item in client.get("/api/map-build/meta").json()["scene_ids"]] == [
        "Listed"
    ]

    assert client.put(
        "/api/settings", json={"show_unlisted_scene_ids": True}
    ).status_code == 200
    assert [item["value"] for item in client.get("/api/map-build/meta").json()["scene_ids"]] == [
        "Listed",
        "Unlisted",
    ]


def test_concurrent_map_build_retries_leave_one_complete_snapshot(client):
    _batch(client, "701", "2026-08-01T09:00:00")

    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(
            executor.map(lambda _: _upload(client, "701", _payload(1)), range(1, 7))
        )

    assert all(response.status_code == 201 for response in responses)
    overview = client.get("/api/map-build/scenes/MapScene/overview").json()
    assert overview["world"]["metrics"]["total_bytes"] == 100
    assert len(overview["blocks"]) == 1
    assert len(overview["blocks"][0]["sub_blocks"]) == 2


def test_thirty_day_realistic_dataset_keeps_overview_and_trend_responsive(client):
    payload = _realistic_partitioned_payload()
    assert len(payload["registries"]) == 70
    for day in range(1, 31):
        batch_id = str(9000 + day)
        _batch(client, batch_id, f"2026-06-{day:02d}T09:00:00")
        response = _upload(client, batch_id, payload)
        assert response.status_code == 201, response.text

    started = perf_counter()
    trend = client.get(
        "/api/map-build/scenes/MapScene/trend",
        params={"days": 30, "block_index": 3, "metric_scope": "subtree"},
    )
    trend_seconds = perf_counter() - started

    started = perf_counter()
    overview = client.get("/api/map-build/scenes/MapScene/overview")
    overview_seconds = perf_counter() - started

    assert trend.status_code == 200, trend.text
    assert len(trend.json()["points"]) == 30
    assert all(point["metrics"] is not None for point in trend.json()["points"])
    assert overview.status_code == 200, overview.text
    assert len(overview.json()["blocks"]) == 4
    assert all(len(block["sub_blocks"]) == 16 for block in overview.json()["blocks"])
    assert len(overview.json()["auxiliary_blocks"]) == 1
    assert trend_seconds < 2.0, f"30 天趋势查询耗时 {trend_seconds:.3f}s"
    assert overview_seconds < 1.0, f"70 Registry 概览查询耗时 {overview_seconds:.3f}s"
