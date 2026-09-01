"""批次分支隔离与数据能力的公开接口行为。"""

import importlib
import sqlite3


def _map_build_payload(total=100):
    aggregate = {
        "residentBytes": total,
        "allMipsBytes": total,
        "cookEstimateBytes": total,
        "textureCount": 1,
    }
    return {
        "worldAggregate": aggregate,
        "registries": [
            {
                "path": "/Game/Maps/BranchScene_BuiltData",
                "self": {
                    **aggregate,
                    "breakdown": {
                        "lightmapTextures": aggregate | {"textureCount": 1},
                        "hueTextures": aggregate | {"textureCount": 1},
                        "shadowmapTextures": aggregate | {"textureCount": 1},
                    },
                },
                "subtreeAggregate": aggregate,
            }
        ],
    }


def _create_batch(
    client,
    batch_id,
    *,
    branch_tag=None,
    scene_id="BranchScene",
    captured_at=None,
):
    body = {
        "id": batch_id,
        "scene_id": scene_id,
        "platform": "Windows",
        "p4_version": 100,
    }
    if branch_tag is not None:
        body["branch_tag"] = branch_tag
    if captured_at is not None:
        body["captured_at"] = captured_at
    response = client.post("/api/batches", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_batch_branch_defaults_normalizes_and_filters(client):
    legacy = _create_batch(client, "main-batch")
    engine = _create_batch(client, "engine-batch", branch_tag="  Engine-UE5  ")

    assert legacy["branch_tag"] == "main"
    assert engine["branch_tag"] == "engine-ue5"
    assert legacy["has_screenshots"] is False
    assert legacy["has_map_build_data"] is False

    meta = client.get("/api/meta").json()
    assert meta["branch_tags"] == ["main", "engine-ue5"]

    default_items = client.get("/api/batches").json()["items"]
    engine_items = client.get(
        "/api/batches", params={"branch_tag": "engine-ue5"}
    ).json()["items"]
    assert [item["id"] for item in default_items] == ["main-batch"]
    assert [item["id"] for item in engine_items] == ["engine-batch"]


def test_exact_batch_returns_capabilities_without_branch_filter(client, png_bytes):
    _create_batch(
        client,
        "engine-exact",
        branch_tag="engine-ue5",
        scene_id="ExactScene",
        captured_at="2026-08-03T12:34:00",
    )
    screenshot = client.post(
        "/api/batches/engine-exact/screenshots",
        params={"branch_tag": "engine-ue5"},
        data={"scene_name": "shot_01"},
        files={"file": ("shot_01.png", png_bytes(), "image/png")},
    )
    assert screenshot.status_code == 201, screenshot.text

    response = client.get("/api/batches/engine-exact")

    assert response.status_code == 200, response.text
    body = response.json()
    assert {key: body[key] for key in (
        "id", "branch_tag", "scene_id", "p4_version", "platform", "creator",
        "batch_url", "resolution", "shading_quality", "shading_quality_label",
        "created_at", "scene_count", "has_screenshots", "has_map_build_data",
    )} == {
        "id": "engine-exact",
        "branch_tag": "engine-ue5",
        "scene_id": "ExactScene",
        "p4_version": 100,
        "platform": "Windows",
        "creator": "CI机器人",
        "batch_url": None,
        "resolution": None,
        "shading_quality": 4,
        "shading_quality_label": "极致",
        "created_at": "2026-08-03 12:34",
        "scene_count": 1,
        "has_screenshots": True,
        "has_map_build_data": False,
    }
    assert body["shading_qualities"] == [4]
    assert body["available_shading_qualities"] == [4]
    assert body["quality_runs"][0]["capture_status"] == "legacy"
    assert client.get("/api/batches/missing-batch").status_code == 404


def test_batch_branch_rejects_non_string_value_as_validation_error(client):
    response = client.post(
        "/api/batches",
        json={
            "id": "bad-branch",
            "branch_tag": 123,
            "scene_id": "BranchScene",
            "platform": "Windows",
        },
    )

    assert response.status_code == 422
    assert "branch_tag" in response.text


def test_capability_flags_and_grid_only_include_screenshot_batches(client, png_bytes):
    _create_batch(
        client, "engine-shot", branch_tag="engine-ue5", scene_id="ShotScene"
    )
    _create_batch(
        client, "engine-build", branch_tag="engine-ue5", scene_id="BuildScene"
    )
    _create_batch(
        client, "engine-empty", branch_tag="engine-ue5", scene_id="EmptyScene"
    )

    screenshot = client.post(
        "/api/batches/engine-shot/screenshots",
        params={"branch_tag": "engine-ue5"},
        data={"scene_name": "shot_01"},
        files={"file": ("shot_01.png", png_bytes(), "image/png")},
    )
    build = client.post(
        "/api/batches/engine-build/map-build-data",
        params={"branch_tag": "engine-ue5"},
        json=_map_build_payload(),
    )
    assert screenshot.status_code == 201, screenshot.text
    assert build.status_code == 201, build.text

    items = {
        item["id"]: item
        for item in client.get(
            "/api/batches", params={"branch_tag": "engine-ue5"}
        ).json()["items"]
    }
    assert items["engine-shot"]["has_screenshots"] is True
    assert items["engine-shot"]["has_map_build_data"] is False
    assert items["engine-build"]["has_screenshots"] is False
    assert items["engine-build"]["has_map_build_data"] is True
    assert items["engine-empty"]["has_screenshots"] is False
    assert items["engine-empty"]["has_map_build_data"] is False

    flags = client.get("/api/meta").json()["scene_data_flags"]["engine-ue5"]
    assert flags["ShotScene"] == {
        "has_screenshots": True,
        "has_map_build_data": False,
        "screenshot_qualities": [4],
    }
    assert flags["BuildScene"] == {
        "has_screenshots": False,
        "has_map_build_data": True,
        "screenshot_qualities": [],
    }
    assert flags["EmptyScene"] == {
        "has_screenshots": False,
        "has_map_build_data": False,
        "screenshot_qualities": [],
    }

    grid = client.get(
        "/api/scenes/ShotScene/grid", params={"branch_tag": "engine-ue5"}
    ).json()
    assert grid["total"] == 1
    assert [batch["id"] for batch in grid["batches"]] == ["engine-shot"]


def test_batch_branch_is_immutable_and_artifact_upload_rejects_mismatch(client, png_bytes):
    _create_batch(client, "immutable")

    screenshot = client.post(
        "/api/batches/immutable/screenshots",
        params={"branch_tag": "engine-ue5"},
        data={"scene_name": "shot_01"},
        files={"file": ("shot_01.png", png_bytes(), "image/png")},
    )
    build = client.post(
        "/api/batches/immutable/map-build-data",
        params={"branch_tag": "engine-ue5"},
        json=_map_build_payload(),
    )
    overwrite = client.post(
        "/api/batches",
        json={
            "id": "immutable",
            "scene_id": "BranchScene",
            "branch_tag": "engine-ue5",
            "platform": "Windows",
            "overwrite": True,
        },
    )

    assert screenshot.status_code == 409
    assert build.status_code == 409
    assert overwrite.status_code == 409
    listed = client.get("/api/batches").json()["items"]
    assert listed[0]["branch_tag"] == "main"
    assert listed[0]["has_screenshots"] is False
    assert listed[0]["has_map_build_data"] is False


def test_map_build_meta_overview_and_trend_are_isolated_by_branch(client):
    _create_batch(
        client,
        "main-build",
        captured_at="2026-08-01T09:00:00",
    )
    _create_batch(
        client,
        "engine-build",
        branch_tag="engine-ue5",
        captured_at="2026-08-02T09:00:00",
    )
    assert client.post(
        "/api/batches/main-build/map-build-data",
        json=_map_build_payload(100),
    ).status_code == 201
    assert client.post(
        "/api/batches/engine-build/map-build-data",
        params={"branch_tag": "engine-ue5"},
        json=_map_build_payload(200),
    ).status_code == 201

    default_meta = client.get("/api/map-build/meta").json()
    engine_meta = client.get(
        "/api/map-build/meta", params={"branch_tag": "engine-ue5"}
    ).json()
    assert default_meta["scene_ids"][0]["batch_count"] == 1
    assert engine_meta["scene_ids"][0]["batch_count"] == 1

    default_overview = client.get(
        "/api/map-build/scenes/BranchScene/overview"
    ).json()
    engine_overview = client.get(
        "/api/map-build/scenes/BranchScene/overview",
        params={"branch_tag": "engine-ue5"},
    ).json()
    assert default_overview["batch"]["id"] == "main-build"
    assert default_overview["batch"]["branch_tag"] == "main"
    assert engine_overview["batch"]["id"] == "engine-build"
    assert engine_overview["batch"]["branch_tag"] == "engine-ue5"

    default_trend = client.get(
        "/api/map-build/scenes/BranchScene/trend", params={"days": 30}
    ).json()
    engine_trend = client.get(
        "/api/map-build/scenes/BranchScene/trend",
        params={"days": 30, "branch_tag": "engine-ue5"},
    ).json()
    assert [point["batch"]["id"] for point in default_trend["points"]] == [
        "main-build"
    ]
    assert [point["batch"]["id"] for point in engine_trend["points"]] == [
        "engine-build"
    ]


def test_comparison_rejects_cross_branch_and_batches_without_screenshots(
    client, png_bytes
):
    _create_batch(client, "main-shot")
    _create_batch(client, "engine-shot", branch_tag="engine-ue5")
    _create_batch(client, "engine-build", branch_tag="engine-ue5")
    for batch_id, branch_tag in (
        ("main-shot", "main"),
        ("engine-shot", "engine-ue5"),
    ):
        response = client.post(
            f"/api/batches/{batch_id}/screenshots",
            params={"branch_tag": branch_tag},
            data={"scene_name": "shot_01"},
            files={"file": ("shot_01.png", png_bytes(), "image/png")},
        )
        assert response.status_code == 201, response.text

    cross_branch = client.post(
        "/api/comparisons",
        json={"batch_id": "main-shot", "ref_batch_id": "engine-shot"},
    )
    missing_screenshot = client.post(
        "/api/comparisons",
        json={"batch_id": "engine-build", "ref_batch_id": "engine-shot"},
    )
    auto_compare = client.post("/api/batches/engine-build/auto-compare")

    assert cross_branch.status_code == 400
    assert "分支" in cross_branch.json()["detail"]
    assert missing_screenshot.status_code == 400
    assert "截图" in missing_screenshot.json()["detail"]
    assert auto_compare.status_code == 400
    assert "截图" in auto_compare.json()["detail"]


def test_comparison_and_baseline_lists_are_isolated_by_branch(client):
    _create_batch(client, "main-current")
    _create_batch(client, "main-ref")
    _create_batch(client, "engine-current", branch_tag="engine-ue5")
    _create_batch(client, "engine-ref", branch_tag="engine-ue5")

    from app.db import SessionLocal
    from app.models import Baseline, Comparison

    with SessionLocal() as db:
        db.add_all(
            [
                Comparison(batch_id="main-current", ref_batch_id="main-ref"),
                Comparison(batch_id="engine-current", ref_batch_id="engine-ref"),
                Baseline(
                    version="main-v1",
                    branch_tag="main",
                    scene_id="BranchScene",
                    platform="Windows",
                    source_batch_id="main-ref",
                ),
                Baseline(
                    version="engine-v1",
                    branch_tag="engine-ue5",
                    scene_id="BranchScene",
                    platform="Windows",
                    source_batch_id="engine-ref",
                ),
            ]
        )
        db.commit()

    main_comparisons = client.get("/api/comparisons").json()
    engine_comparisons = client.get(
        "/api/comparisons", params={"branch_tag": "engine-ue5"}
    ).json()
    main_baselines = client.get("/api/baselines").json()
    engine_baselines = client.get(
        "/api/baselines", params={"branch_tag": "engine-ue5"}
    ).json()

    assert main_comparisons["total"] == 1
    assert main_comparisons["items"][0]["branch_tag"] == "main"
    assert engine_comparisons["total"] == 1
    assert engine_comparisons["items"][0]["branch_tag"] == "engine-ue5"
    assert [item["version"] for item in main_baselines["items"]] == ["main-v1"]
    assert [item["version"] for item in engine_baselines["items"]] == ["engine-v1"]


def test_legacy_database_migration_backfills_main_branch(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-branch.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE batches (
                id VARCHAR PRIMARY KEY,
                scene_id VARCHAR NOT NULL,
                p4_version INTEGER,
                platform VARCHAR NOT NULL,
                creator VARCHAR,
                created_at DATETIME
            );
            CREATE TABLE baselines (
                id INTEGER PRIMARY KEY,
                version VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                platform VARCHAR NOT NULL,
                source_batch_id VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                created_at DATETIME
            );
            INSERT INTO batches VALUES (
                'legacy', 'LegacyScene', 100, 'Windows', NULL, '2026-08-01 09:00:00'
            );
            INSERT INTO baselines VALUES (
                1, 'v1', 'LegacyScene', 'Windows', 'legacy', 'active',
                '2026-08-01 09:00:00'
            );
            """
        )

    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXELCOMP_DB_PATH", str(db_path))
    import app.db

    importlib.reload(app.db)
    app.db.migrate_columns()
    app.db.migrate_columns()
    with sqlite3.connect(db_path) as migrated:
        batch_branch = migrated.execute(
            "SELECT branch_tag FROM batches WHERE id = 'legacy'"
        ).fetchone()[0]
        baseline_branch = migrated.execute(
            "SELECT branch_tag FROM baselines WHERE id = 1"
        ).fetchone()[0]
    app.db.engine.dispose()

    assert batch_branch == "main"
    assert baseline_branch == "main"


def test_batch_capability_flags_use_constant_query_count_per_page(client):
    for index in range(12):
        _create_batch(client, f"batch-{index}")

    from sqlalchemy import event
    from app.db import engine

    selects = []

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        response = client.get("/api/batches", params={"page_size": 12})
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 12
    assert len(selects) <= 4
