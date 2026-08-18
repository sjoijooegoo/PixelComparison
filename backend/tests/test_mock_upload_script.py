"""仓库参考上报脚本能处理后端生成 ID 与可选 map_build_data。"""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "mock_uploads" / "upload.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("mock_upload_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_upload_package_uses_generated_batch_id_for_artifact_and_screenshot(tmp_path, monkeypatch):
    module = _load_script()
    package = tmp_path / "package"
    (package / "Screenshot").mkdir(parents=True)
    (package / "Artifacts" / "MapBuildData").mkdir(parents=True)
    (package / "Screenshot" / "shot.png").write_bytes(b"png")
    map_data = {"worldAggregate": {}, "registries": [{"path": "registry"}]}
    (package / "Artifacts" / "MapBuildData" / "map_build_data.json").write_text(
        json.dumps(map_data), encoding="utf-8"
    )
    (package / "manifest.json").write_text(
        json.dumps({
            "capture_type": "levelsequence",
            "ue_data": {"world_name": "Scene", "platform": "WindowsEditor"},
            "screenshots": [{"name": "shot", "image": "Screenshot/shot.png"}],
            "artifacts": {
                "map_build_data": {
                    "path": "Artifacts/MapBuildData/map_build_data.json",
                    "format": "map-build-data/v2",
                }
            },
        }),
        encoding="utf-8",
    )

    json_calls = []
    screenshot_calls = []

    def fake_post_json(url, payload):
        json_calls.append((url, payload))
        if url.endswith("/api/batches"):
            return 201, {"id": "77"}
        return 201, {"registry_count": 1}

    def fake_post_screenshot(url, scene_name, image_path, **kwargs):
        screenshot_calls.append((url, scene_name, image_path))
        return 201

    monkeypatch.setattr(module, "post_json", fake_post_json)
    monkeypatch.setattr(module, "post_screenshot", fake_post_screenshot)
    module.upload_package(package)

    assert json_calls[1][0].endswith(
        "/api/batches/77/map-build-data?format=map-build-data%2Fv2&branch_tag=main"
    )
    assert json_calls[1][1] == map_data
    assert screenshot_calls[0][0].endswith(
        "/api/batches/77/screenshots?branch_tag=main"
    )


def test_map_build_rejection_does_not_block_legacy_screenshot_upload(
    tmp_path, monkeypatch, capsys
):
    module = _load_script()
    package = tmp_path / "package"
    (package / "Screenshot").mkdir(parents=True)
    (package / "Artifacts").mkdir()
    (package / "Screenshot" / "shot.png").write_bytes(b"png")
    (package / "Artifacts" / "map.json").write_text(
        json.dumps({"worldAggregate": {}, "registries": []}), encoding="utf-8"
    )
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "pipeline_data": {"id": "88"},
                "ue_data": {
                    "world_name": "Scene",
                    "platform": "WindowsEditor",
                },
                "screenshots": [
                    {"name": "shot", "image": "Screenshot/shot.png"}
                ],
                "artifacts": {
                    "map_build_data": {
                        "path": "Artifacts/map.json",
                        "format": "map-build-data/v2",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_post_json(url, _payload):
        if url.endswith("/api/batches"):
            return 201, {"id": "88"}
        return 422, "invalid map build payload"

    screenshot_calls = []
    monkeypatch.setattr(module, "post_json", fake_post_json)
    monkeypatch.setattr(
        module,
        "post_screenshot",
        lambda *args, **kwargs: screenshot_calls.append((args, kwargs)) or 201,
    )

    module.upload_package(package)

    assert len(screenshot_calls) == 1
    assert screenshot_calls[0][0][0].endswith(
        "/api/batches/88/screenshots?branch_tag=main"
    )
    output = capsys.readouterr().out
    assert "烘培数据: HTTP 422" in output
    assert "完成: 1/1 张截图" in output


def test_pure_map_build_package_reports_branch_without_requiring_screenshots(
    tmp_path, monkeypatch
):
    module = _load_script()
    package = tmp_path / "package"
    (package / "Artifacts").mkdir(parents=True)
    (package / "Artifacts" / "map.json").write_text(
        json.dumps({"worldAggregate": {}, "registries": []}), encoding="utf-8"
    )
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "pipeline_data": {"id": "engine-1", "branch_tag": "Engine-UE5"},
                "ue_data": {"world_name": "Scene", "platform": "WindowsEditor"},
                "artifacts": {
                    "map_build_data": {
                        "path": "Artifacts/map.json",
                        "format": "map-build-data/v2",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    json_calls = []
    screenshot_calls = []

    def fake_post_json(url, payload):
        json_calls.append((url, payload))
        return (201, {"id": "engine-1"}) if url.endswith("/api/batches") else (
            201,
            {"registry_count": 0},
        )

    monkeypatch.setattr(module, "post_json", fake_post_json)
    monkeypatch.setattr(
        module,
        "post_screenshot",
        lambda *args, **kwargs: screenshot_calls.append((args, kwargs)) or 201,
    )

    module.upload_package(package)

    assert json_calls[0][1]["branch_tag"] == "engine-ue5"
    assert json_calls[1][0].endswith(
        "/api/batches/engine-1/map-build-data?format=map-build-data%2Fv2&branch_tag=engine-ue5"
    )
    assert screenshot_calls == []


def test_branch_conflict_stops_mock_upload_before_artifacts(tmp_path, monkeypatch, capsys):
    module = _load_script()
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "pipeline_data": {"id": "shared", "branch_tag": "engine-ue5"},
                "ue_data": {"world_name": "Scene", "platform": "WindowsEditor"},
                "artifacts": {"map_build_data": {"path": "map.json"}},
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_post_json(url, payload):
        calls.append((url, payload))
        return 409, '{"detail":"batch shared belongs to branch main; branch_tag is immutable"}'

    monkeypatch.setattr(module, "post_json", fake_post_json)

    module.upload_package(package)

    assert len(calls) == 1
    assert "停止补传" in capsys.readouterr().out
