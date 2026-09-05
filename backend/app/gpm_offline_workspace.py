"""只读的 SceneScope 热力图离线工作区。

该模块是离线查看器与 ``.ssheat`` 格式之间唯一的适配层。前端仍使用在线版的
热力图读接口；这里负责校验多个数据包、聚合筛选目录，并重算跨包趋势与上一批次
变化。它不依赖 FastAPI、SQLite 或线上资源目录。
"""

from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .gpm_configuration_format import (
    PACKAGE_FORMAT as CONFIGURATION_FORMAT,
    PACKAGE_VERSION as CONFIGURATION_VERSION,
)
from .gpm_scale_expressions import ScaleExpressionError
from .gpm_scale_runtime import configured_scale_dto, resolve_metric_scales
from .gpm_metric_values import finite_number as _number, metric_change_percentages as _changes
from .gpm_offline_format import (
    CONFIGURATION_FILENAME,
    IMAGE_MODE,
    PACKAGE_FORMAT,
    PACKAGE_VERSION,
    PLATFORMS,
    QUALITY_LABELS,
)


VIEWER_VERSION = 2
TREND_DAYS = {7, 14, 30}
TREND_SUMMARY_FIELDS = {
    "Scene_DC": "AvgSceneDrawCall",
    "Scene_Tris": "AvgSceneTriangle",
    "Drawcall": "AvgDrawCall",
    "Triangle": "AvgTriangle",
}
MAX_ARCHIVE_ENTRIES = 20_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024

mimetypes.add_type("image/webp", ".webp")


class OfflineWorkspaceError(Exception):
    """离线包或查询错误，可直接映射成 JSON API 错误。"""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _PackMap:
    pack_id: str
    path: Path
    upload: dict[str, Any]
    map_name: str
    frame: dict[str, Any]
    detail_entries_by_index: dict[int, tuple[int, str]]
    asset_entries: frozenset[str]


