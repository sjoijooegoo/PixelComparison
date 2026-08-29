"""GPMHeatmap 配置包导出、检查和原子应用。"""

import io
import json
import zipfile

from PIL import Image


SEGMENTS = [
    {"color": "#52e817", "expression": "<100"},
    {"color": "#b7f400", "expression": ">=100 & <200"},
    {"color": "#ffb20a", "expression": ">=200 & <300"},
    {"color": "#ff4a0a", "expression": ">=300 & <400"},
    {"color": "#ff1111", "expression": ">=400"},
]


def _seed_configuration(client, png):
    scale = client.post(
        "/api/gpm-heatmaps/configuration/scales",
        json={"name": "场景 DC", "segments": SEGMENTS},
    ).json()
    scale_set = client.post(
        "/api/gpm-heatmaps/configuration/scale-sets",
        json={
            "name": "默认标尺集",
            "items": [{"metric_key": "Scene_DC", "scale_id": scale["id"]}],
        },
    ).json()
    configuration = {
        "description": "村庄",
        "origin": [-100, -200],
        "range": [300, 400],
        "x_reverse": False,
        "y_reverse": True,
        "bindings": [{
            "platform": "IOS", "shading_quality": 5,
            "scale_set_id": scale_set["id"],
        }],
    }
    response = client.put(
        "/api/gpm-heatmaps/configuration/maps/Village_Dimension_Main",
        data={"configuration": json.dumps(configuration)},
        files={"image": ("map.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text


def _files_from_zip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _rebuilt_package(files):
    manifest = json.loads(files["manifest.json"])
    files["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def _inspect(client, package):
    return client.post(
        "/api/gpm-heatmaps/configuration/imports/inspect",
        files={"package": ("gpm-config.zip", package, "application/zip")},
    )


def test_export_is_readable_and_round_trips_without_changes(client, png_bytes):
    _seed_configuration(client, png_bytes(size=(80, 60)))

    exported = client.get("/api/gpm-heatmaps/configuration/export")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == "application/zip"
    files = _files_from_zip(exported.content)
    assert set(files) >= {
        "manifest.json", "maps.json", "metric-scales.json", "scale-sets.json",
        "map-bindings.json",
    }
    assert "README.md" not in files
    assert len([name for name in files if name.startswith("images/")]) == 1
    manifest = json.loads(files["manifest.json"])
    assert manifest["format"] == "pixelcomparison-gpm-config"
    assert manifest["scope"] == "all"
    assert set(manifest) == {"format", "format_version", "scope", "files"}
    exported_map = json.loads(files["maps.json"])["maps"][0]
    assert "bindings" not in exported_map
    assert set(exported_map["image"]) == {"file"}
    assert exported_map["image"]["file"].startswith("images/")
    assert json.loads(files["map-bindings.json"])["map_bindings"][0]["bindings"]

    inspected = _inspect(client, exported.content)
    assert inspected.status_code == 200, inspected.text
    report = inspected.json()
    assert report["valid"] is True
    assert report["summary"]["maps"]["unchanged"] == 1
    assert report["summary"]["metric_scales"]["unchanged"] == 1
    assert report["summary"]["scale_sets"]["unchanged"] == 1

    applied = client.post(
        f"/api/gpm-heatmaps/configuration/imports/{report['import_id']}/apply"
    )
    assert applied.status_code == 200, applied.text
    catalog = client.get("/api/gpm-heatmaps/configuration").json()
    assert catalog["metric_scales"][0]["revision"] == 1
    assert catalog["scale_sets"][0]["revision"] == 1
    assert catalog["maps"][0]["revision"] == 1


def test_map_only_import_updates_resource_without_touching_scale_bindings(client, png_bytes):
    _seed_configuration(client, png_bytes(size=(80, 60)))
    before = client.get("/api/gpm-heatmaps/configuration").json()

    exported = client.get("/api/gpm-heatmaps/configuration/export?scope=maps")
    assert exported.status_code == 200, exported.text
    files = _files_from_zip(exported.content)
    assert set(files) == {
        "manifest.json", "maps.json",
        next(name for name in files if name.startswith("images/")),
    }
    assert json.loads(files["manifest.json"])["scope"] == "maps"
    maps = json.loads(files["maps.json"])
    maps["maps"][0]["origin"] = [-321, -654]
    files["maps.json"] = json.dumps(maps, ensure_ascii=False, indent=2).encode()

    report = _inspect(client, _rebuilt_package(files)).json()
    assert report["valid"] is True
    assert report["summary"]["maps"]["included"] is True
    assert report["summary"]["metric_scales"]["included"] is False
    assert report["summary"]["map_bindings"]["included"] is False
    assert client.post(
        f"/api/gpm-heatmaps/configuration/imports/{report['import_id']}/apply"
    ).status_code == 200

    after = client.get("/api/gpm-heatmaps/configuration").json()
    assert after["maps"][0]["origin"] == [-321, -654]
    assert after["maps"][0]["bindings"] == before["maps"][0]["bindings"]
    assert after["metric_scales"] == before["metric_scales"]
    assert after["scale_sets"] == before["scale_sets"]


def test_import_accepts_safe_images_directory_entry(client, png_bytes):
    _seed_configuration(client, png_bytes(size=(80, 60)))
    files = _files_from_zip(
        client.get("/api/gpm-heatmaps/configuration/export?scope=maps").content
    )
    files["images/"] = b""

    inspected = _inspect(client, _rebuilt_package(files)).json()
    assert inspected["valid"] is True
    assert inspected["issues"] == []


def test_map_without_image_exports_an_editable_null_file_object(client):
    configuration = {
        "description": "待补图片",
        "origin": [0, 0],
        "range": [100, 200],
        "x_reverse": False,
        "y_reverse": True,
        "bindings": [],
    }
    created = client.put(
        "/api/gpm-heatmaps/configuration/maps/Map_Without_Image",
        data={"configuration": json.dumps(configuration)},
    )
    assert created.status_code == 200, created.text

    exported = client.get("/api/gpm-heatmaps/configuration/export?scope=maps")
    files = _files_from_zip(exported.content)
    exported_map = json.loads(files["maps.json"])["maps"][0]
    assert exported_map["image"] == {"file": None}

    inspected = _inspect(client, exported.content).json()
    assert inspected["valid"] is True


def test_scale_only_import_excludes_map_resources_and_preserves_them(client, png_bytes):
    _seed_configuration(client, png_bytes(size=(80, 60)))
    before = client.get("/api/gpm-heatmaps/configuration").json()

    exported = client.get("/api/gpm-heatmaps/configuration/export?scope=scales")
    assert exported.status_code == 200, exported.text
    files = _files_from_zip(exported.content)
    assert set(files) == {
        "manifest.json", "metric-scales.json", "scale-sets.json", "map-bindings.json",
    }
    assert json.loads(files["manifest.json"])["scope"] == "scales"
    scales = json.loads(files["metric-scales.json"])
    scales["metric_scales"][0]["name"] = "只更新标尺"
    files["metric-scales.json"] = json.dumps(scales, ensure_ascii=False, indent=2).encode()

    report = _inspect(client, _rebuilt_package(files)).json()
    assert report["valid"] is True
    assert report["summary"]["maps"]["included"] is False
    assert report["summary"]["metric_scales"]["included"] is True
    assert client.post(
        f"/api/gpm-heatmaps/configuration/imports/{report['import_id']}/apply"
    ).status_code == 200

    after = client.get("/api/gpm-heatmaps/configuration").json()
    assert after["metric_scales"][0]["name"] == "只更新标尺"
    assert after["maps"][0]["origin"] == before["maps"][0]["origin"]
    assert after["maps"][0]["image"] == before["maps"][0]["image"]
    assert after["maps"][0]["bindings"] == before["maps"][0]["bindings"]
    assert after["maps"][0]["revision"] == before["maps"][0]["revision"]


def test_import_inspects_and_atomically_applies_edited_configuration(client, png_bytes):
    _seed_configuration(client, png_bytes(size=(80, 60)))
    files = _files_from_zip(client.get("/api/gpm-heatmaps/configuration/export").content)
    scales = json.loads(files["metric-scales.json"])
    scales["metric_scales"][0]["name"] = "场景 DC 一档"
    files["metric-scales.json"] = json.dumps(scales, ensure_ascii=False, indent=2).encode()
    maps = json.loads(files["maps.json"])
    maps["maps"][0]["origin"] = [-120, -220]
    files["maps.json"] = json.dumps(maps, ensure_ascii=False, indent=2).encode()

    inspected = _inspect(client, _rebuilt_package(files)).json()
    assert inspected["valid"] is True
    assert "current" not in inspected
    assert inspected["summary"]["metric_scales"]["updated"] == 1
    assert inspected["summary"]["maps"]["updated"] == 1
    assert client.post(
        f"/api/gpm-heatmaps/configuration/imports/{inspected['import_id']}/apply"
    ).status_code == 200

    catalog = client.get("/api/gpm-heatmaps/configuration").json()
    assert catalog["metric_scales"][0]["name"] == "场景 DC 一档"
    assert catalog["metric_scales"][0]["revision"] == 2
    assert catalog["maps"][0]["origin"] == [-120, -220]
    assert catalog["maps"][0]["revision"] == 2
    assert client.get(catalog["maps"][0]["image"]["url"]).status_code == 200


def test_import_rechecks_revisions_before_apply(client, png_bytes):
    _seed_configuration(client, png_bytes())
    exported = client.get("/api/gpm-heatmaps/configuration/export").content
    inspected = _inspect(client, exported).json()
    assert inspected["valid"] is True

    changed = client.put(
        "/api/gpm-heatmaps/configuration/scales/0",
        json={"name": "并发修改", "segments": SEGMENTS, "expected_revision": 1},
    )
    assert changed.status_code == 200
    applied = client.post(
        f"/api/gpm-heatmaps/configuration/imports/{inspected['import_id']}/apply"
    )
    assert applied.status_code == 409
    catalog = client.get("/api/gpm-heatmaps/configuration").json()
    assert catalog["metric_scales"][0]["name"] == "并发修改"
    assert catalog["maps"][0]["revision"] == 1


def test_import_rejects_same_revision_object_created_after_inspection(client, png_bytes):
    _seed_configuration(client, png_bytes())
    files = _files_from_zip(client.get("/api/gpm-heatmaps/configuration/export").content)
    scales = json.loads(files["metric-scales.json"])
    scales["metric_scales"].append({
        "id": 1,
        "name": "待导入标尺",
        "revision": 1,
        "segments": SEGMENTS,
    })
    files["metric-scales.json"] = json.dumps(
        scales, ensure_ascii=False, indent=2,
    ).encode()
    inspected = _inspect(client, _rebuilt_package(files)).json()
    assert inspected["valid"] is True

    concurrent = client.post(
        "/api/gpm-heatmaps/configuration/scales",
        json={"name": "并发新建标尺", "segments": SEGMENTS},
    )
    assert concurrent.status_code == 201
    assert concurrent.json()["id"] == 1

    applied = client.post(
        f"/api/gpm-heatmaps/configuration/imports/{inspected['import_id']}/apply"
    )
    assert applied.status_code == 409
    assert applied.json()["detail"]["code"] == "CONFIGURATION_CHANGED_SINCE_INSPECTION"
    catalog = client.get("/api/gpm-heatmaps/configuration").json()
    assert catalog["metric_scales"][1]["name"] == "并发新建标尺"


def test_import_reports_invalid_references_and_unsafe_paths_without_mutation(client, png_bytes):
    _seed_configuration(client, png_bytes())
    files = _files_from_zip(client.get("/api/gpm-heatmaps/configuration/export").content)
    sets = json.loads(files["scale-sets.json"])
    sets["scale_sets"][0]["items"][0]["scale_id"] = 999
    files["scale-sets.json"] = json.dumps(sets, ensure_ascii=False, indent=2).encode()
    invalid = _inspect(client, _rebuilt_package(files)).json()
    assert invalid["valid"] is False
    assert invalid["import_id"] is None
    assert invalid["issues"][0]["code"] == "MISSING_METRIC_SCALE_REFERENCE"

    files = _files_from_zip(client.get("/api/gpm-heatmaps/configuration/export").content)
    files["../outside.txt"] = b"unsafe"
    unsafe = _inspect(client, _rebuilt_package(files)).json()
    assert unsafe["valid"] is False
    assert unsafe["issues"][0]["code"] == "UNSAFE_CONFIG_PACKAGE_PATH"
    assert client.get("/api/gpm-heatmaps/configuration").json()["metric_scales"][0]["name"] == "场景 DC"


def test_import_reports_decompression_bomb_as_invalid_image(client, png_bytes, monkeypatch):
    _seed_configuration(client, png_bytes())
    exported = client.get("/api/gpm-heatmaps/configuration/export").content

    def raise_bomb(*_args, **_kwargs):
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr("app.gpm_configuration_package.Image.open", raise_bomb)
    inspected = _inspect(client, exported).json()
    assert inspected["valid"] is False
    assert inspected["issues"][0]["code"] == "INVALID_MAP_IMAGE"


def test_previous_package_shape_is_rejected_instead_of_compatibly_converted(client, png_bytes):
    _seed_configuration(client, png_bytes())
    files = _files_from_zip(client.get("/api/gpm-heatmaps/configuration/export").content)
    manifest = json.loads(files["manifest.json"])
    manifest.pop("scope")
    manifest["files"] = {
        "maps": "maps.json",
        "metric_scales": "metric-scales.json",
        "scale_sets": "scale-sets.json",
        "readme": "README.md",
        "images": "images/",
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    files["README.md"] = b"legacy package"

    inspected = _inspect(client, _rebuilt_package(files))
    assert inspected.status_code == 200
    report = inspected.json()
    assert report["valid"] is False
    assert report["import_id"] is None
    assert report["issues"][0]["code"] == "INVALID_CONFIG_MANIFEST"


def test_new_object_from_another_environment_may_have_a_higher_source_revision(client, png_bytes):
    _seed_configuration(client, png_bytes())
    files = _files_from_zip(client.get("/api/gpm-heatmaps/configuration/export").content)
    scales = json.loads(files["metric-scales.json"])
    scales["metric_scales"].append({
        "id": 7, "name": "外部环境标尺", "revision": 12, "segments": SEGMENTS,
    })
    files["metric-scales.json"] = json.dumps(scales, ensure_ascii=False, indent=2).encode()

    inspected = _inspect(client, _rebuilt_package(files)).json()
    assert inspected["valid"] is True
    assert inspected["summary"]["metric_scales"]["new"] == 1
    assert client.post(
        f"/api/gpm-heatmaps/configuration/imports/{inspected['import_id']}/apply"
    ).status_code == 200
    imported = client.get("/api/gpm-heatmaps/configuration").json()["metric_scales"][-1]
    assert imported["id"] == 7
    assert imported["revision"] == 1
