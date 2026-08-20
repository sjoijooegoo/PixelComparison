import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _plan(quality, tex, *names):
    return {
        "quality_run_index": tex,
        "shading_quality": quality,
        "tex_quality": tex,
        "capture_status": "complete",
        "screenshots": [
            {
                "scene_name": name,
                "source_relative_path": f"Screenshot/{tex}/{name}.png",
                "frame_index": index,
                "camera": {"index": index},
            }
            for index, name in enumerate(names)
        ],
    }


def _batch_payload(batch_id="mq1", qualities=None):
    return {
        "id": batch_id,
        "scene_id": "MultiScene",
        "branch_tag": "main",
        "p4_version": 100,
        "platform": "WindowsEditor",
        "manifest_format_version": 2,
        "source_manifest_sha256": hashlib.sha256(batch_id.encode()).hexdigest(),
        "quality_runs": qualities if qualities is not None else [
            _plan(5, 0, "shot_00", "shot_01"),
            _plan(3, 2, "shot_00", "shot_01"),
        ],
    }


def _upload(client, batch_id, quality, name, data, frame_index=0):
    return client.post(
        f"/api/batches/{batch_id}/quality-runs/{quality}/screenshots",
        params={"branch_tag": "main"},
        data={
            "scene_name": name,
            "frame_index": frame_index,
            "camera": '{"index": %d}' % frame_index,
        },
        files={"file": (f"{name}.png", data, "image/png")},
    )


