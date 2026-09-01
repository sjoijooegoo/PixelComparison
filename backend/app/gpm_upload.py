"""GPMHeatmap 报告校验、截图解包与原子覆盖上传。"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from PIL import Image, UnidentifiedImageError

from .gpm_common import (
    IMAGE_SUFFIXES, http_error, require_identifier, require_platform, safe_segment,
)
from .gpm_map_config import ensure_map_definitions
from .gpm_storage import connect_gpm_database, gpm_assets_dir
from .gpm_retention import (
    GPM_DATA_RETENTION_DAYS,
    is_expired_capture,
    prune_expired_gpm_uploads,
)


router = APIRouter()

MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_POINT_COUNT = 5_000
MAX_ARCHIVE_FILES = MAX_POINT_COUNT
MAX_ARCHIVE_UNPACKED_BYTES = 4 * 1024 * 1024 * 1024
MAX_SCREENSHOT_PIXELS = 40_000_000
MAX_JSON_DEPTH = 32


def _validate_json_depth(value: object, label: str) -> None:
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise http_error(422, "GPM_JSON_TOO_DEEP", f"{label} 嵌套不能超过 {MAX_JSON_DEPTH} 层")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise http_error(422, "INVALID_GPM_REPORT", f"{label} 必须是数组")
    _validate_json_depth(value, label)
    return value


def _require_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise http_error(422, "INVALID_GPM_REPORT", f"{label} 必须是对象")
    _validate_json_depth(value, label)
    return value


def _validate_metric_list(value: object, label: str) -> list[dict]:
    items = _require_list(value, label)
    keys: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise http_error(422, "INVALID_GPM_REPORT", f"{label}[{index}] 必须是对象")
        key = str(item.get("key") or "").strip()
        if not key or len(key) > 200 or any(ord(character) < 32 for character in key):
            raise http_error(422, "INVALID_GPM_METRIC_KEY", f"{label}[{index}].key 无效")
        if key in keys:
            raise http_error(422, "DUPLICATE_GPM_METRIC_KEY", f"{label} 存在重复 Key: {key}")
        keys.add(key)
    return items


def _parse_iso_datetime(value: str) -> tuple[str, int]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise http_error(422, "INVALID_CAPTURED_AT", "captured_at 必须是 ISO 8601 时间")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise http_error(422, "INVALID_CAPTURED_AT", "captured_at 必须包含时区")
    return parsed.isoformat(timespec="seconds"), int(parsed.timestamp())


def _validate_report(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise http_error(422, "INVALID_GPM_REPORT", "GPMHeatmap.json 必须包含 data 数组")
    maps = payload["data"]
    if not maps:
        raise http_error(422, "EMPTY_GPM_REPORT", "GPMHeatmap.json 没有地图数据")
    point_count = sum(
        len(item.get("detail", []))
        for item in maps
        if isinstance(item, dict) and isinstance(item.get("detail"), list)
    )
    if point_count > MAX_POINT_COUNT:
        raise http_error(
            413,
            "TOO_MANY_GPM_POINTS",
            f"单次上报点位数不能超过 {MAX_POINT_COUNT}",
        )
    map_names: set[str] = set()
    all_screenshot_ids: set[str] = set()
    for map_item in maps:
        if not isinstance(map_item, dict):
            raise http_error(422, "INVALID_GPM_MAP", "data 中的地图必须是对象")
        canonical_name = map_item.get("map_name")
        legacy_name = map_item.get("pic_name")
        if canonical_name is not None and legacy_name is not None:
            canonical_name = require_identifier(canonical_name, "map_name")
            legacy_name = require_identifier(legacy_name, "pic_name")
            if canonical_name != legacy_name:
                raise http_error(
                    422,
                    "GPM_MAP_NAME_CONFLICT",
                    "map_name 与 pic_name 同时存在时必须一致",
                )
        map_name = require_identifier(
            canonical_name if canonical_name is not None else legacy_name,
            "map_name",
        )
        map_item["map_name"] = map_name
        details = map_item.get("detail")
        if not isinstance(details, list):
            raise http_error(422, "INVALID_GPM_MAP", "每个地图必须包含 map_name 和 detail 数组")
        if map_name in map_names:
            raise http_error(422, "DUPLICATE_GPM_MAP", f"地图重复: {map_name}")
        map_names.add(map_name)
        _validate_metric_list(map_item.get("heat_map", []), f"{map_name}.heat_map")
        _validate_metric_list(map_item.get("trend", []), f"{map_name}.trend")
        show_direction = map_item.get("show_direction", True)
        if not isinstance(show_direction, bool) and show_direction not in (0, 1):
            raise http_error(422, "INVALID_GPM_MAP", f"{map_name}.show_direction 必须是布尔值或 0/1")
        map_item["show_direction"] = bool(show_direction)
        indices: set[int] = set()
        screenshot_ids: set[str] = set()
        for point in details:
            if not isinstance(point, dict):
                raise http_error(422, "INVALID_GPM_POINT", f"{map_name} 存在无效点位")
            try:
                index = point["index"]
                screenshot_id = require_identifier(point["screenshot_id"], "screenshot_id")
                position = point["position"]
                direction = point["direction"]
            except (KeyError, TypeError, ValueError):
                raise http_error(422, "INVALID_GPM_POINT", f"{map_name} 点位缺少必要字段")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise http_error(422, "INVALID_GPM_POINT", f"{map_name} 点位 index 必须是非负整数")
            if (
                not screenshot_id.isascii()
                or not screenshot_id.isdigit()
                or int(screenshot_id) != index
            ):
                raise http_error(
                    422,
                    "GPM_POINT_SCREENSHOT_ID_MISMATCH",
                    f"{map_name} 点位 {index} 的 screenshot_id 必须对应同一个点位序号",
                )
            _require_object(point.get("heat_map_data"), f"{map_name} 点位 {index}.heat_map_data")
            _require_object(point.get("trend_data"), f"{map_name} 点位 {index}.trend_data")
            _require_list(point.get("detail_data"), f"{map_name} 点位 {index}.detail_data")
            normalized_screenshot_id = screenshot_id.casefold()
            if index in indices or normalized_screenshot_id in screenshot_ids:
                raise http_error(422, "DUPLICATE_GPM_POINT", f"{map_name} 点位或截图 ID 重复")
            if normalized_screenshot_id in all_screenshot_ids:
                raise http_error(
                    422, "DUPLICATE_GPM_SCREENSHOT_ID",
                    f"跨地图 screenshot_id 必须唯一，重复值: {screenshot_id}",
                )
            if not isinstance(position, list) or len(position) < 2:
                raise http_error(422, "INVALID_GPM_POSITION", f"{map_name} 点位 {index} 坐标无效")
            if not isinstance(direction, list) or len(direction) < 2:
                raise http_error(422, "INVALID_GPM_DIRECTION", f"{map_name} 点位 {index} 方向无效")
            for values, code, label in (
                (position, "INVALID_GPM_POSITION", "坐标"),
                (direction, "INVALID_GPM_DIRECTION", "方向"),
            ):
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in values[:2]
                ):
                    raise http_error(422, code, f"{map_name} 点位 {index} {label}必须是有限数字")
            indices.add(index)
            screenshot_ids.add(normalized_screenshot_id)
            all_screenshot_ids.add(normalized_screenshot_id)
    return maps


def _parse_pipeline_data(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise http_error(422, "INVALID_PIPELINE_DATA", "pipeline_data 必须是 JSON 对象")
    if not isinstance(parsed, dict):
        raise http_error(422, "INVALID_PIPELINE_DATA", "pipeline_data 必须是 JSON 对象")
    return parsed


def _report_scope_value(maps: list[dict], key: str) -> object:
    present = [key in map_item and map_item.get(key) is not None for map_item in maps]
    if not all(present):
        raise http_error(422, "INCONSISTENT_GPM_SCOPE", f"所有地图必须提供 {key}")
    values = [map_item.get(key) for map_item in maps if map_item.get(key) is not None]
    reference = values[0]
    if any(type(value) is not type(reference) or value != reference for value in values[1:]):
        raise http_error(422, "INCONSISTENT_GPM_SCOPE", f"所有地图的 {key} 必须一致")
    return reference


def _archive_images(archive_path: Path) -> dict[str, zipfile.ZipInfo]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile:
        raise http_error(422, "INVALID_SCREENSHOT_ARCHIVE", "GPMScreenshot.zip 不是有效 ZIP")
    with archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if len(infos) > MAX_ARCHIVE_FILES:
            raise http_error(413, "TOO_MANY_SCREENSHOTS", "截图文件数量超过限制")
        if sum(item.file_size for item in infos) > MAX_ARCHIVE_UNPACKED_BYTES:
            raise http_error(413, "SCREENSHOTS_TOO_LARGE", "截图解压后体积超过限制")
        images: dict[str, zipfile.ZipInfo] = {}
        normalized_ids: set[str] = set()
        for item in infos:
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise http_error(422, "UNSAFE_SCREENSHOT_PATH", "截图压缩包包含不安全路径")
            if ((item.external_attr >> 16) & 0o170000) == 0o120000:
                raise http_error(422, "UNSAFE_SCREENSHOT_PATH", "截图压缩包不能包含符号链接")
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            screenshot_id = path.stem
            normalized_screenshot_id = screenshot_id.casefold()
            if normalized_screenshot_id in normalized_ids:
                raise http_error(422, "DUPLICATE_SCREENSHOT", f"截图 ID 重复: {screenshot_id}")
            images[screenshot_id] = item
            normalized_ids.add(normalized_screenshot_id)
        return images


def _create_thumbnail(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
            if image.width * image.height > MAX_SCREENSHOT_PIXELS:
                raise http_error(
                    413,
                    "SCREENSHOT_PIXEL_LIMIT_EXCEEDED",
                    f"截图 {source.name} 像素数超过限制",
                )
            image = image.convert("RGB")
            image.thumbnail((480, 270), Image.Resampling.LANCZOS)
            image.save(target, "WEBP", quality=78, method=4)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise http_error(422, "INVALID_SCREENSHOT", f"无法解析截图 {source.name}: {exc}")


def _insert_upload_graph(
    connection: sqlite3.Connection,
    *,
    maps: list[dict],
    image_entries: dict[str, zipfile.ZipInfo],
    relative_root: PurePosixPath,
    batch_id: str,
    branch_tag: str,
    batch_url: str | None,
    captured_at: str,
    captured_at_epoch: int,
    p4_version: int,
    platform: str,
    shading_quality: int,
    source_sha256: str,
) -> int:
    ensure_map_definitions(connection, (str(item["map_name"]) for item in maps))
    cursor = connection.execute(
        """
        INSERT INTO gpm_uploads (
            batch_id, branch_tag, batch_url, captured_at, captured_at_epoch, p4_version,
            platform, shading_quality, source_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id, branch_tag, batch_url, captured_at, captured_at_epoch, p4_version,
            platform, shading_quality, source_sha256,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    upload_id = int(cursor.lastrowid)
    for map_item in maps:
        map_cursor = connection.execute(
            """
            INSERT INTO gpm_upload_maps (
                upload_id, map_name, show_direction, heat_map_json, trend_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                upload_id, str(map_item["map_name"]), int(bool(map_item.get("show_direction", 1))),
                json.dumps(map_item.get("heat_map", []), ensure_ascii=False),
                json.dumps(map_item.get("trend", []), ensure_ascii=False),
            ),
        )
        upload_map_id = int(map_cursor.lastrowid)
        point_rows = []
        for point in map_item["detail"]:
            screenshot_id = str(point["screenshot_id"])
            info = image_entries[screenshot_id]
            safe_id = safe_segment(screenshot_id, "point")
            original = relative_root / "originals" / f"{safe_id}{PurePosixPath(info.filename).suffix.lower()}"
            thumb = relative_root / "thumbs" / f"{safe_id}.webp"
            point_rows.append((
                upload_map_id, int(point["index"]), screenshot_id,
                float(point["position"][0]), float(point["position"][1]),
                float(point["direction"][0]), float(point["direction"][1]),
                json.dumps(point["heat_map_data"], ensure_ascii=False),
                json.dumps(point["trend_data"], ensure_ascii=False),
                json.dumps(point["detail_data"], ensure_ascii=False),
                original.as_posix(), thumb.as_posix(),
            ))
        connection.executemany(
            """
            INSERT INTO gpm_points (
                upload_map_id, point_index, screenshot_id,
                position_x, position_y, direction_x, direction_y,
                heat_map_data_json, trend_data_json, detail_data_json,
                screenshot_path, thumbnail_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            point_rows,
        )
    return upload_id


def _remove_replaced_asset_dirs(relative_dirs: set[PurePosixPath], batch_root: Path) -> None:
    assets = gpm_assets_dir().resolve()
    batch_root = batch_root.resolve()
    for relative in sorted(relative_dirs, key=lambda item: len(item.parts), reverse=True):
        target = (assets / Path(*relative.parts)).resolve()
        if target == batch_root or batch_root not in target.parents:
            continue
        shutil.rmtree(target, ignore_errors=True)
        parent = target.parent
        while parent != batch_root and batch_root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


@router.post("/api/gpm-heatmaps/uploads", status_code=201)
def upload_gpm_heatmap(
    report: Annotated[UploadFile, File(description="GPMHeatmap.json")],
    screenshots: Annotated[UploadFile, File(description="GPMScreenshot.zip")],
    pipeline_data: Annotated[str, Form(description="流水线元数据 JSON")],
    overwrite: Annotated[bool, Form()] = False,
):
    report_bytes = report.file.read(MAX_REPORT_BYTES + 1)
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise http_error(413, "REPORT_TOO_LARGE", "GPMHeatmap.json 超过 64 MiB")
    try:
        payload = json.loads(report_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise http_error(422, "INVALID_GPM_JSON", "GPMHeatmap.json 无法解析")
    maps = _validate_report(payload)

    pipeline = _parse_pipeline_data(pipeline_data)
    batch_id = require_identifier(
        str(pipeline.get("batch_id") or ""),
        "batch_id", maximum=120,
    )
    branch_tag = require_identifier(
        str(pipeline.get("branch_tag") or "main").strip().lower(), "branch_tag", maximum=120,
    )
    captured_at, captured_at_epoch = _parse_iso_datetime(str(pipeline.get("captured_at") or ""))
    if is_expired_capture(captured_at):
        raise http_error(
            422,
            "GPM_CAPTURE_EXPIRED",
            f"captured_at 已超出最近 {GPM_DATA_RETENTION_DAYS} 天保留范围，拒绝上报",
        )
    batch_url = pipeline.get("batch_url")
    if batch_url is not None:
        batch_url = str(batch_url).strip() or None
        if batch_url and len(batch_url) > 2048:
            raise http_error(422, "INVALID_BATCH_URL", "batch_url 不能超过 2048 个字符")

    platform = require_platform(_report_scope_value(maps, "platform"))
    raw_quality = _report_scope_value(maps, "shading_quality")
    if isinstance(raw_quality, bool) or not isinstance(raw_quality, int):
        raise http_error(422, "INVALID_SHADING_QUALITY", "shading_quality 必须在 0 到 5 之间")
    shading_quality = raw_quality
    if not 0 <= shading_quality <= 5:
        raise http_error(422, "INVALID_SHADING_QUALITY", "shading_quality 必须在 0 到 5 之间")
    raw_p4 = _report_scope_value(maps, "p4_version")
    if isinstance(raw_p4, bool) or not isinstance(raw_p4, int):
        raise http_error(422, "INVALID_P4_VERSION", "p4_version 必须是非负整数")
    p4_version = raw_p4
    if p4_version < 0:
        raise http_error(422, "INVALID_P4_VERSION", "p4_version 不能为负数")

    if not overwrite:
        connection = connect_gpm_database()
        try:
            existing = connection.execute(
                "SELECT branch_tag FROM gpm_uploads WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        finally:
            connection.close()
        if existing:
            if existing["branch_tag"] != branch_tag:
                raise http_error(
                    409, "GPM_BATCH_BRANCH_IMMUTABLE",
                    "GPM 批次号在模块内全局唯一，不能在其他分支重复使用",
                )
            raise http_error(409, "GPM_BATCH_EXISTS", "GPM 批次已存在；覆盖请传 overwrite=true")

    staging_root = gpm_assets_dir() / ".staging" / uuid.uuid4().hex
    staging_root.mkdir(parents=True, exist_ok=False)
    archive_path = staging_root / "screenshots.zip"
    try:
        with archive_path.open("wb") as target:
            copied = 0
            while chunk := screenshots.file.read(1024 * 1024):
                copied += len(chunk)
                if copied > MAX_ARCHIVE_BYTES:
                    raise http_error(413, "ARCHIVE_TOO_LARGE", "GPMScreenshot.zip 超过限制")
                target.write(chunk)
        image_entries = _archive_images(archive_path)
        expected_ids = {
            str(point["screenshot_id"])
            for map_item in maps
            for point in map_item["detail"]
        }
        missing = sorted(expected_ids - set(image_entries))
        extras = sorted(set(image_entries) - expected_ids)
        if missing or extras:
            raise http_error(
                422, "SCREENSHOT_SET_MISMATCH",
                f"截图与点位不匹配，缺少 {missing[:8]}，多出 {extras[:8]}",
            )

        extracted = staging_root / "payload"
        original_dir = extracted / "originals"
        thumb_dir = extracted / "thumbs"
        original_dir.mkdir(parents=True)
        with zipfile.ZipFile(archive_path) as archive:
            for screenshot_id, info in image_entries.items():
                suffix = PurePosixPath(info.filename).suffix.lower()
                destination = original_dir / f"{safe_segment(screenshot_id, 'point')}{suffix}"
                with archive.open(info) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                _create_thumbnail(destination, thumb_dir / f"{safe_segment(screenshot_id, 'point')}.webp")

        batch_relative_root = (
            PurePosixPath("uploads")
            / safe_segment(branch_tag, "main")
            / safe_segment(batch_id, "batch")
        )
        relative_root = batch_relative_root / uuid.uuid4().hex
        final_root = gpm_assets_dir() / Path(*relative_root.parts)
        batch_root = gpm_assets_dir() / Path(*batch_relative_root.parts)
        connection = connect_gpm_database()
        published_new = False
        old_asset_dirs: set[PurePosixPath] = set()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id, branch_tag FROM gpm_uploads WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if existing and existing["branch_tag"] != branch_tag:
                raise http_error(
                    409, "GPM_BATCH_BRANCH_IMMUTABLE",
                    "GPM 批次号在模块内全局唯一，覆盖不能改变所属分支",
                )
            if existing and not overwrite:
                raise http_error(409, "GPM_BATCH_EXISTS", "GPM 批次已存在；覆盖请传 overwrite=true")
            if existing:
                old_paths = connection.execute(
                    """
                    SELECT p.screenshot_path, p.thumbnail_path
                    FROM gpm_points p
                    JOIN gpm_upload_maps m ON m.id = p.upload_map_id
                    WHERE m.upload_id = ?
                    """,
                    (existing["id"],),
                ).fetchall()
                for row in old_paths:
                    for key in ("screenshot_path", "thumbnail_path"):
                        if row[key]:
                            old_asset_dirs.add(PurePosixPath(row[key]).parent)
                connection.execute("DELETE FROM gpm_uploads WHERE id = ?", (existing["id"],))

            final_root.parent.mkdir(parents=True, exist_ok=True)
            extracted.rename(final_root)
            published_new = True
            upload_id = _insert_upload_graph(
                connection,
                maps=maps,
                image_entries=image_entries,
                relative_root=relative_root,
                batch_id=batch_id,
                branch_tag=branch_tag,
                batch_url=batch_url,
                captured_at=captured_at,
                captured_at_epoch=captured_at_epoch,
                p4_version=p4_version,
                platform=platform,
                shading_quality=shading_quality,
                source_sha256=hashlib.sha256(report_bytes).hexdigest(),
            )
            connection.commit()
            _remove_replaced_asset_dirs(old_asset_dirs, batch_root)
            try:
                # 本次写入已经提交；保留清理失败只记录并由小时任务重试，不能把
                # 已成功的流水线上报伪装成失败。
                prune_expired_gpm_uploads()
            except Exception:  # noqa: BLE001
                logging.getLogger("pixelcomp").exception(
                    "GPMHeatmap 上报成功，但过期数据清理失败，稍后自动重试"
                )
            return {
                "id": upload_id,
                "batch_id": batch_id,
                "branch_tag": branch_tag,
                "map_count": len(maps),
                "point_count": sum(len(map_item["detail"]) for map_item in maps),
                "updated": existing is not None,
            }
        except Exception:
            connection.rollback()
            if published_new:
                shutil.rmtree(final_root, ignore_errors=True)
            raise
        finally:
            connection.close()
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
