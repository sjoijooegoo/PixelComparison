"""GPMHeatmap 可移植配置包。

本模块是配置迁移的唯一边界：导出可读 ZIP、只读检查、短期暂存，以及把已经
检查过的配置以单事务安全合并到现有地图、指标标尺和指标标尺集中。
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .gpm_common import IMAGE_SUFFIXES, PLATFORMS, SAFE_IDENTIFIER, safe_segment
from .gpm_scale_expressions import ScaleExpressionError, compile_scale_segments
from .gpm_map_config import MAX_MAP_IMAGE_BYTES
from .gpm_storage import connect_gpm_database, gpm_assets_dir


PACKAGE_FORMAT = "pixelcomparison-gpm-config"
PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_PACKAGE_FILES = 1000
MAX_JSON_BYTES = 8 * 1024 * 1024
IMPORT_TTL_SECONDS = 24 * 60 * 60
PACKAGE_SCOPES = frozenset({"all", "maps", "scales"})
MAP_FILES = {
    "maps": "maps.json",
    "images": "images/",
}
SCALE_FILES = {
    "metric_scales": "metric-scales.json",
    "scale_sets": "scale-sets.json",
    "map_bindings": "map-bindings.json",
}


class ConfigurationPackageError(Exception):
    def __init__(self, issues: list[dict]):
        super().__init__(issues[0]["message"] if issues else "配置包无效")
        self.issues = issues


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False,
    ) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configuration_revision_token(connection: sqlite3.Connection) -> str:
    """Fingerprint the editable configuration state inspected by an import."""

    queries = {
        "metric_scales": "SELECT id, name, revision FROM gpm_metric_scales ORDER BY id",
        "scale_sets": "SELECT id, name, revision FROM gpm_metric_scale_sets ORDER BY id",
        "scale_set_items": """
            SELECT scale_set_id, metric_key, scale_id
            FROM gpm_metric_scale_set_items ORDER BY scale_set_id, rowid
        """,
        "maps": """
            SELECT map_name, map_id, revision, image_path
            FROM gpm_map_definitions ORDER BY map_name
        """,
        "map_bindings": """
            SELECT map_name, platform, shading_quality, scale_set_id
            FROM gpm_map_scale_set_bindings
            ORDER BY map_name, platform, shading_quality
        """,
    }
    snapshot = {
        key: [dict(row) for row in connection.execute(query)]
        for key, query in queries.items()
    }
    canonical = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def _transfer_root() -> Path:
    root = gpm_assets_dir() / ".configuration-transfers"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_stale_transfers() -> None:
    cutoff = time.time() - IMPORT_TTL_SECONDS
    root = _transfer_root()
    for candidate in root.iterdir():
        try:
            if candidate.stat().st_mtime >= cutoff:
                continue
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)
            else:
                candidate.unlink(missing_ok=True)
        except OSError:
            continue


def remove_transfer(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_asset(path_value: str) -> Path:
    relative = PurePosixPath(path_value)
    target = gpm_assets_dir() / Path(*relative.parts)
    try:
        target.relative_to(gpm_assets_dir())
    except ValueError as exc:
        raise ConfigurationPackageError([{
            "code": "INVALID_STORED_IMAGE_PATH",
            "scope": "maps",
            "message": "地图图片路径超出 GPM 资源目录",
        }]) from exc
    try:
        if not target.is_file():
            raise FileNotFoundError(target)
        return target
    except OSError as exc:
        raise ConfigurationPackageError([{
            "code": "MISSING_STORED_MAP_IMAGE",
            "scope": "maps",
            "message": f"地图图片文件不存在：{path_value}",
        }]) from exc


def _export_payload(connection: sqlite3.Connection) -> tuple[dict, dict, dict, dict, dict[str, Path]]:
    scales = []
    for row in connection.execute("SELECT * FROM gpm_metric_scales ORDER BY id"):
        scales.append({
            "id": row["id"],
            "name": row["name"],
            "revision": row["revision"],
            "segments": compile_scale_segments(json.loads(row["segments_json"])).segments,
        })

    sets = []
    for row in connection.execute("SELECT * FROM gpm_metric_scale_sets ORDER BY id"):
        items = [dict(item) for item in connection.execute(
            """
            SELECT metric_key, scale_id FROM gpm_metric_scale_set_items
            WHERE scale_set_id = ? ORDER BY rowid
            """,
            (row["id"],),
        )]
        sets.append({
            "id": row["id"], "name": row["name"],
            "revision": row["revision"], "items": items,
        })

    images: dict[str, Path] = {}
    maps = []
    map_bindings = []
    for row in connection.execute(
        "SELECT * FROM gpm_map_definitions ORDER BY map_id, map_name COLLATE NOCASE"
    ):
        image = {"file": None}
        if row["image_path"]:
            target = _read_asset(row["image_path"])
            suffix = target.suffix.lower()
            image_name = (
                f"images/{row['map_id']:04d}-{safe_segment(row['map_name'], 'map')}{suffix}"
            )
            images[image_name] = target
            image = {"file": image_name}
        bindings = [dict(item) for item in connection.execute(
            """
            SELECT platform, shading_quality, scale_set_id
            FROM gpm_map_scale_set_bindings WHERE map_name = ?
            ORDER BY platform, shading_quality DESC
            """,
            (row["map_name"],),
        )]
        maps.append({
            "id": row["map_id"],
            "map_name": row["map_name"],
            "description": row["description"],
            "revision": row["revision"],
            "origin": [row["origin_x"], row["origin_y"]],
            "range": [row["range_x"], row["range_y"]],
            "x_reverse": bool(row["x_reverse"]),
            "y_reverse": bool(row["y_reverse"]),
            "image": image,
        })
        map_bindings.append({
            "map_name": row["map_name"],
            "map_revision": row["revision"],
            "bindings": bindings,
        })
    return (
        {"maps": maps},
        {"metric_scales": scales},
        {"scale_sets": sets},
        {"map_bindings": map_bindings},
        images,
    )


def export_configuration_package(scope: str = "all") -> tuple[Path, str]:
    """按模块生成可人工编辑的 ZIP 配置包。"""

    if scope not in PACKAGE_SCOPES:
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_EXPORT_SCOPE", "scope", "导出范围必须是 all、maps 或 scales"),
        ])

    _cleanup_stale_transfers()
    includes_maps = scope in {"all", "maps"}
    includes_scales = scope in {"all", "scales"}
    root = _transfer_root()
    descriptor, raw_path = tempfile.mkstemp(prefix="gpm-config-export-", suffix=".zip", dir=root)
    os.close(descriptor)
    path = Path(raw_path)
    connection = connect_gpm_database()
    try:
        # The transaction also keeps map image replacements from deleting a file
        # between reading its database row and adding it to the archive.
        connection.execute("BEGIN IMMEDIATE")
        maps, scales, scale_sets, map_bindings, images = _export_payload(connection)
        payloads: dict[str, bytes] = {}
        manifest_files: dict[str, str] = {}
        if includes_maps:
            payloads["maps.json"] = _json_bytes(maps)
            manifest_files.update(MAP_FILES)
        if includes_scales:
            payloads["metric-scales.json"] = _json_bytes(scales)
            payloads["scale-sets.json"] = _json_bytes(scale_sets)
            payloads["map-bindings.json"] = _json_bytes(map_bindings)
            manifest_files.update(SCALE_FILES)
        manifest = {
            "format": PACKAGE_FORMAT,
            "format_version": PACKAGE_VERSION,
            "scope": scope,
            "files": manifest_files,
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _json_bytes(manifest))
            for name, raw in payloads.items():
                archive.writestr(name, raw)
            if includes_maps:
                for name, image_path in images.items():
                    archive.write(image_path, arcname=name)
        connection.commit()
    except Exception:
        connection.rollback()
        path.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    suffix = {"all": "all", "maps": "maps", "scales": "scales"}[scope]
    return path, f"gpm-heatmap-config-{suffix}-{timestamp}.zip"


def _issue(code: str, scope: str, message: str) -> dict:
    return {"code": code, "scope": scope, "message": message}


def _valid_archive_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    normalized_name = name[:-1] if name.endswith("/") else name
    if not normalized_name:
        return False
    path = PurePosixPath(normalized_name)
    return ".." not in path.parts and str(path) == normalized_name


def _load_json(archive: zipfile.ZipFile, name: str) -> object:
    info = archive.getinfo(name)
    if info.file_size > MAX_JSON_BYTES:
        raise ConfigurationPackageError([
            _issue("CONFIG_JSON_TOO_LARGE", name, f"{name} 超过 8 MiB"),
        ])
    try:
        return json.loads(archive.read(name).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_JSON", name, f"{name} 不是有效 UTF-8 JSON"),
        ]) from exc


def _integer(value: object, scope: str, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_VALUE", scope, f"{label} 必须是大于等于 {minimum} 的整数"),
        ])
    return value


def _text(value: object, scope: str, label: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or any(ord(character) < 32 for character in result):
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_VALUE", scope, f"{label}不能为空且不能超过 {maximum} 个字符"),
        ])
    return result


def _pair(value: object, scope: str, label: str, *, positive: bool = False) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_VALUE", scope, f"{label} 必须包含两个数字"),
        ])
    try:
        result = [float(value[0]), float(value[1])]
    except (TypeError, ValueError) as exc:
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_VALUE", scope, f"{label} 必须包含两个数字"),
        ]) from exc
    if any(not math.isfinite(number) for number in result):
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_VALUE", scope, f"{label} 必须包含有限数字"),
        ])
    if positive and any(number <= 0 for number in result):
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_VALUE", scope, f"{label} 必须大于 0"),
        ])
    return result


def _normalize_scales(root: object) -> list[dict]:
    if not isinstance(root, dict) or not isinstance(root.get("metric_scales"), list):
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_SCHEMA", "metric-scales.json", "metric_scales 必须是数组"),
        ])
    result = []
    ids: set[int] = set()
    names: set[str] = set()
    for index, raw in enumerate(root["metric_scales"]):
        scope = f"metric-scales.json/metric_scales[{index}]"
        if not isinstance(raw, dict):
            raise ConfigurationPackageError([_issue("INVALID_CONFIG_SCHEMA", scope, "指标标尺必须是对象")])
        scale_id = _integer(raw.get("id"), scope, "id")
        name = _text(raw.get("name"), scope, "name", 100)
        revision = _integer(raw.get("revision"), scope, "revision", minimum=1)
        try:
            segments = compile_scale_segments(raw.get("segments")).segments
        except ScaleExpressionError as exc:
            raise ConfigurationPackageError([
                _issue("INVALID_SCALE_SEGMENTS", scope, str(exc)),
            ]) from exc
        if scale_id in ids or name in names:
            raise ConfigurationPackageError([
                _issue("DUPLICATE_SCALE", scope, "指标标尺 ID 和名称在包内必须唯一"),
            ])
        ids.add(scale_id)
        names.add(name)
        result.append({"id": scale_id, "name": name, "revision": revision, "segments": segments})
    return result


def _normalize_scale_sets(root: object) -> list[dict]:
    if not isinstance(root, dict) or not isinstance(root.get("scale_sets"), list):
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_SCHEMA", "scale-sets.json", "scale_sets 必须是数组"),
        ])
    result = []
    ids: set[int] = set()
    names: set[str] = set()
    for index, raw in enumerate(root["scale_sets"]):
        scope = f"scale-sets.json/scale_sets[{index}]"
        if not isinstance(raw, dict):
            raise ConfigurationPackageError([_issue("INVALID_CONFIG_SCHEMA", scope, "指标标尺集必须是对象")])
        set_id = _integer(raw.get("id"), scope, "id")
        name = _text(raw.get("name"), scope, "name", 100)
        revision = _integer(raw.get("revision"), scope, "revision", minimum=1)
        raw_items = raw.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ConfigurationPackageError([
                _issue("INVALID_SCALE_SET_ITEMS", scope, "指标标尺集至少需要一个 Key"),
            ])
        items = []
        keys: set[str] = set()
        for item_index, item in enumerate(raw_items):
            item_scope = f"{scope}/items[{item_index}]"
            if not isinstance(item, dict):
                raise ConfigurationPackageError([_issue("INVALID_CONFIG_SCHEMA", item_scope, "映射必须是对象")])
            metric_key = _text(item.get("metric_key"), item_scope, "metric_key", 200)
            scale_id = _integer(item.get("scale_id"), item_scope, "scale_id")
            if metric_key in keys:
                raise ConfigurationPackageError([
                    _issue("DUPLICATE_SCALE_SET_KEY", item_scope, "同一标尺集内指标 Key 不能重复"),
                ])
            keys.add(metric_key)
            items.append({"metric_key": metric_key, "scale_id": scale_id})
        if set_id in ids or name in names:
            raise ConfigurationPackageError([
                _issue("DUPLICATE_SCALE_SET", scope, "指标标尺集 ID 和名称在包内必须唯一"),
            ])
        ids.add(set_id)
        names.add(name)
        result.append({
            "id": set_id, "name": name, "revision": revision,
            "items": items,
        })
    return result


def _normalize_maps(root: object, archive: zipfile.ZipFile) -> list[dict]:
    if not isinstance(root, dict) or not isinstance(root.get("maps"), list):
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_SCHEMA", "maps.json", "maps 必须是数组"),
        ])
    result = []
    ids: set[int] = set()
    names: set[str] = set()
    referenced_images: set[str] = set()
    archive_names = set(archive.namelist())
    for index, raw in enumerate(root["maps"]):
        scope = f"maps.json/maps[{index}]"
        if not isinstance(raw, dict):
            raise ConfigurationPackageError([_issue("INVALID_CONFIG_SCHEMA", scope, "地图必须是对象")])
        map_id = _integer(raw.get("id"), scope, "id")
        map_name = _text(raw.get("map_name"), scope, "map_name", 200)
        if not SAFE_IDENTIFIER.fullmatch(map_name):
            raise ConfigurationPackageError([
                _issue("INVALID_MAP_NAME", scope, "map_name 仅允许字母、数字、点、下划线和连字符"),
            ])
        description = str(raw.get("description") or map_name).strip()
        if len(description) > 500:
            raise ConfigurationPackageError([_issue("INVALID_CONFIG_VALUE", scope, "description 不能超过 500 个字符")])
        revision = _integer(raw.get("revision"), scope, "revision", minimum=1)
        origin = _pair(raw.get("origin"), scope, "origin")
        range_value = _pair(raw.get("range"), scope, "range", positive=True)
        x_reverse = raw.get("x_reverse", False)
        y_reverse = raw.get("y_reverse", True)
        if not isinstance(x_reverse, bool) or not isinstance(y_reverse, bool):
            raise ConfigurationPackageError([_issue("INVALID_CONFIG_VALUE", scope, "坐标轴反转必须是布尔值")])

        image = raw.get("image")
        normalized_image = None
        if not isinstance(image, dict) or set(image) != {"file"}:
            raise ConfigurationPackageError([
                _issue("INVALID_CONFIG_SCHEMA", scope, "image 必须是只包含 file 的对象"),
            ])
        image_file_value = image.get("file")
        if image_file_value is not None:
            image_file = _text(image_file_value, scope, "image.file", 240)
            suffix = PurePosixPath(image_file).suffix.lower()
            if not image_file.startswith("images/") or suffix not in IMAGE_SUFFIXES or image_file not in archive_names:
                raise ConfigurationPackageError([_issue("INVALID_MAP_IMAGE", scope, "地图图片引用无效")])
            raw_image = archive.read(image_file)
            try:
                with Image.open(io.BytesIO(raw_image)) as opened:
                    opened.verify()
                with Image.open(io.BytesIO(raw_image)) as opened:
                    actual_width, actual_height = opened.size
            except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
                raise ConfigurationPackageError([_issue("INVALID_MAP_IMAGE", scope, "地图图片无法解析")]) from exc
            referenced_images.add(image_file)
            normalized_image = {
                "file": image_file, "width": actual_width, "height": actual_height,
                "sha256": _sha256_bytes(raw_image),
            }

        if map_id in ids or map_name in names:
            raise ConfigurationPackageError([_issue("DUPLICATE_MAP", scope, "地图 ID 和名称在包内必须唯一")])
        ids.add(map_id)
        names.add(map_name)
        result.append({
            "id": map_id, "map_name": map_name, "description": description,
            "revision": revision, "origin": origin, "range": range_value,
            "x_reverse": x_reverse, "y_reverse": y_reverse,
            "image": normalized_image,
        })

    orphan_images = sorted(
        name for name in archive_names
        if name.startswith("images/") and not name.endswith("/") and name not in referenced_images
    )
    if orphan_images:
        raise ConfigurationPackageError([
            _issue("ORPHAN_PACKAGE_IMAGE", "images", f"存在未被地图引用的图片：{orphan_images[0]}"),
        ])
    return result


def _normalize_map_bindings(root: object) -> list[dict]:
    if not isinstance(root, dict) or not isinstance(root.get("map_bindings"), list):
        raise ConfigurationPackageError([
            _issue("INVALID_CONFIG_SCHEMA", "map-bindings.json", "map_bindings 必须是数组"),
        ])
    result = []
    map_names: set[str] = set()
    for index, raw in enumerate(root["map_bindings"]):
        scope = f"map-bindings.json/map_bindings[{index}]"
        if not isinstance(raw, dict):
            raise ConfigurationPackageError([_issue("INVALID_CONFIG_SCHEMA", scope, "地图标尺关联必须是对象")])
        map_name = _text(raw.get("map_name"), scope, "map_name", 200)
        if not SAFE_IDENTIFIER.fullmatch(map_name):
            raise ConfigurationPackageError([
                _issue("INVALID_MAP_NAME", scope, "map_name 仅允许字母、数字、点、下划线和连字符"),
            ])
        if map_name in map_names:
            raise ConfigurationPackageError([
                _issue("DUPLICATE_MAP_BINDING_GROUP", scope, "同一地图只能出现一组标尺关联"),
            ])
        map_names.add(map_name)
        map_revision = _integer(raw.get("map_revision"), scope, "map_revision", minimum=1)
        raw_bindings = raw.get("bindings")
        if not isinstance(raw_bindings, list):
            raise ConfigurationPackageError([_issue("INVALID_MAP_BINDINGS", scope, "bindings 必须是数组")])
        bindings = []
        scopes: set[tuple[str, int]] = set()
        for binding_index, binding in enumerate(raw_bindings):
            binding_scope = f"{scope}/bindings[{binding_index}]"
            if not isinstance(binding, dict):
                raise ConfigurationPackageError([_issue("INVALID_CONFIG_SCHEMA", binding_scope, "绑定必须是对象")])
            platform = str(binding.get("platform") or "").strip()
            if platform not in PLATFORMS:
                raise ConfigurationPackageError([_issue("INVALID_PLATFORM", binding_scope, "platform 必须是 IOS、Android 或 Windows")])
            quality = _integer(binding.get("shading_quality"), binding_scope, "shading_quality")
            if quality > 5:
                raise ConfigurationPackageError([_issue("INVALID_QUALITY", binding_scope, "shading_quality 必须在 0 到 5 之间")])
            scale_set_id = _integer(binding.get("scale_set_id"), binding_scope, "scale_set_id")
            key = (platform, quality)
            if key in scopes:
                raise ConfigurationPackageError([_issue("DUPLICATE_MAP_BINDING", binding_scope, "平台和画质绑定不能重复")])
            scopes.add(key)
            bindings.append({
                "platform": platform,
                "shading_quality": quality,
                "scale_set_id": scale_set_id,
            })
        result.append({
            "map_name": map_name,
            "map_revision": map_revision,
            "bindings": sorted(bindings, key=lambda item: (item["platform"], -item["shading_quality"])),
        })
    return result


def _read_package(path: Path) -> dict:
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ConfigurationPackageError([_issue("INVALID_CONFIG_PACKAGE", "package", "请选择有效 ZIP 配置包")]) from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(infos) > MAX_PACKAGE_FILES or len(names) != len(set(names)):
            raise ConfigurationPackageError([_issue("INVALID_CONFIG_PACKAGE", "package", "配置包文件过多或存在重名文件")])
        if any(not _valid_archive_name(name) for name in names):
            raise ConfigurationPackageError([_issue("UNSAFE_CONFIG_PACKAGE_PATH", "package", "配置包包含不安全路径")])
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise ConfigurationPackageError([_issue("CONFIG_PACKAGE_TOO_LARGE", "package", "配置包解压后超过 1 GiB")])
        if any(
            info.filename.startswith("images/") and info.file_size > MAX_MAP_IMAGE_BYTES
            for info in infos
        ):
            raise ConfigurationPackageError([_issue("MAP_IMAGE_TOO_LARGE", "images", "单张地图图片超过 32 MiB")])
        if "manifest.json" not in names:
            raise ConfigurationPackageError([_issue("MISSING_CONFIG_FILE", "package", "缺少文件：manifest.json")])
        manifest = _load_json(archive, "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("format") != PACKAGE_FORMAT or manifest.get("format_version") != PACKAGE_VERSION:
            raise ConfigurationPackageError([_issue("UNSUPPORTED_CONFIG_PACKAGE", "manifest.json", "配置包格式或版本不受支持")])
        if set(manifest) != {"format", "format_version", "scope", "files"}:
            raise ConfigurationPackageError([
                _issue("INVALID_CONFIG_MANIFEST", "manifest.json", "manifest 只能包含格式、版本、范围和文件清单"),
            ])
        scope = manifest.get("scope")
        if scope not in PACKAGE_SCOPES:
            raise ConfigurationPackageError([
                _issue("INVALID_CONFIG_MANIFEST", "manifest.json", "scope 必须是 all、maps 或 scales"),
            ])
        includes_maps = scope in {"all", "maps"}
        includes_scales = scope in {"all", "scales"}
        expected_files = {
            **(MAP_FILES if includes_maps else {}),
            **(SCALE_FILES if includes_scales else {}),
        }
        if manifest.get("files") != expected_files:
            raise ConfigurationPackageError([
                _issue("INVALID_CONFIG_MANIFEST", "manifest.json", "配置文件位置与导出范围不匹配"),
            ])
        required = {"manifest.json", *expected_files.values()}
        required.discard("images/")
        missing = required - set(names)
        if missing:
            raise ConfigurationPackageError([_issue("MISSING_CONFIG_FILE", "package", f"缺少文件：{', '.join(sorted(missing))}")])
        allowed = required | ({name for name in names if name.startswith("images/")} if includes_maps else set())
        unexpected = set(names) - allowed
        if unexpected:
            raise ConfigurationPackageError([_issue("UNEXPECTED_CONFIG_FILE", "package", f"存在未知文件：{sorted(unexpected)[0]}")])

        maps = _normalize_maps(_load_json(archive, "maps.json"), archive) if includes_maps else []
        scales = _normalize_scales(_load_json(archive, "metric-scales.json")) if includes_scales else []
        scale_sets = _normalize_scale_sets(_load_json(archive, "scale-sets.json")) if includes_scales else []
        map_bindings = _normalize_map_bindings(_load_json(archive, "map-bindings.json")) if includes_scales else []
        return {
            "manifest": {
                "format_version": PACKAGE_VERSION,
                "scope": scope,
            },
            "includes_maps": includes_maps,
            "includes_scales": includes_scales,
            "metric_scales": scales,
            "scale_sets": scale_sets,
            "maps": maps,
            "map_bindings": map_bindings,
        }


def _current_snapshot(connection: sqlite3.Connection) -> dict:
    scales = {}
    for row in connection.execute("SELECT * FROM gpm_metric_scales"):
        scales[row["id"]] = {
            "id": row["id"], "name": row["name"], "revision": row["revision"],
            "segments": compile_scale_segments(json.loads(row["segments_json"])).segments,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
    sets = {}
    for row in connection.execute("SELECT * FROM gpm_metric_scale_sets"):
        items = [dict(item) for item in connection.execute(
            "SELECT metric_key, scale_id FROM gpm_metric_scale_set_items WHERE scale_set_id = ? ORDER BY rowid",
            (row["id"],),
        )]
        sets[row["id"]] = {
            "id": row["id"], "name": row["name"], "revision": row["revision"],
            "items": items, "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
    maps = {}
    map_bindings = {}
    for row in connection.execute("SELECT * FROM gpm_map_definitions"):
        image = None
        if row["image_path"]:
            target = gpm_assets_dir() / Path(*PurePosixPath(row["image_path"]).parts)
            image = {
                "path": row["image_path"], "width": row["image_width"],
                "height": row["image_height"],
                "sha256": _sha256_file(target) if target.is_file() else None,
            }
        bindings = [dict(item) for item in connection.execute(
            """
            SELECT platform, shading_quality, scale_set_id FROM gpm_map_scale_set_bindings
            WHERE map_name = ? ORDER BY platform, shading_quality DESC
            """,
            (row["map_name"],),
        )]
        maps[row["map_name"]] = {
            "id": row["map_id"], "map_name": row["map_name"],
            "description": row["description"], "revision": row["revision"],
            "origin": [row["origin_x"], row["origin_y"]],
            "range": [row["range_x"], row["range_y"]],
            "x_reverse": bool(row["x_reverse"]), "y_reverse": bool(row["y_reverse"]),
            "image": image,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        map_bindings[row["map_name"]] = {
            "map_name": row["map_name"],
            "map_revision": row["revision"],
            "bindings": bindings,
        }
    return {
        "metric_scales": scales,
        "scale_sets": sets,
        "maps": maps,
        "map_bindings": map_bindings,
    }


def _comparable(kind: str, item: dict) -> dict:
    if kind == "metric_scales":
        return {key: item[key] for key in ("name", "segments")}
    if kind == "scale_sets":
        return {key: item[key] for key in ("name", "items")}
    if kind == "map_bindings":
        return {"bindings": item["bindings"]}
    image = item.get("image")
    normalized_image = None if image is None else {
        "width": image.get("width"), "height": image.get("height"),
        "sha256": image.get("sha256"),
    }
    return {
        "id": item["id"], "description": item["description"],
        "origin": item["origin"], "range": item["range"],
        "x_reverse": item["x_reverse"], "y_reverse": item["y_reverse"],
        "image": normalized_image,
    }


def _change_details(kind: str, current: dict | None, desired: dict) -> list[str]:
    if current is None:
        return ["新增"]
    labels = {
        "name": "名称", "segments": "颜色分段", "items": "Key 映射",
        "id": "排序 ID", "description": "描述", "origin": "起点",
        "range": "坐标范围", "x_reverse": "X 轴", "y_reverse": "Y 轴",
        "image": "图片", "bindings": "平台/画质绑定",
    }
    left = _comparable(kind, current)
    right = _comparable(kind, desired)
    return [labels.get(key, key) for key in right if left.get(key) != right.get(key)]


def _summary_bucket(total: int = 0, *, included: bool = True) -> dict:
    return {"included": included, "total": total, "new": 0, "updated": 0, "unchanged": 0}


def _analyze(connection: sqlite3.Connection, package: dict) -> dict:
    current = _current_snapshot(connection)
    issues: list[dict] = []

    final_scales = dict(current["metric_scales"])
    if package["includes_scales"]:
        for item in package["metric_scales"]:
            existing = current["metric_scales"].get(item["id"])
            if existing and item["revision"] != existing["revision"]:
                issues.append(_issue("STALE_METRIC_SCALE", f"metric_scales/{item['id']}", f"指标标尺 {item['id']} 已被更新"))
            final_scales[item["id"]] = item
        scale_names: dict[str, int] = {}
        for scale_id, item in final_scales.items():
            other = scale_names.get(item["name"])
            if other is not None and other != scale_id:
                issues.append(_issue("METRIC_SCALE_NAME_CONFLICT", f"metric_scales/{scale_id}", f"指标标尺名称“{item['name']}”已被 ID {other} 使用"))
            scale_names[item["name"]] = scale_id

    final_sets = dict(current["scale_sets"])
    if package["includes_scales"]:
        for item in package["scale_sets"]:
            existing = current["scale_sets"].get(item["id"])
            if existing and item["revision"] != existing["revision"]:
                issues.append(_issue("STALE_SCALE_SET", f"scale_sets/{item['id']}", f"指标标尺集 {item['id']} 已被更新"))
            final_sets[item["id"]] = item
        set_names: dict[str, int] = {}
        for set_id, item in final_sets.items():
            other = set_names.get(item["name"])
            if other is not None and other != set_id:
                issues.append(_issue("SCALE_SET_NAME_CONFLICT", f"scale_sets/{set_id}", f"指标标尺集名称“{item['name']}”已被 ID {other} 使用"))
            set_names[item["name"]] = set_id
            for mapping in item["items"]:
                if mapping["scale_id"] not in final_scales:
                    issues.append(_issue("MISSING_METRIC_SCALE_REFERENCE", f"scale_sets/{set_id}", f"Key {mapping['metric_key']} 引用了不存在的指标标尺 {mapping['scale_id']}"))

    final_maps = dict(current["maps"])
    if package["includes_maps"]:
        for item in package["maps"]:
            existing = current["maps"].get(item["map_name"])
            if existing and item["revision"] != existing["revision"]:
                issues.append(_issue("STALE_MAP", f"maps/{item['map_name']}", f"地图 {item['map_name']} 已被更新"))
            final_maps[item["map_name"]] = item
    map_ids: dict[int, str] = {}
    for map_name, item in final_maps.items():
        other = map_ids.get(item["id"])
        if other is not None and other != map_name:
            issues.append(_issue("MAP_ID_CONFLICT", f"maps/{map_name}", f"地图 ID {item['id']} 已被 {other} 使用"))
        map_ids[item["id"]] = map_name

    if package["includes_scales"]:
        packaged_maps = {item["map_name"]: item for item in package["maps"]}
        for item in package["map_bindings"]:
            map_name = item["map_name"]
            existing_map = current["maps"].get(map_name)
            packaged_map = packaged_maps.get(map_name)
            if not existing_map and not packaged_map:
                issues.append(_issue("MISSING_MAP_REFERENCE", f"map_bindings/{map_name}", f"标尺关联引用了不存在的地图 {map_name}"))
                continue
            expected_revision = existing_map["revision"] if existing_map else packaged_map["revision"]
            if item["map_revision"] != expected_revision:
                issues.append(_issue("STALE_MAP_BINDINGS", f"map_bindings/{map_name}", f"地图 {map_name} 的标尺关联已被更新"))
            for binding in item["bindings"]:
                if binding["scale_set_id"] not in final_sets:
                    issues.append(_issue("MISSING_SCALE_SET_REFERENCE", f"map_bindings/{map_name}", f"绑定引用了不存在的指标标尺集 {binding['scale_set_id']}"))

    changes = []
    summary = {
        "maps": _summary_bucket(len(package["maps"]), included=package["includes_maps"]),
        "metric_scales": _summary_bucket(len(package["metric_scales"]), included=package["includes_scales"]),
        "scale_sets": _summary_bucket(len(package["scale_sets"]), included=package["includes_scales"]),
        "map_bindings": _summary_bucket(len(package["map_bindings"]), included=package["includes_scales"]),
        "images": {
            "included": package["includes_maps"], "total": len(package["maps"]),
            "added": 0, "replaced": 0, "removed": 0, "unchanged": 0,
        },
    }
    labels = {
        "maps": "地图资源", "metric_scales": "指标标尺",
        "scale_sets": "指标标尺集", "map_bindings": "地图标尺关联",
    }
    for kind, identity_key in (
        ("metric_scales", "id"), ("scale_sets", "id"),
        ("maps", "map_name"), ("map_bindings", "map_name"),
    ):
        for item in package[kind]:
            identity = item[identity_key]
            existing = current[kind].get(identity)
            details = _change_details(kind, existing, item)
            action = "new" if existing is None else ("updated" if details else "unchanged")
            summary[kind][action] += 1
            changes.append({
                "kind": kind, "kind_label": labels[kind], "identity": str(identity),
                "name": item.get("name") or item.get("map_name"),
                "action": action, "details": details,
            })
            if kind == "maps":
                current_image = existing.get("image") if existing else None
                desired_image = item.get("image")
                if current_image is None and desired_image is not None:
                    image_action = "added"
                elif current_image is not None and desired_image is None:
                    image_action = "removed"
                elif current_image and desired_image and current_image.get("sha256") != desired_image.get("sha256"):
                    image_action = "replaced"
                else:
                    image_action = "unchanged"
                summary["images"][image_action] += 1

    return {
        "valid": not issues,
        "package": package["manifest"],
        "summary": summary,
        "changes": changes,
        "issues": issues,
        "current": current,
    }


def _invalid_report(issues: list[dict]) -> dict:
    return {
        "valid": False, "import_id": None, "package": None,
        "summary": None, "changes": [], "issues": issues,
    }


def _public_report(report: dict, import_id: str | None) -> dict:
    return {
        key: value for key, value in report.items() if key != "current"
    } | {"import_id": import_id}


def inspect_configuration_package(upload: UploadFile) -> dict:
    """保存候选 ZIP 并只读检查；有效包返回短期 import_id。"""

    _cleanup_stale_transfers()
    import_id = uuid.uuid4().hex
    directory = _transfer_root() / import_id
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "package.zip"
    size = 0
    try:
        with path.open("wb") as destination:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_PACKAGE_BYTES:
                    raise ConfigurationPackageError([
                        _issue("CONFIG_PACKAGE_TOO_LARGE", "package", "配置包超过 512 MiB"),
                    ])
                destination.write(chunk)
        package = _read_package(path)
        connection = connect_gpm_database()
        try:
            report = _analyze(connection, package)
            revision_token = _configuration_revision_token(connection)
        finally:
            connection.close()
        if not report["valid"]:
            remove_transfer(directory)
            return _public_report(report, None)
        (directory / "checked.sha256").write_text(_sha256_file(path), encoding="ascii")
        (directory / "checked.configuration.sha256").write_text(
            revision_token, encoding="ascii",
        )
        return _public_report(report, import_id)
    except ConfigurationPackageError as exc:
        remove_transfer(directory)
        return _invalid_report(exc.issues)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        remove_transfer(directory)
        return _invalid_report([
            _issue("INVALID_CONFIG_PACKAGE", "package", "配置包已损坏、被加密或无法读取"),
        ])
    except Exception:
        remove_transfer(directory)
        raise


def _stage_image(
    archive: zipfile.ZipFile, item: dict, current: dict | None,
    created_files: list[Path],
) -> tuple[str | None, int | None, int | None]:
    image = item.get("image")
    if image is None:
        return None, None, None
    current_image = current.get("image") if current else None
    if current_image and current_image.get("sha256") == image["sha256"]:
        return current_image["path"], current_image["width"], current_image["height"]
    suffix = PurePosixPath(image["file"]).suffix.lower()
    relative = PurePosixPath("maps") / safe_segment(item["map_name"], "map") / f"{uuid.uuid4().hex}{suffix}"
    destination = gpm_assets_dir() / Path(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(archive.read(image["file"]))
    os.replace(temporary, destination)
    created_files.append(destination)
    return relative.as_posix(), image["width"], image["height"]


def apply_configuration_import(import_id: str) -> dict:
    """重新检查暂存包，并在一个数据库事务中执行安全合并。"""

    if len(import_id) != 32 or any(character not in "0123456789abcdef" for character in import_id):
        raise ConfigurationPackageError([_issue("INVALID_IMPORT_ID", "import", "导入检查记录无效")])
    directory = _transfer_root() / import_id
    path = directory / "package.zip"
    checksum_path = directory / "checked.sha256"
    revision_path = directory / "checked.configuration.sha256"
    if not path.is_file() or not checksum_path.is_file() or not revision_path.is_file():
        raise FileNotFoundError(import_id)
    if checksum_path.read_text(encoding="ascii").strip() != _sha256_file(path):
        raise ConfigurationPackageError([_issue("CHANGED_STAGED_PACKAGE", "import", "暂存配置包已发生变化，请重新检查")])

    package = _read_package(path)
    created_files: list[Path] = []
    old_files: list[Path] = []
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        expected_revision_token = revision_path.read_text(encoding="ascii").strip()
        if expected_revision_token != _configuration_revision_token(connection):
            raise ConfigurationPackageError([_issue(
                "CONFIGURATION_CHANGED_SINCE_INSPECTION",
                "import",
                "配置在检查后已发生变化，请重新检查导入包",
            )])
        analysis = _analyze(connection, package)
        if not analysis["valid"]:
            raise ConfigurationPackageError(analysis["issues"])
        current = analysis["current"]
        actions = {
            (change["kind"], change["identity"]): change["action"]
            for change in analysis["changes"]
        }
        now = _now()

        def map_changed(map_name: str) -> bool:
            return any(
                actions.get((kind, map_name)) in {"new", "updated"}
                for kind in ("maps", "map_bindings")
            )

        # 先释放包内现有对象的唯一名称，支持两个对象在一次导入中互换名称。
        for item in package["metric_scales"]:
            if item["id"] in current["metric_scales"]:
                connection.execute(
                    "UPDATE gpm_metric_scales SET name = ? WHERE id = ?",
                    (f"__gpm_import_scale_{import_id}_{item['id']}", item["id"]),
                )
        for item in package["scale_sets"]:
            if item["id"] in current["scale_sets"]:
                connection.execute(
                    "UPDATE gpm_metric_scale_sets SET name = ? WHERE id = ?",
                    (f"__gpm_import_set_{import_id}_{item['id']}", item["id"]),
                )

        for item in package["metric_scales"]:
            existing = current["metric_scales"].get(item["id"])
            if existing:
                changed = actions[("metric_scales", str(item["id"]))] == "updated"
                connection.execute(
                    """
                    UPDATE gpm_metric_scales SET name = ?, segments_json = ?, revision = ?,
                        updated_at = ? WHERE id = ?
                    """,
                    (
                        item["name"], json.dumps(item["segments"], ensure_ascii=False),
                        existing["revision"] + (1 if changed else 0),
                        now if changed else existing["updated_at"], item["id"],
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO gpm_metric_scales
                        (id, name, segments_json, revision, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (item["id"], item["name"], json.dumps(item["segments"], ensure_ascii=False), now, now),
                )

        for item in package["scale_sets"]:
            existing = current["scale_sets"].get(item["id"])
            if existing:
                changed = actions[("scale_sets", str(item["id"]))] == "updated"
                connection.execute(
                    "UPDATE gpm_metric_scale_sets SET name = ?, revision = ?, updated_at = ? WHERE id = ?",
                    (
                        item["name"], existing["revision"] + (1 if changed else 0),
                        now if changed else existing["updated_at"], item["id"],
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO gpm_metric_scale_sets (id, name, revision, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                    (item["id"], item["name"], now, now),
                )
            connection.execute("DELETE FROM gpm_metric_scale_set_items WHERE scale_set_id = ?", (item["id"],))
            connection.executemany(
                "INSERT INTO gpm_metric_scale_set_items (scale_set_id, metric_key, scale_id) VALUES (?, ?, ?)",
                [(item["id"], mapping["metric_key"], mapping["scale_id"]) for mapping in item["items"]],
            )

        if package["includes_maps"]:
            final_map_ids = [item["id"] for item in package["maps"]] + [
                item["id"] for item in current["maps"].values()
            ]
            temporary_map_id = (max(final_map_ids) if final_map_ids else 0) + 1000
            for index, item in enumerate(package["maps"]):
                if item["map_name"] in current["maps"]:
                    connection.execute(
                        "UPDATE gpm_map_definitions SET map_id = ? WHERE map_name = ?",
                        (temporary_map_id + index, item["map_name"]),
                    )

        with zipfile.ZipFile(path, "r") as archive:
            for item in package["maps"]:
                existing = current["maps"].get(item["map_name"])
                image_path, image_width, image_height = _stage_image(
                    archive, item, existing, created_files,
                )
                changed = existing is None or map_changed(item["map_name"])
                if existing:
                    old_image = existing.get("image")
                    if old_image and old_image.get("path") != image_path:
                        old_files.append(gpm_assets_dir() / Path(*PurePosixPath(old_image["path"]).parts))
                    connection.execute(
                        """
                        UPDATE gpm_map_definitions SET map_id = ?, description = ?, origin_x = ?,
                            origin_y = ?, range_x = ?, range_y = ?, x_reverse = ?, y_reverse = ?,
                            image_path = ?, image_width = ?, image_height = ?, revision = ?,
                            updated_at = ? WHERE map_name = ?
                        """,
                        (
                            item["id"], item["description"], item["origin"][0], item["origin"][1],
                            item["range"][0], item["range"][1], int(item["x_reverse"]),
                            int(item["y_reverse"]), image_path, image_width, image_height,
                            existing["revision"] + (1 if changed else 0),
                            now if changed else existing["updated_at"], item["map_name"],
                        ),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO gpm_map_definitions (
                            map_name, map_id, description, origin_x, origin_y, range_x, range_y,
                            x_reverse, y_reverse, image_path, image_width, image_height,
                            revision, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            item["map_name"], item["id"], item["description"],
                            item["origin"][0], item["origin"][1], item["range"][0], item["range"][1],
                            int(item["x_reverse"]), int(item["y_reverse"]), image_path,
                            image_width, image_height, now, now,
                        ),
                    )

        packaged_map_names = {item["map_name"] for item in package["maps"]}
        for item in package["map_bindings"]:
            map_name = item["map_name"]
            connection.execute(
                "DELETE FROM gpm_map_scale_set_bindings WHERE map_name = ?", (map_name,),
            )
            connection.executemany(
                """
                INSERT INTO gpm_map_scale_set_bindings
                    (map_name, platform, shading_quality, scale_set_id)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (map_name, binding["platform"], binding["shading_quality"], binding["scale_set_id"])
                    for binding in item["bindings"]
                ],
            )
            existing = current["maps"].get(map_name)
            if existing and map_name not in packaged_map_names and map_changed(map_name):
                connection.execute(
                    """
                    UPDATE gpm_map_definitions SET revision = revision + 1, updated_at = ?
                    WHERE map_name = ?
                    """,
                    (now, map_name),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        for created in created_files:
            created.unlink(missing_ok=True)
        raise
    finally:
        connection.close()

    for old_file in old_files:
        try:
            old_file.unlink(missing_ok=True)
        except OSError:
            pass
    remove_transfer(directory)
    return {
        "applied": True,
        "summary": analysis["summary"],
        "applied_at": _now(),
    }