def test_multi_quality_manifest_is_atomic_and_tracks_completeness(client, png_bytes):
    created = client.post("/api/batches", json=_batch_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["shading_quality"] is None
    assert body["shading_qualities"] == [5, 3]
    assert body["available_shading_qualities"] == []
    assert body["has_screenshots"] is False

    first = _upload(client, "mq1", 5, "shot_00", png_bytes(), 0)
    second = _upload(client, "mq1", 5, "shot_01", png_bytes(), 1)
    assert first.status_code == second.status_code == 201

    detail = client.get("/api/batches/mq1").json()
    assert detail["available_shading_qualities"] == [5]
    assert detail["has_screenshots"] is True
    assert detail["quality_runs"][1]["ready_screenshot_count"] == 0

    # 旧列表接口在多个声明运行中只有一个完整档位时可以无歧义推断。
    inferred = client.get("/api/batches/mq1/screenshots")
    assert inferred.status_code == 200
    assert inferred.json()["shading_quality"] == 5
    preview = client.get("/api/batches/mq1/quality-runs/5/screenshots")
    assert preview.status_code == 200
    assert preview.json()["total"] == 2
    assert client.get("/api/batches/mq1/quality-runs/3/screenshots").status_code == 409

    grid = client.get("/api/scenes/MultiScene/grid", params={"shading_quality": "all"})
    assert [column["column_id"] for column in grid.json()["batches"]] == ["mq1:5"]


def test_duplicate_quality_or_index_rejects_whole_manifest(client):
    duplicate_quality = _batch_payload("dup-q", [
        _plan(5, 0, "a"),
        {**_plan(5, 2, "b"), "quality_run_index": 1},
    ])
    response = client.post("/api/batches", json=duplicate_quality)
    assert response.status_code == 422
    assert response.json()["code"] == "DUPLICATE_SHADING_QUALITY"
    assert client.get("/api/batches/dup-q").status_code == 404

    duplicate_index = _batch_payload("dup-index", [
        _plan(5, 0, "a"),
        {**_plan(3, 2, "b"), "quality_run_index": 0},
    ])
    response = client.post("/api/batches", json=duplicate_index)
    assert response.status_code == 422
    assert response.json()["code"] == "DUPLICATE_QUALITY_RUN_INDEX"
    assert client.get("/api/batches/dup-index").status_code == 404


def test_v2_without_quality_runs_never_falls_back_to_legacy(client, png_bytes):
    payload = _batch_payload("v2-map-only", [])
    payload.pop("quality_runs")
    response = client.post("/api/batches", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["quality_runs"] == []

    # v2 省略运行用于纯烘培/诊断批次；旧截图端点不能把它变成“一张即完整”。
    legacy_upload = client.post(
        "/api/batches/v2-map-only/screenshots",
        data={"scene_name": "unexpected"},
        files={"file": ("unexpected.png", png_bytes(), "image/png")},
    )
    assert legacy_upload.status_code == 422
    assert legacy_upload.json()["code"] == "AMBIGUOUS_QUALITY_RUN"


def test_promoting_baseline_retires_same_scope_quality_not_same_run(client):
    from app.db import SessionLocal
    from app.models import Baseline, Batch, QualityRun
    from app.service import promote_baseline
    from sqlalchemy import select

    for batch_id, quality in (("base-old", 5), ("base-new", 5), ("base-q3", 3)):
        payload = _batch_payload(batch_id, [_plan(quality, quality, "shot")])
        assert client.post("/api/batches", json=payload).status_code == 201

    with SessionLocal() as db:
        def promote(batch_id):
            batch = db.get(Batch, batch_id)
            run = db.scalar(select(QualityRun).where(QualityRun.batch_id == batch_id))
            promote_baseline(db, batch, run, "release")
            db.commit()

        promote("base-old")
        promote("base-q3")
        promote("base-new")

        statuses = {
            baseline.source_batch_id: baseline.status
            for baseline in db.scalars(select(Baseline)).all()
        }
    assert statuses == {
        "base-old": "retired",
        "base-q3": "active",
        "base-new": "active",
    }


def test_new_upload_endpoint_is_hash_idempotent_and_rejects_conflict(client, png_bytes):
    assert client.post(
        "/api/batches", json=_batch_payload("idem", [_plan(5, 0, "shot")])
    ).status_code == 201
    image = png_bytes(color=(1, 2, 3))
    assert _upload(client, "idem", 5, "shot", image).status_code == 201
    retry = _upload(client, "idem", 5, "shot", image)
    assert retry.status_code == 200
    assert retry.json()["idempotent"] is True
    conflict = _upload(client, "idem", 5, "shot", png_bytes(color=(4, 5, 6)))
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "SCREENSHOT_CONTENT_CONFLICT"


def test_grid_expands_quality_runs_and_filter_matches_declared_run(client, png_bytes):
    assert client.post("/api/batches", json=_batch_payload("11")).status_code == 201
    for quality in (5, 3):
        for index, name in enumerate(("shot_00", "shot_01")):
            assert _upload(client, "11", quality, name, png_bytes(), index).status_code == 201

    all_grid = client.get(
        "/api/scenes/MultiScene/grid", params={"shading_quality": "all"}
    ).json()
    assert [item["column_id"] for item in all_grid["batches"]] == ["11:5", "11:3"]
    assert all_grid["rows"][0]["cells"][0] != all_grid["rows"][0]["cells"][1]

    q3 = client.get(
        "/api/scenes/MultiScene/grid", params={"shading_quality": 3}
    ).json()
    assert [item["column_id"] for item in q3["batches"]] == ["11:3"]
    listed = client.get("/api/batches", params={"shading_quality": 3}).json()
    assert listed["total"] == 1
    # 同一检查点在多个画质运行中重复出现，批次列表只统计一次。
    assert listed["items"][0]["scene_count"] == 2
    assert client.get("/api/batches/11").json()["scene_count"] == 2


def test_comparisons_are_isolated_by_quality(client, png_bytes):
    for batch_id, p4 in (("20", 20), ("21", 21)):
        payload = _batch_payload(batch_id)
        payload["p4_version"] = p4
        assert client.post("/api/batches", json=payload).status_code == 201
        for quality in (5, 3):
            for index, name in enumerate(("shot_00", "shot_01")):
                assert _upload(client, batch_id, quality, name, png_bytes(), index).status_code == 201

    movie = client.post("/api/comparisons", json={
        "batch_id": "21", "ref_batch_id": "20", "shading_quality": 5,
    })
    pretty = client.post("/api/comparisons", json={
        "batch_id": "21", "ref_batch_id": "20", "shading_quality": 3,
    })
    assert movie.status_code == pretty.status_code == 202
    assert movie.json()["task_id"] != pretty.json()["task_id"]
    assert client.get("/api/comparisons/lookup", params={
        "batch_id": "21", "ref_batch_id": "20",
    }).status_code == 422


def test_auto_compare_defers_multi_quality_workers_until_all_rows_exist(
    client, png_bytes, monkeypatch,
):
    """同一自动对比请求不能让首个画质任务抢在其余画质建行前写 SQLite。"""
    for batch_id, p4 in (("auto-old", 10), ("auto-new", 20)):
        payload = _batch_payload(batch_id)
        payload["p4_version"] = p4
        assert client.post("/api/batches", json=payload).status_code == 201
        for quality in (5, 3):
            for index, name in enumerate(("shot_00", "shot_01")):
                assert _upload(
                    client, batch_id, quality, name, png_bytes(), index
                ).status_code == 201

    import app.main as main

    submitted_gates = []

    def record_submission(_func, *_args):
        gate = _args[-1]
        submitted_gates.append((gate, gate.is_set()))
        return True

    monkeypatch.setattr(main.comparison_executor, "submit", record_submission)

    response = client.post("/api/batches/auto-new/auto-compare")
    assert response.status_code == 202, response.text
    assert len(submitted_gates) == 2
    assert submitted_gates[0][0] is submitted_gates[1][0]
    assert [was_set for _, was_set in submitted_gates] == [False, False]
    assert submitted_gates[0][0].is_set() is True


def test_auto_compare_reports_queue_full_per_quality_without_failing_request(
    client, png_bytes, monkeypatch,
):
    for batch_id, p4 in (("queue-old", 10), ("queue-new", 20)):
        payload = _batch_payload(batch_id)
        payload["p4_version"] = p4
        assert client.post("/api/batches", json=payload).status_code == 201
        for quality in (5, 3):
            for index, name in enumerate(("shot_00", "shot_01")):
                assert _upload(
                    client, batch_id, quality, name, png_bytes(), index
                ).status_code == 201

    import app.main as main

    submissions = 0

    def limited_submit(*_args, **_kwargs):
        nonlocal submissions
        submissions += 1
        return submissions == 1

    monkeypatch.setattr(main.comparison_executor, "submit", limited_submit)
    response = client.post("/api/batches/queue-new/auto-compare")
    assert response.status_code == 202, response.text
    results = response.json()["results"]
    assert results[0]["matched"] is True
    assert results[1] == {
        "matched": False,
        "shading_quality": 3,
        "error": "queue_full",
    }


def test_batch_scene_availability_respects_quality_and_date_filters(client):
    cases = [
        ("catalog-q5", "SceneQ5", "2026-08-01T10:00:00", [_plan(5, 0, "a", "b")]),
        ("catalog-q3", "SceneQ3", "2026-08-02T10:00:00", [_plan(3, 2, "a")]),
        ("catalog-map", "SceneMapOnly", "2026-08-03T10:00:00", []),
    ]
    for batch_id, scene_id, captured_at, runs in cases:
        payload = _batch_payload(batch_id, runs)
        payload.update({"scene_id": scene_id, "captured_at": captured_at})
        assert client.post("/api/batches", json=payload).status_code == 201

    filtered = client.get("/api/scene-availability", params={
        "capability": "batches",
        "branch_tag": "main",
        "shading_quality": 5,
        "created_from": "2026-08-01",
        "created_to": "2026-08-01",
    })
    assert filtered.status_code == 200, filtered.text
    # 批次管理按已声明画质判断；即使截图还没上传完整也属于匹配批次。
    assert filtered.json()["scene_ids"] == ["SceneQ5"]

    selected_days = client.get("/api/scene-availability", params=[
        ("capability", "batches"),
        ("branch_tag", "main"),
        ("created_dates", "2026-08-02"),
        ("created_dates", "2026-08-03"),
    ])
    assert selected_days.status_code == 200
    assert selected_days.json()["scene_ids"] == ["SceneMapOnly", "SceneQ3"]


def test_screenshot_scene_availability_requires_complete_matching_run(client, png_bytes):
    cases = [
        ("partial", "PartialScene", "main", "2026-08-01T10:00:00", 5, 1),
        ("complete", "CompleteScene", "main", "2026-08-02T10:00:00", 5, 2),
        ("other-quality", "OtherQualityScene", "main", "2026-08-02T11:00:00", 3, 2),
        ("other-branch", "OtherBranchScene", "engine-ue5", "2026-08-02T12:00:00", 5, 2),
    ]
    for batch_id, scene_id, branch, captured_at, quality, upload_count in cases:
        payload = _batch_payload(batch_id, [_plan(quality, 0, "a", "b")])
        payload.update({
            "scene_id": scene_id,
            "branch_tag": branch,
            "captured_at": captured_at,
        })
        assert client.post("/api/batches", json=payload).status_code == 201
        for index, name in enumerate(("a", "b")[:upload_count]):
            response = client.post(
                f"/api/batches/{batch_id}/quality-runs/{quality}/screenshots",
                params={"branch_tag": branch},
                data={"scene_name": name, "frame_index": index},
                files={"file": (f"{name}.png", png_bytes(), "image/png")},
            )
            assert response.status_code == 201

    filtered = client.get("/api/scene-availability", params={
        "capability": "screenshots",
        "branch_tag": "main",
        "shading_quality": 5,
        "created_from": "2026-08-01",
        "created_to": "2026-08-02",
    })
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["scene_ids"] == ["CompleteScene"]

    empty_day = client.get("/api/scene-availability", params=[
        ("capability", "screenshots"),
        ("branch_tag", "main"),
        ("shading_quality", "5"),
        ("created_dates", "2026-08-01"),
    ])
    assert empty_day.status_code == 200
    assert empty_day.json()["scene_ids"] == []


def test_existing_database_is_backed_up_before_multi_quality_migration(tmp_path):
    db_path = tmp_path / "shotdiff.db"
    connection = sqlite3.connect(db_path)
    connection.executescript("""
        CREATE TABLE batches (
            id VARCHAR PRIMARY KEY, branch_tag VARCHAR NOT NULL DEFAULT 'main',
            scene_id VARCHAR NOT NULL, p4_version INTEGER NOT NULL, platform VARCHAR NOT NULL,
            creator VARCHAR NOT NULL, created_at DATETIME NOT NULL,
            batch_url VARCHAR, resolution VARCHAR, capture_type VARCHAR,
            levelsequence_name VARCHAR, levelsequence_path VARCHAR,
            shading_quality INTEGER
        );
        CREATE TABLE screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id VARCHAR NOT NULL,
            scene_name VARCHAR NOT NULL, path VARCHAR NOT NULL,
            cache_version VARCHAR, frame_index INTEGER, camera JSON,
            CONSTRAINT uq_screenshot_batch_scene UNIQUE(batch_id, scene_name)
        );
        INSERT INTO batches VALUES (
            'old', 'main', 'OldScene', 1, 'Windows', 'CI',
            '2026-01-01 00:00:00', NULL, NULL, NULL, NULL, NULL, NULL
        );
        INSERT INTO screenshots (
            batch_id, scene_name, path, cache_version, frame_index, camera
        ) VALUES ('old', 'shot', 'batches/old/shot.png', 'v1', 0, NULL);
    """)
    connection.commit()
    connection.close()

    env = os.environ.copy()
    env.update({
        "PIXELCOMP_DATA_DIR": str(tmp_path),
        "PIXELCOMP_BACKUP_ENABLED": "0",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    })
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(db_path)
    run = connection.execute(
        "SELECT shading_quality, capture_status, expected_screenshot_count "
        "FROM quality_runs WHERE batch_id='old'"
    ).fetchone()
    shot = connection.execute(
        "SELECT quality_run_id, upload_status, path FROM screenshots WHERE id=1"
    ).fetchone()
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()
    assert run == (4, "legacy", 1)
    assert shot[0] is not None and shot[1:] == ("ready", "batches/old/shot.png")
    assert version == 2
    backups = list((tmp_path / "backup").rglob("*.pre-multi-quality-v2.*.db"))
    assert len(backups) == 1


def test_migration_preserves_baseline_comparison_and_screenshot_references(tmp_path):
    db_path = tmp_path / "shotdiff.db"
    connection = sqlite3.connect(db_path)
    connection.executescript("""
        CREATE TABLE batches (
            id VARCHAR PRIMARY KEY, branch_tag VARCHAR NOT NULL DEFAULT 'main',
            scene_id VARCHAR NOT NULL, p4_version INTEGER NOT NULL, platform VARCHAR NOT NULL,
            creator VARCHAR NOT NULL, created_at DATETIME NOT NULL,
            batch_url VARCHAR, resolution VARCHAR, capture_type VARCHAR,
            levelsequence_name VARCHAR, levelsequence_path VARCHAR,
            shading_quality INTEGER
        );
        CREATE TABLE screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id VARCHAR NOT NULL,
            scene_name VARCHAR NOT NULL, path VARCHAR NOT NULL,
            cache_version VARCHAR, frame_index INTEGER, camera JSON,
            FOREIGN KEY(batch_id) REFERENCES batches(id),
            CONSTRAINT uq_screenshot_batch_scene UNIQUE(batch_id, scene_name)
        );
        CREATE TABLE baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, version VARCHAR NOT NULL,
            branch_tag VARCHAR NOT NULL DEFAULT 'main', scene_id VARCHAR NOT NULL,
            platform VARCHAR NOT NULL, source_batch_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL, created_at DATETIME NOT NULL,
            FOREIGN KEY(source_batch_id) REFERENCES batches(id)
        );
        CREATE TABLE comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id VARCHAR NOT NULL,
            ref_batch_id VARCHAR NOT NULL, baseline_id INTEGER,
            status VARCHAR NOT NULL, diff_avg FLOAT NOT NULL, created_at DATETIME NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES batches(id),
            FOREIGN KEY(ref_batch_id) REFERENCES batches(id),
            FOREIGN KEY(baseline_id) REFERENCES baselines(id)
        );
        CREATE TABLE comparison_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, comparison_id INTEGER NOT NULL,
            scene_name VARCHAR NOT NULL, current_shot_id INTEGER,
            baseline_shot_id INTEGER, status VARCHAR NOT NULL,
            diff_pct FLOAT, metrics JSON, heatmap_path VARCHAR, cache_version VARCHAR,
            FOREIGN KEY(comparison_id) REFERENCES comparisons(id),
            FOREIGN KEY(current_shot_id) REFERENCES screenshots(id),
            FOREIGN KEY(baseline_shot_id) REFERENCES screenshots(id)
        );
        INSERT INTO batches VALUES
            ('current', 'main', 'OldScene', 2, 'Windows', 'CI',
             '2026-01-02 00:00:00', NULL, NULL, NULL, NULL, NULL, 5),
            ('reference', 'main', 'OldScene', 1, 'Windows', 'CI',
             '2026-01-01 00:00:00', NULL, NULL, NULL, NULL, NULL, 5);
        INSERT INTO screenshots (
            id, batch_id, scene_name, path, cache_version, frame_index, camera
        ) VALUES
            (10, 'current', 'shot', 'batches/current/shot.png', 'v10', 0, NULL),
            (20, 'reference', 'shot', 'batches/reference/shot.png', 'v20', 0, NULL);
        INSERT INTO baselines VALUES (
            1, 'v1', 'main', 'OldScene', 'Windows', 'reference',
            'active', '2026-01-01 00:00:00'
        );
        INSERT INTO comparisons VALUES (
            1, 'current', 'reference', 1, 'pass', 0.0, '2026-01-02 00:00:00'
        );
        INSERT INTO comparison_items VALUES (
            1, 1, 'shot', 10, 20, 'pass', 0.0, NULL, NULL, 'heat-v1'
        );
    """)
    connection.commit()
    connection.close()

    env = os.environ.copy()
    env.update({
        "PIXELCOMP_DATA_DIR": str(tmp_path),
        "PIXELCOMP_BACKUP_ENABLED": "0",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    })
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(db_path)
    run_ids = dict(connection.execute(
        "SELECT batch_id, id FROM quality_runs ORDER BY batch_id"
    ))
    assert connection.execute(
        "SELECT current_shot_id, baseline_shot_id FROM comparison_items WHERE id=1"
    ).fetchone() == (10, 20)
    assert connection.execute(
        "SELECT source_quality_run_id FROM baselines WHERE id=1"
    ).fetchone() == (run_ids["reference"],)
    assert connection.execute(
        "SELECT current_quality_run_id, reference_quality_run_id, scope_status "
        "FROM comparisons WHERE id=1"
    ).fetchone() == (run_ids["current"], run_ids["reference"], "valid")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_migration_recovers_foreign_keys_left_by_interrupted_v2_upgrade(tmp_path):
    """已由旧版迁移改写成 _batches_old 的线上库可直接续跑。"""
    db_path = tmp_path / "shotdiff.db"
    connection = sqlite3.connect(db_path)
    connection.executescript("""
        CREATE TABLE batches (
            id VARCHAR PRIMARY KEY, branch_tag VARCHAR NOT NULL DEFAULT 'main',
            scene_id VARCHAR NOT NULL, p4_version INTEGER NOT NULL,
            platform VARCHAR NOT NULL, creator VARCHAR NOT NULL,
            created_at DATETIME NOT NULL, shading_quality INTEGER
        );
        CREATE TABLE quality_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id VARCHAR NOT NULL,
            quality_run_index INTEGER NOT NULL, shading_quality INTEGER NOT NULL,
            tex_quality INTEGER, capture_status VARCHAR NOT NULL,
            expected_screenshot_count INTEGER NOT NULL, created_at DATETIME NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES batches(id),
            UNIQUE(batch_id, shading_quality), UNIQUE(batch_id, quality_run_index)
        );
        CREATE TABLE screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id VARCHAR NOT NULL,
            scene_name VARCHAR NOT NULL, path VARCHAR NOT NULL,
            cache_version VARCHAR, frame_index INTEGER, camera JSON,
            FOREIGN KEY(batch_id) REFERENCES batches(id),
            UNIQUE(batch_id, scene_name)
        );
        CREATE TABLE baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, version VARCHAR NOT NULL,
            branch_tag VARCHAR NOT NULL DEFAULT 'main', scene_id VARCHAR NOT NULL,
            platform VARCHAR NOT NULL, source_batch_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL, created_at DATETIME NOT NULL,
            FOREIGN KEY(source_batch_id) REFERENCES batches(id)
        );
        CREATE TABLE comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id VARCHAR NOT NULL,
            ref_batch_id VARCHAR NOT NULL, baseline_id INTEGER,
            status VARCHAR NOT NULL, diff_avg FLOAT NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES batches(id),
            FOREIGN KEY(ref_batch_id) REFERENCES batches(id),
            FOREIGN KEY(baseline_id) REFERENCES baselines(id)
        );
        INSERT INTO batches VALUES
            ('current', 'main', 'OldScene', 2, 'Windows', 'CI',
             '2026-01-02 00:00:00', 5),
            ('reference', 'main', 'OldScene', 1, 'Windows', 'CI',
             '2026-01-01 00:00:00', 5);
        INSERT INTO quality_runs VALUES
            (10, 'current', 0, 5, NULL, 'legacy', 1,
             '2026-01-02 00:00:00'),
            (20, 'reference', 0, 5, NULL, 'legacy', 1,
             '2026-01-01 00:00:00');
        INSERT INTO screenshots (
            id, batch_id, scene_name, path, cache_version, frame_index, camera
        ) VALUES
            (100, 'current', 'shot', 'batches/current/shot.png', 'v10', 0, NULL),
            (200, 'reference', 'shot', 'batches/reference/shot.png', 'v20', 0, NULL);
        INSERT INTO baselines VALUES (
            1, 'v1', 'main', 'OldScene', 'Windows', 'reference',
            'active', '2026-01-01 00:00:00'
        );
        INSERT INTO comparisons VALUES (
            1, 'current', 'reference', 1, 'pass', 0.0,
            '2026-01-02 00:00:00'
        );

        -- 精确模拟已发布旧代码的错误重建顺序及第一次失败后的已提交结构。
        ALTER TABLE batches RENAME TO _batches_old;
        CREATE TABLE batches (
            id VARCHAR PRIMARY KEY, branch_tag VARCHAR NOT NULL DEFAULT 'main',
            scene_id VARCHAR NOT NULL, p4_version INTEGER,
            platform VARCHAR NOT NULL, creator VARCHAR NOT NULL,
            created_at DATETIME NOT NULL, shading_quality INTEGER
        );
        INSERT INTO batches SELECT * FROM _batches_old;
        DROP TABLE _batches_old;
        PRAGMA user_version = 0;
    """)
    assert {
        row[2] for row in connection.execute("PRAGMA foreign_key_list(quality_runs)")
    } == {"_batches_old"}
    connection.commit()
    connection.close()

    env = os.environ.copy()
    env.update({
        "PIXELCOMP_DATA_DIR": str(tmp_path),
        "PIXELCOMP_BACKUP_ENABLED": "0",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    })
    command = [sys.executable, "-c", "import app.main"]
    first = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert first.returncode == 0, first.stderr
    # 修复后的库再次启动也必须幂等，不能重复重建或丢失引用。
    second = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert second.returncode == 0, second.stderr

    connection = sqlite3.connect(db_path)
    assert connection.execute("PRAGMA user_version").fetchone() == (2,)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    for table_name in ("quality_runs", "screenshots", "baselines", "comparisons"):
        targets = {
            row[2]
            for row in connection.execute(f"PRAGMA foreign_key_list({table_name})")
        }
        assert "_batches_old" not in targets
    assert connection.execute(
        "SELECT source_quality_run_id FROM baselines WHERE id=1"
    ).fetchone() == (20,)
    assert connection.execute(
        "SELECT current_quality_run_id, reference_quality_run_id "
        "FROM comparisons WHERE id=1"
    ).fetchone() == (10, 20)
    assert connection.execute("SELECT COUNT(*) FROM batches").fetchone() == (2,)
    connection.close()
