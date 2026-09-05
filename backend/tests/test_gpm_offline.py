"""热力图缩略图离线包与多包工作区测试。"""

import io
import json
import runpy
import sys
import threading
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app.gpm_offline_format import IMAGE_MODE, MEDIA_TYPE, PACKAGE_FORMAT, PACKAGE_VERSION
from app.gpm_offline_workspace import OfflineHeatmapWorkspace, OfflineWorkspaceError


def _report(value: int) -> dict:
    return {"data": [{
        "map_name": "Forest_WP",
        "platform": "IOS",
        "shading_quality": 4,
        "p4_version": 3000000 + value,
        "show_direction": 1,
        "heat_map": [{"key": "Scene_DC", "name": "场景DC", "index": 0}],
        "trend": [{"key": "Scene_DC", "summary_data": {"AvgSceneDrawCall": value}}],
        "detail": [{
            "index": 7,
            "screenshot_id": "7",
            "position": [12, 34, 0],
            "direction": [0.5, -0.5],
            "heat_map_data": {"Scene_DC": value},
            "trend_data": {"Scene_DC": value},
            "detail_data": [],
        }],
    }]}


def _screenshots(png: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("7.png", png)
    return output.getvalue()


def _upload(client, png: bytes, batch_id: str, captured_at: str, value: int, *, overwrite=False):
    response = client.post(
        "/api/gpm-heatmaps/uploads",
        data={
            "pipeline_data": json.dumps({
                "batch_id": batch_id,
                "batch_url": f"https://example.test/{batch_id}",
                "captured_at": captured_at,
                "branch_tag": "main",
            }),
            "overwrite": str(overwrite).lower(),
        },
        files={
            "report": ("GPMHeatmap.json", json.dumps(_report(value)), "application/json"),
            "screenshots": ("GPMScreenshot.zip", _screenshots(png), "application/zip"),
        },
    )
    assert response.status_code == 201, response.text


def _save_map(client, png: bytes, *, revision=1, bindings=None, origin=None):
    configuration = {
        "description": "Forest",
        "origin": origin or [0, 0],
        "range": [100, 100],
        "x_reverse": False,
        "y_reverse": True,
        "bindings": bindings or [],
        "expected_revision": revision,
    }
    response = client.put(
        "/api/gpm-heatmaps/configuration/maps/Forest_WP",
        data={"configuration": json.dumps(configuration)},
        files={"image": ("map.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text


def _export_config(client, root):
    response = client.get("/api/gpm-heatmaps/configuration/export?scope=all")
    assert response.status_code == 200, response.text
    target = root / "config" / "heatmap.zip"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(response.content)
    return target


def _export_batch(client, root, batch_id):
    response = client.get(f"/api/gpm-heatmaps/uploads/{batch_id}/offline-package")
    assert response.status_code == 200, response.text
    target = root / "data" / f"{batch_id}.ssheat"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(response.content)
    return target


def test_offline_replaced_batch_serves_new_thumbnail_without_immutable_cache(client, png_bytes, tmp_path):
    _upload(client, png_bytes(), "one", "2026-09-01T10:00:00+08:00", 100)
    _export_batch(client, tmp_path, "one")
    _export_config(client, tmp_path)
    workspace = OfflineHeatmapWorkspace(tmp_path / "data")
    script = Path(__file__).resolve().parents[2] / "scripts/gpm_offline_viewer.py"
    handler = runpy.run_path(str(script))["OfflineRequestHandler"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        server.workspace = workspace
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            image_url = workspace.frame("Forest_WP")["points"][0]["thumbnail_url"]
            url = f"http://127.0.0.1:{server.server_port}{image_url}"
            with opener.open(url, timeout=5) as response:
                assert response.headers["Cache-Control"] == "no-cache"
                original = response.read()
            _upload(client, png_bytes(color=(255, 0, 0)), "one", "2026-09-01T10:00:00+08:00", 200, overwrite=True)
            _export_batch(client, tmp_path, "one")
            workspace.reload_if_changed()
            assert workspace.frame("Forest_WP")["points"][0]["thumbnail_url"] == image_url
            with opener.open(url, timeout=5) as response:
                assert response.headers["Cache-Control"] == "no-cache"
                assert response.read() != original
        finally:
            server.shutdown()
            worker.join(timeout=5)


def test_offline_change_percentages_match_online_for_overflow_and_zero():
    from app.gpm_offline_workspace import _changes
    from app.gpm_workspace import _metric_change_percentages

    current = {"overflow": 1e308, "zero": 2, "normal": 150}
    previous = {"overflow": 1e-308, "zero": 0, "normal": 100}
    assert _changes(current, previous) == _metric_change_percentages(current, previous) == {"normal": 50}
    json.dumps(_changes(current, previous), allow_nan=False)


def test_offline_package_contains_only_thumbnails(client, png_bytes):
    png = png_bytes(size=(160, 90))
    _upload(client, png, "offline-1", "2026-08-27T10:00:00+08:00", 100)
    _save_map(client, png)

    response = client.get("/api/gpm-heatmaps/uploads/offline-1/offline-package")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(MEDIA_TYPE)
    assert response.headers["content-disposition"].endswith('.ssheat"')

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        frame = json.loads(archive.read(manifest["maps"][0]["frame_file"]))
        point_file = f"{manifest['maps'][0]['points_dir']}/{frame['points'][0]['id']}.json"
        detail = json.loads(archive.read(point_file))

    assert manifest["format"] == PACKAGE_FORMAT
    assert manifest["format_version"] == PACKAGE_VERSION
    assert manifest["image_mode"] == IMAGE_MODE
    assert manifest["maps"][0]["point_count"] == 1
    assert not any("/originals/" in name for name in names)
    thumbnails = [name for name in names if "/thumbnails/" in name]
    assert len(thumbnails) == 1
    assert frame["points"][0]["image_url"] == frame["points"][0]["thumbnail_url"]
    assert detail["image_url"] == detail["thumbnail_url"]
    assert not any(name.endswith("/map.png") for name in names)
    assert "map_config" not in frame
    assert "batch" not in frame
    assert "previous_batch" not in frame
    assert all("scale" not in metric for metric in frame["heat_map"])


def test_offline_workspace_aggregates_batches_changes_and_trends(client, png_bytes, tmp_path):
    png = png_bytes(size=(160, 90))
    _upload(client, png, "offline-old", "2026-08-27T10:00:00+08:00", 100)
    _upload(client, png, "offline-new", "2026-08-28T10:00:00+08:00", 150)
    _save_map(client, png)
    config = _export_config(client, tmp_path)
    original_config = config.read_bytes()
    _export_batch(client, tmp_path, "offline-old")
    workspace = OfflineHeatmapWorkspace(tmp_path / "data")
    assert workspace.catalog("main")["maps"][0]["batch_count"] == 1
    _export_batch(client, tmp_path, "offline-new")
    workspace.reload_if_changed()
    assert config.read_bytes() == original_config
    catalog = workspace.catalog("main")
    assert catalog["maps"][0]["value"] == "Forest_WP"
    assert catalog["maps"][0]["batch_count"] == 2

    frame = workspace.frame("Forest_WP", "main", "IOS", 4)
    assert frame["batch"]["batch_id"] == "offline-new"
    assert frame["previous_batch"]["batch_id"] == "offline-old"
    assert frame["points"][0]["metric_change_percent"]["Scene_DC"] == 50
    assert [item["batch_id"] for item in frame["available_batches"]] == [
        "offline-new", "offline-old",
    ]

    point_id = frame["points"][0]["id"]
    detail = workspace.point(point_id)
    assert detail["index"] == 7
    trends = workspace.point_trends(point_id, 7)
    assert [point["metrics"]["Scene_DC"] for point in trends["points"]] == [100, 150]
    map_trends = workspace.map_trends("Forest_WP", "main", "IOS", 4, 7)
    assert [point["metrics"]["Scene_DC"] for point in map_trends["points"]] == [100, 150]

    asset_url = frame["points"][0]["thumbnail_url"].removeprefix("/gpm-assets/offline/")
    pack_id, entry = asset_url.split("/", 1)
    asset, content_type = workspace.asset(pack_id, entry)
    assert asset
    assert content_type == "image/webp"
    map_url = frame["map_config"]["image_url"].removeprefix("/gpm-assets/offline/")
    assert workspace.asset(*map_url.split("/", 1)) == (png, "image/png")
    assert frame["heat_map"][0]["scale"]["range"] == [150, 150]


def test_shared_configuration_refresh_applies_to_all_batches(client, png_bytes, tmp_path):
    png = png_bytes()
    for batch_id, value in (("old", 100), ("new", 150)):
        _upload(client, png, batch_id, "2026-08-27T10:00:00+08:00", value)
        _export_batch(client, tmp_path, batch_id)
    _save_map(client, png)
    _export_config(client, tmp_path)
    workspace = OfflineHeatmapWorkspace(tmp_path / "data")
    before = workspace.frame("Forest_WP", "main", "IOS", 4)
    original_batches = {path: path.read_bytes() for path in (tmp_path / "data").iterdir()}
    segments = [{"color": "#00ff00", "expression": "<120"}, {"color": "#ff0000", "expression": ">=120"}]
    scale = client.post("/api/gpm-heatmaps/configuration/scales", json={"name": "DC", "segments": segments})
    assert scale.status_code == 201, scale.text
    scale_set = client.post("/api/gpm-heatmaps/configuration/scale-sets", json={
        "name": "共享标尺", "items": [{"metric_key": "Scene_DC", "scale_id": scale.json()["id"]}],
    })
    assert scale_set.status_code == 201, scale_set.text
    assert scale_set.json()["id"] == 0
    replacement_image = png_bytes(color=(20, 30, 40))
    _save_map(client, replacement_image, revision=2, origin=[10, 20], bindings=[{
        "platform": "IOS", "shading_quality": 4, "scale_set_id": scale_set.json()["id"],
    }])
    config_path = _export_config(client, tmp_path)
    workspace.reload_if_changed()
    for batch_id in ("old", "new"):
        frame = workspace.frame("Forest_WP", "main", "IOS", 4, batch_id)
        online = client.get(f"/api/gpm-heatmaps/maps/Forest_WP/frame?platform=IOS&shading_quality=4&batch_id={batch_id}").json()
        assert frame["heat_map"] == online["heat_map"]
        assert frame["map_config"]["origin"] == [10, 20]
        assert frame["map_config"]["image_url"] != before["map_config"]["image_url"]
        resource = frame["map_config"]["image_url"].removeprefix("/gpm-assets/offline/")
        assert workspace.asset(*resource.split("/", 1))[0] == replacement_image
    assert all(path.read_bytes() == content for path, content in original_batches.items())
    with zipfile.ZipFile(config_path) as archive:
        assert len(json.loads(archive.read("metric-scales.json"))["metric_scales"]) == 1
        assert len([name for name in archive.namelist() if name.startswith("images/")]) == 1


def test_workspace_requires_shared_configuration_and_rejects_old_batches(client, png_bytes, tmp_path):
    _upload(client, png_bytes(), "one", "2026-08-27T10:00:00+08:00", 100)
    batch = _export_batch(client, tmp_path, "one")
    with pytest.raises(OfflineWorkspaceError, match="缺少共享配置"):
        OfflineHeatmapWorkspace(tmp_path / "data")
    _export_config(client, tmp_path)
    # 无底图配置仍允许读取点位与趋势，和在线行为一致。
    workspace = OfflineHeatmapWorkspace(tmp_path / "data")
    assert workspace.frame("Forest_WP")["map_config"] is None
    with zipfile.ZipFile(batch) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["manifest.json"])
    manifest["format_version"] = 1
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(batch, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(OfflineWorkspaceError, match="重新导出 v2"):
        workspace.reload_if_changed()


def test_configuration_updates_reject_partial_or_missing_maps(client, png_bytes, tmp_path):
    _upload(client, png_bytes(), "one", "2026-08-27T10:00:00+08:00", 100)
    _export_batch(client, tmp_path, "one")
    path = _export_config(client, tmp_path)
    with zipfile.ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    for scope, expected in (("maps", "完整的 all"), ("all", "缺少地图")):
        manifest = json.loads(files["manifest.json"])
        manifest["scope"] = scope
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in files.items():
                if name == "manifest.json":
                    content = json.dumps(manifest).encode()
                elif scope == "all" and name in {"maps.json", "map-bindings.json"}:
                    content = json.dumps({"maps" if name == "maps.json" else "map_bindings": []}).encode()
                archive.writestr(name, content)
        with pytest.raises(OfflineWorkspaceError, match=expected):
            OfflineHeatmapWorkspace(tmp_path / "data")


def test_unknown_offline_batch_is_404(client):
    response = client.get("/api/gpm-heatmaps/uploads/missing/offline-package")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "GPM_BATCH_NOT_FOUND"


def test_export_script_separates_configuration_and_daily_batches(client, png_bytes, tmp_path, monkeypatch):
    _upload(client, png_bytes(), "one", "2026-08-27T10:00:00+08:00", 100)
    script = Path(__file__).resolve().parents[2] / "scripts" / "export_gpm_offline_package.py"
    root = tmp_path / "workspace"

    def export(*arguments):
        monkeypatch.setattr(sys, "argv", [str(script), *arguments, "--output", str(root)])
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(script), run_name="__main__")
        assert result.value.code == 0

    export("--export-config")
    config = root / "config" / "heatmap.zip"
    config_snapshot = config.stat().st_mtime_ns, config.read_bytes()
    assert not (root / "data").exists()
    export("one")
    assert (config.stat().st_mtime_ns, config.read_bytes()) == config_snapshot
    assert len(list((root / "data").glob("*.ssheat"))) == 1
    assert not list(root.rglob("*.tmp"))
    assert OfflineHeatmapWorkspace(root / "data").frame("Forest_WP")["batch"]["batch_id"] == "one"