def _read_json(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        return json.loads(archive.read(name))
    except KeyError as error:
        raise OfflineWorkspaceError(422, "OFFLINE_FILE_MISSING", f"离线包缺少 {name}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfflineWorkspaceError(422, "OFFLINE_JSON_INVALID", f"{name} 不是有效 JSON") from error


def _safe_entry(name: object) -> str:
    value = str(name or "")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise OfflineWorkspaceError(422, "OFFLINE_PATH_INVALID", f"离线包路径不安全：{value}")
    return value


def _archive_entries(archive: zipfile.ZipFile) -> frozenset[str]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES or sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_BYTES:
        raise OfflineWorkspaceError(413, "OFFLINE_ARCHIVE_TOO_LARGE", "离线包文件数量或解压体积过大")
    names = [_safe_entry(item.filename) for item in infos if not item.is_dir()]
    if len(names) != len(set(names)):
        raise OfflineWorkspaceError(422, "OFFLINE_ARCHIVE_DUPLICATE_PATH", "离线包有重复路径")
    return frozenset(names)


class _SharedConfiguration:
    """读取现有 all 配置 ZIP，保持地图、标尺及引用各一份。"""

    def __init__(self, path: Path):
        self.path = path
        self.maps: dict[str, dict] = {}
        self.scales: dict[int, dict] = {}
        self.scale_sets: dict[int, dict] = {}
        self.bindings: dict[tuple[str, str, int], int] = {}
        self.assets: frozenset[str] = frozenset()
        self.pack_id = ""
        if not path.is_file():
            raise OfflineWorkspaceError(422, "OFFLINE_CONFIG_MISSING", f"缺少共享配置：{path}")
        try:
            with path.open("rb") as source:
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            self.pack_id = f"config-{digest.hexdigest()}"
            with zipfile.ZipFile(path) as archive:
                entries = _archive_entries(archive)
                manifest = _read_json(archive, "manifest.json")
                if (manifest.get("format") != CONFIGURATION_FORMAT
                        or manifest.get("format_version") != CONFIGURATION_VERSION
                        or manifest.get("scope") != "all"):
                    raise OfflineWorkspaceError(422, "OFFLINE_CONFIG_UNSUPPORTED", "共享配置必须是完整的 all 配置包 v1")
                for item in _read_json(archive, "metric-scales.json")["metric_scales"]:
                    scale_id = int(item["id"])
                    if scale_id in self.scales:
                        raise ValueError("指标标尺 ID 重复")
                    # 在装载时验证表达式，即使该标尺暂未被数据引用。
                    configured_scale_dto(item, 0, "")
                    self.scales[scale_id] = item
                for item in _read_json(archive, "scale-sets.json")["scale_sets"]:
                    set_id = int(item["id"])
                    if set_id in self.scale_sets:
                        raise ValueError("标尺集 ID 重复")
                    keys = set()
                    for mapping in item["items"]:
                        if mapping["scale_id"] not in self.scales or mapping["metric_key"] in keys:
                            raise ValueError("标尺集存在无效引用或重复指标")
                        keys.add(mapping["metric_key"])
                    self.scale_sets[set_id] = item
                images = set()
                for item in _read_json(archive, "maps.json")["maps"]:
                    name = item["map_name"]
                    if name in self.maps:
                        raise ValueError("地图名称重复")
                    # 配置包允许无底图地图，其行为与在线工作区一致。
                    image_entry = item["image"].get("file")
                    if image_entry:
                        image_entry = _safe_entry(image_entry)
                        if not image_entry.startswith("images/") or image_entry not in entries:
                            raise ValueError(f"地图 {name} 缺少底图")
                        images.add(image_entry)
                    for key in ("origin", "range"):
                        pair = item[key]
                        if (len(pair) != 2 or any(_number(value) is None for value in pair)
                                or (key == "range" and any(float(value) <= 0 for value in pair))):
                            raise ValueError(f"地图 {name} 坐标配置无效")
                    self.maps[name] = item
                self.assets = frozenset(images)
                for item in _read_json(archive, "map-bindings.json")["map_bindings"]:
                    if item["map_name"] not in self.maps:
                        raise ValueError("标尺绑定引用了不存在的地图")
                    for binding in item["bindings"]:
                        key = (item["map_name"], binding["platform"], binding["shading_quality"])
                        if (key in self.bindings or binding["scale_set_id"] not in self.scale_sets
                                or key[1] not in PLATFORMS or key[2] not in range(6)):
                            raise ValueError("地图标尺绑定无效或重复")
                        self.bindings[key] = binding["scale_set_id"]
        except (OSError, zipfile.BadZipFile, KeyError, TypeError, ValueError, AttributeError, ScaleExpressionError) as error:
            raise OfflineWorkspaceError(422, "OFFLINE_CONFIG_INVALID", f"共享配置无效：{error}") from error

    def map_config(self, map_name: str) -> dict | None:
        item = self.maps[map_name]
        entry = item["image"].get("file")
        if not entry:
            return None
        return {
            **{key: copy.deepcopy(item[key]) for key in (
                "id", "map_name", "origin", "range", "x_reverse", "y_reverse",
            )},
            "image_url": f"/gpm-assets/offline/{self.pack_id}/{entry}",
        }

    def heat_scales(self, map_name: str, upload: dict, frame: dict) -> dict:
        set_id = self.bindings.get((map_name, upload["platform"], upload["shading_quality"]))
        configured = {}
        if set_id is not None:
            scale_set = self.scale_sets[set_id]
            configured = {
                item["metric_key"]: configured_scale_dto(self.scales[item["scale_id"]], set_id, scale_set["name"])
                for item in scale_set["items"]
            }
        return resolve_metric_scales(frame["heat_map"], frame["points"], configured)


def _epoch(value: object) -> int:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError as error:
        raise OfflineWorkspaceError(422, "OFFLINE_TIME_INVALID", f"采集时间无效：{text}") from error


def _summary_metrics(raw: object) -> dict[str, float]:
    result = {}
    if not isinstance(raw, list):
        return result
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        field = TREND_SUMMARY_FIELDS.get(key)
        summary = item.get("summary_data")
        value = summary.get(field) if field and isinstance(summary, dict) else None
        number = _number(value)
        if number is not None:
            result[key] = number
    return result


def _quality(value: int) -> dict:
    return {"value": value, "label": QUALITY_LABELS.get(value, f"画质 {value}")}


def _synthetic_point_id(pack_id: str, source_id: object) -> int:
    digest = hashlib.blake2b(f"{pack_id}:{source_id}".encode("utf-8"), digest_size=6).digest()
    return int.from_bytes(digest, "big") or 1


def _batch_dto(upload: dict[str, Any]) -> dict[str, Any]:
    quality = int(upload["shading_quality"])
    return {
        "id": upload["id"],
        "batch_id": str(upload["batch_id"]),
        "branch_tag": str(upload["branch_tag"]),
        "batch_url": upload.get("batch_url"),
        "captured_at": str(upload["captured_at"]),
        "p4_version": int(upload["p4_version"]),
        "platform": str(upload["platform"]),
        "shading_quality": quality,
        "shading_quality_label": QUALITY_LABELS.get(quality, str(quality)),
    }


class OfflineHeatmapWorkspace:
    """把数据目录中的多个缩略图离线包呈现为在线版热力图读模型。"""

    def __init__(self, data_dir: Path | str, config_path: Path | str | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.config_path = Path(config_path).resolve() if config_path is not None else self.data_dir.parent / "config" / CONFIGURATION_FILENAME
        self._configuration: _SharedConfiguration | None = None
        self._fingerprint: tuple[tuple[str, int, int], ...] = ()
        self._maps: list[_PackMap] = []
        self._points: dict[int, tuple[_PackMap, str, int]] = {}
        self._packs: dict[str, tuple[Path, frozenset[str]]] = {}
        self.reload(force=True)

    def _snapshot(self) -> tuple[tuple[str, int, int], ...]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        paths = list(self.data_dir.rglob("*.ssheat"))
        if self.config_path.is_file():
            paths.append(self.config_path)
        return tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in sorted(paths, key=lambda item: str(item).casefold())
            if path.is_file()
        )

    def reload(self, *, force: bool = False) -> bool:
        snapshot = self._snapshot()
        if not force and snapshot == self._fingerprint:
            return False
        maps: list[_PackMap] = []
        points: dict[int, tuple[_PackMap, str, int]] = {}
        packs: dict[str, tuple[Path, frozenset[str]]] = {}
        identities: set[tuple[str, str]] = set()
        configuration = _SharedConfiguration(self.config_path) if snapshot else None
        for raw_path, _, _ in snapshot:
            path = Path(raw_path)
            if path == self.config_path:
                continue
            loaded, pack_id, entries, identity = self._load_pack(path)
            if pack_id in packs or identity in identities:
                raise OfflineWorkspaceError(
                    409, "OFFLINE_PACK_DUPLICATE",
                    f"存在重复的离线批次：{identity[0]}/{identity[1]}",
                )
            identities.add(identity)
            packs[pack_id] = (path, entries)
            for item in loaded:
                if item.map_name not in configuration.maps:
                    raise OfflineWorkspaceError(422, "OFFLINE_CONFIG_MAP_MISSING", f"共享配置缺少地图 {item.map_name}，请更新 config/{CONFIGURATION_FILENAME}")
                maps.append(item)
                for index, (point_id, entry) in item.detail_entries_by_index.items():
                    if point_id in points:
                        raise OfflineWorkspaceError(409, "OFFLINE_POINT_DUPLICATE", "离线点位 ID 冲突")
                    points[point_id] = (item, entry, index)
        self._maps = maps
        self._points = points
        self._packs = packs
        self._configuration = configuration
        self._fingerprint = snapshot
        return True

    def reload_if_changed(self) -> None:
        self.reload()

    def _load_pack(
        self, path: Path,
    ) -> tuple[list[_PackMap], str, frozenset[str], tuple[str, str]]:
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise OfflineWorkspaceError(422, "OFFLINE_ARCHIVE_INVALID", f"无法读取 {path.name}") from error
        with archive:
            entries = _archive_entries(archive)
            manifest = _read_json(archive, "manifest.json")
            if not isinstance(manifest, dict):
                raise OfflineWorkspaceError(422, "OFFLINE_MANIFEST_INVALID", "manifest.json 必须是对象")
            if manifest.get("format") != PACKAGE_FORMAT or manifest.get("format_version") != PACKAGE_VERSION:
                raise OfflineWorkspaceError(422, "OFFLINE_FORMAT_UNSUPPORTED", f"{path.name} 格式版本不受支持，请重新导出 v{PACKAGE_VERSION} 批次包")
            if int(manifest.get("min_viewer_version", 0)) > VIEWER_VERSION:
                raise OfflineWorkspaceError(422, "OFFLINE_VIEWER_TOO_OLD", f"{path.name} 需要更新离线查看器")
            if manifest.get("image_mode") != IMAGE_MODE:
                raise OfflineWorkspaceError(422, "OFFLINE_IMAGE_MODE_UNSUPPORTED", "只支持缩略图离线包")
            pack_id = str(manifest.get("pack_id") or "")
            if not pack_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in pack_id):
                raise OfflineWorkspaceError(422, "OFFLINE_PACK_ID_INVALID", "离线包 pack_id 无效")
            upload = manifest.get("upload")
            if not isinstance(upload, dict):
                raise OfflineWorkspaceError(422, "OFFLINE_MANIFEST_INVALID", "离线包缺少 upload")
            required = {"id", "batch_id", "branch_tag", "captured_at", "p4_version", "platform", "shading_quality"}
            if not required.issubset(upload):
                raise OfflineWorkspaceError(422, "OFFLINE_MANIFEST_INVALID", "离线包 upload 字段不完整")
            _epoch(upload["captured_at"])
            if upload["platform"] not in PLATFORMS or int(upload["shading_quality"]) not in range(6):
                raise OfflineWorkspaceError(422, "OFFLINE_SCOPE_INVALID", "离线包平台或画质无效")
            maps = manifest.get("maps")
            if not isinstance(maps, list) or not maps:
                raise OfflineWorkspaceError(422, "OFFLINE_MANIFEST_INVALID", "离线包没有地图数据")
            loaded = []
            for definition in maps:
                if not isinstance(definition, dict):
                    raise OfflineWorkspaceError(422, "OFFLINE_MANIFEST_INVALID", "地图清单项无效")
                frame_file = _safe_entry(definition.get("frame_file"))
                points_dir = _safe_entry(definition.get("points_dir"))
                frame = _read_json(archive, frame_file)
                map_name = str(definition.get("map_name") or "")
                if not isinstance(frame, dict) or frame.get("map", {}).get("map_name") != map_name:
                    raise OfflineWorkspaceError(422, "OFFLINE_MAP_INVALID", f"{map_name or path.name} 地图数据无效")
                detail_entries_by_index = {}
                for point in frame.get("points", []):
                    source_id = int(point["id"])
                    point_index = int(point["index"])
                    detail_entry = f"{points_dir}/{source_id}.json"
                    if detail_entry not in entries:
                        raise OfflineWorkspaceError(422, "OFFLINE_POINT_INVALID", f"{map_name} 点位详情不完整")
                    point_id = _synthetic_point_id(pack_id, source_id)
                    point["id"] = point_id
                    if point_index in detail_entries_by_index:
                        raise OfflineWorkspaceError(422, "OFFLINE_POINT_INVALID", f"{map_name} 点位序号重复")
                    detail_entries_by_index[point_index] = (point_id, detail_entry)
                asset_entries = frozenset(name for name in entries if name.startswith("assets/"))
                loaded.append(_PackMap(
                    pack_id=pack_id,
                    path=path,
                    upload=dict(upload),
                    map_name=map_name,
                    frame=frame,
                    detail_entries_by_index=detail_entries_by_index,
                    asset_entries=asset_entries,
                ))
            return loaded, pack_id, entries, (str(upload["branch_tag"]), str(upload["batch_id"]))

    @staticmethod
    def _sort_key(item: _PackMap) -> tuple[int, int, int, str]:
        return (
            int(item.upload["p4_version"]),
            _epoch(item.upload["captured_at"]),
            int(item.upload["id"]),
            item.pack_id,
        )

    @staticmethod
    def _report_key(item: _PackMap) -> tuple[int, str]:
        return int(item.upload["id"]), item.pack_id

    def catalog(self, branch_tag: str = "main") -> dict[str, Any]:
        branches = sorted({str(item.upload["branch_tag"]) for item in self._maps} | {"main"})
        scoped = [item for item in self._maps if item.upload["branch_tag"] == branch_tag]
        grouped: dict[str, list[_PackMap]] = {}
        for item in scoped:
            grouped.setdefault(item.map_name, []).append(item)
        result = []
        for map_name, items in grouped.items():
            platforms = sorted({str(item.upload["platform"]) for item in items})
            scopes = []
            for platform in platforms:
                qualities = sorted({
                    int(item.upload["shading_quality"])
                    for item in items if item.upload["platform"] == platform
                }, reverse=True)
                scopes.append({"platform": platform, "shading_qualities": [_quality(value) for value in qualities]})
            qualities = sorted({int(item.upload["shading_quality"]) for item in items}, reverse=True)
            latest = max(items, key=lambda item: (
                _epoch(item.upload["captured_at"]), int(item.upload["id"]), item.pack_id,
            ))
            map_id = self._configuration.maps[map_name]["id"]
            result.append({
                "id": map_id,
                "value": map_name,
                "has_data": True,
                "batch_count": len(items),
                "point_count": sum(len(item.frame.get("points", [])) for item in items),
                "latest_at": latest.upload["captured_at"],
                "platforms": platforms,
                "shading_qualities": [_quality(value) for value in qualities],
                "platform_qualities": scopes,
            })
        result.sort(key=lambda item: (
            item["id"] is None,
            int(item["id"]) if item["id"] is not None else 2**31,
            item["value"].casefold(),
        ))
        return {
            "branch_tag": branch_tag,
            "branch_tags": branches,
            "platforms": sorted({str(item.upload["platform"]) for item in scoped}),
            "shading_qualities": [_quality(value) for value in range(5, -1, -1)],
            "maps": result,
        }

    def _scope(self, map_name: str, branch_tag: str, platform: str | None, quality: int | None) -> list[_PackMap]:
        return [
            item for item in self._maps
            if item.map_name == map_name
            and item.upload["branch_tag"] == branch_tag
            and (not platform or item.upload["platform"] == platform)
            and (quality is None or int(item.upload["shading_quality"]) == quality)
        ]

    def frame(
        self,
        map_name: str,
        branch_tag: str = "main",
        platform: str | None = None,
        shading_quality: int | None = None,
        batch_id: str | None = None,
        nearest_p4_version: int | None = None,
        preferred_p4_version: int | None = None,
    ) -> dict[str, Any]:
        batches = sorted(self._scope(map_name, branch_tag, platform, shading_quality), key=self._sort_key, reverse=True)
        if not batches:
            raise OfflineWorkspaceError(404, "GPM_MAP_DATA_NOT_FOUND", "当前筛选下没有热力图数据")
        selected = next((item for item in batches if str(item.upload["batch_id"]) == str(batch_id)), None) if batch_id else None
        if batch_id and selected is None:
            raise OfflineWorkspaceError(404, "GPM_BATCH_NOT_FOUND", "当前筛选下找不到指定采集批次")
        if selected is None and nearest_p4_version is not None:
            selected = min(batches, key=lambda item: (
                abs(int(item.upload["p4_version"]) - nearest_p4_version),
                -int(item.upload["p4_version"]),
            ))
        if selected is None and preferred_p4_version is not None:
            selected = next((item for item in batches if int(item.upload["p4_version"]) == preferred_p4_version), None)
        if selected is None:
            latest_platform_p4 = max(
                (int(item.upload["p4_version"]) for item in self._maps
                 if item.upload["branch_tag"] == branch_tag
                 and (platform is None or item.upload["platform"] == platform)),
                default=None,
            )
            selected = next((item for item in batches if int(item.upload["p4_version"]) == latest_platform_p4), batches[0])
        comparison = sorted([
            item for item in batches
            if item.upload["platform"] == selected.upload["platform"]
            and int(item.upload["shading_quality"]) == int(selected.upload["shading_quality"])
        ], key=self._report_key, reverse=True)
        selected_index = comparison.index(selected)
        previous = comparison[selected_index + 1] if selected_index + 1 < len(comparison) else None
        previous_metrics = {
            int(point["index"]): point.get("heat_map_data", {})
            for point in (previous.frame.get("points", []) if previous else [])
        }
        result = copy.deepcopy(selected.frame)
        result["map_config"] = self._configuration.map_config(map_name)
        scales = self._configuration.heat_scales(map_name, selected.upload, result)
        for metric in result["heat_map"]:
            metric["scale"] = scales.get(metric.get("key"))
        result["batch"] = _batch_dto(selected.upload)
        result["previous_batch"] = _batch_dto(previous.upload) if previous else None
        result["available_batches"] = [_batch_dto(item.upload) for item in batches]
        result["latest_p4_version"] = max(
            (int(item.upload["p4_version"]) for item in self._maps
             if item.upload["branch_tag"] == branch_tag
             and item.upload["platform"] == selected.upload["platform"]),
            default=int(selected.upload["p4_version"]),
        )
        for point in result.get("points", []):
            point["metric_change_percent"] = _changes(
                point.get("heat_map_data", {}), previous_metrics.get(int(point["index"])),
            )
        return result

    def point(self, point_id: int) -> dict[str, Any]:
        found = self._points.get(point_id)
        if not found:
            raise OfflineWorkspaceError(404, "GPM_POINT_NOT_FOUND", "点位不存在")
        item, entry, _ = found
        with zipfile.ZipFile(item.path) as archive:
            detail = _read_json(archive, entry)
        if not isinstance(detail, dict):
            raise OfflineWorkspaceError(422, "OFFLINE_POINT_INVALID", "离线点位详情无效")
        detail["id"] = point_id
        return detail

    @staticmethod
    def _trend_range(items: list[_PackMap], days: int) -> list[_PackMap]:
        if days not in TREND_DAYS:
            raise OfflineWorkspaceError(422, "INVALID_GPM_TREND_DAYS", "趋势范围仅支持 7、14、30 天")
        latest = max(_epoch(item.upload["captured_at"]) for item in items)
        start = latest - (days - 1) * 86400
        return sorted(
            (item for item in items if _epoch(item.upload["captured_at"]) >= start),
            key=lambda item: (_epoch(item.upload["captured_at"]), int(item.upload["id"]), item.pack_id),
        )

    def map_trends(self, map_name: str, branch_tag: str, platform: str, quality: int, days: int) -> dict[str, Any]:
        items = self._scope(map_name, branch_tag, platform, quality)
        if not items:
            raise OfflineWorkspaceError(404, "GPM_MAP_DATA_NOT_FOUND", "当前筛选下没有热力图数据")
        points = [{
            "batch_id": item.upload["batch_id"],
            "captured_at": item.upload["captured_at"],
            "p4_version": item.upload["p4_version"],
            "metrics": _summary_metrics(item.frame.get("trend")),
        } for item in self._trend_range(items, days)]
        return {"available": any(point["metrics"] for point in points), "reason": None, "days": days, "points": points}

    def point_trends(self, point_id: int, days: int) -> dict[str, Any]:
        found = self._points.get(point_id)
        if not found:
            raise OfflineWorkspaceError(404, "GPM_POINT_NOT_FOUND", "点位不存在")
        current_map, _, index = found
        items = self._scope(
            current_map.map_name,
            str(current_map.upload["branch_tag"]),
            str(current_map.upload["platform"]),
            int(current_map.upload["shading_quality"]),
        )
        result = []
        for item in self._trend_range(items, days):
            identity = item.detail_entries_by_index.get(index)
            if identity:
                _, entry = identity
                with zipfile.ZipFile(item.path) as archive:
                    detail = _read_json(archive, entry)
                if not isinstance(detail, dict):
                    raise OfflineWorkspaceError(422, "OFFLINE_POINT_INVALID", "离线点位详情无效")
                result.append({
                    "batch_id": item.upload["batch_id"],
                    "captured_at": item.upload["captured_at"],
                    "p4_version": item.upload["p4_version"],
                    "metrics": copy.deepcopy(detail.get("trend_data", {})),
                })
        return {"available": True, "reason": None, "days": days, "points": result}

    def asset(self, pack_id: str, entry: str) -> tuple[bytes, str]:
        entry = _safe_entry(entry)
        configuration = self._configuration
        if configuration and pack_id == configuration.pack_id and entry in configuration.assets:
            path = configuration.path
        else:
            found = self._packs.get(pack_id)
            path = found[0] if found and entry.startswith("assets/") and entry in found[1] else None
        if path is None:
            raise OfflineWorkspaceError(404, "GPM_ASSET_NOT_FOUND", "离线热力图资源不存在")
        with zipfile.ZipFile(path) as archive:
            content = archive.read(entry)
        content_type = mimetypes.guess_type(entry)[0] or "application/octet-stream"
        return content, content_type

    def entry_path(self) -> str:
        catalog = self.catalog()
        maps = catalog["maps"]
        if not maps:
            return "/gpm-heatmap"
        return f"/gpm-heatmap/{maps[0]['value']}"
