"""GPMHeatmap 报告校验、截图解包与原子覆盖上传。"""

from __future__ import annotations

import hashlib
import json
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
from .gpm_storage import connect_gpm_database, gpm_assets_dir


router = APIRouter()

MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_UNPACKED_BYTES = 16 * 1024 * 1024 * 1024


def _parse_iso_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise http_error(422, "INVALID_CAPTURED_AT", "captured_at 必须是 ISO 8601 时间")
    return parsed.isoformat(timespec="seconds")


def _validate_report(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise http_error(422, "INVALID_GPM_REPORT", "GPMHeatmap.json 必须包含 data 数组")
    scenes = payload["data"]
    if not scenes:
        raise http_error(422, "EMPTY_GPM_REPORT", "GPMHeatmap.json 没有场景数据")
    scene_ids: set[str] = set()
    all_screenshot_ids: set[str] = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise http_error(422, "INVALID_GPM_SCENE", "data 中的场景必须是对象")
        scene_id = require_identifier(scene.get("pic_name"), "pic_name")
        map_name = require_identifier(scene.get("map_name") or scene_id, "map_name")
        scene["map_name"] = map_name
        details = scene.get("detail")
        if not scene_id or not isinstance(details, list):
            raise http_error(422, "INVALID_GPM_SCENE", "每个场景必须包含 pic_name 和 detail 数组")
        if scene_id in scene_ids:
            raise http_error(422, "DUPLICATE_GPM_SCENE", f"场景重复: {scene_id}")
        scene_ids.add(scene_id)
        indices: set[int] = set()
        screenshot_ids: set[str] = set()
        point_keys: set[str] = set()
        for point in details:
            if not isinstance(point, dict):
                raise http_error(422, "INVALID_GPM_POINT", f"{scene_id} 存在无效点位")
            try:
                index = int(point["index"])
                screenshot_id = require_identifier(point["screenshot_id"], "screenshot_id")
                position = point["position"]
                direction = point["direction"]
            except (KeyError, TypeError, ValueError):
                raise http_error(422, "INVALID_GPM_POINT", f"{scene_id} 点位缺少必要字段")
            normalized_screenshot_id = screenshot_id.casefold()
            if index in indices or normalized_screenshot_id in screenshot_ids:
                raise http_error(422, "DUPLICATE_GPM_POINT", f"{scene_id} 点位或截图 ID 重复")
            if normalized_screenshot_id in all_screenshot_ids:
                raise http_error(
                    422, "DUPLICATE_GPM_SCREENSHOT_ID",
                    f"跨场景 screenshot_id 必须唯一，重复值: {screenshot_id}",
                )
            if not isinstance(position, list) or len(position) < 2:
                raise http_error(422, "INVALID_GPM_POSITION", f"{scene_id} 点位 {index} 坐标无效")
            if not isinstance(direction, list) or len(direction) < 2:
                raise http_error(422, "INVALID_GPM_DIRECTION", f"{scene_id} 点位 {index} 方向无效")
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
                    raise http_error(422, code, f"{scene_id} 点位 {index} {label}必须是有限数字")
            raw_point_key = point.get("point_key") or point.get("teleport_point_id")
            if raw_point_key is not None:
                point_key = str(raw_point_key).strip()
                if not point_key or len(point_key) > 200:
                    raise http_error(422, "INVALID_GPM_POINT_KEY", f"{scene_id} 点位 {index} 的 point_key 无效")
                if point_key in point_keys:
                    raise http_error(422, "DUPLICATE_GPM_POINT_KEY", f"{scene_id} point_key 重复: {point_key}")
                point["point_key"] = point_key
                point_keys.add(point_key)
            indices.add(index)
            screenshot_ids.add(normalized_screenshot_id)
            all_screenshot_ids.add(normalized_screenshot_id)
    return scenes


def _parse_pipeline_data(raw: str | None) -> dict:
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise http_error(422, "INVALID_PIPELINE_DATA", "pipeline_data 必须是 JSON 对象")
    if not isinstance(parsed, dict):
        raise http_error(422, "INVALID_PIPELINE_DATA", "pipeline_data 必须是 JSON 对象")
    return parsed


def _metadata_value(canonical: object, legacy: object, field: str, *, required: bool = False):
    """优先使用规范字段，并拒绝两套入口给出互相矛盾的值。"""

    has_canonical = canonical is not None and canonical != ""
    has_legacy = legacy is not None and legacy != ""
    if has_canonical and has_legacy and str(canonical) != str(legacy):
        raise http_error(422, "CONFLICTING_UPLOAD_METADATA", f"{field} 在规范字段和兼容字段中不一致")
    value = canonical if has_canonical else legacy
    if required and (value is None or value == ""):
        raise http_error(422, "INVALID_UPLOAD_METADATA", f"{field} 不能为空")
    return value


def _report_scope_value(scenes: list[dict], key: str) -> object | None:
    present = [key in scene and scene.get(key) is not None for scene in scenes]
    if any(present) and not all(present):
        raise http_error(
            422, "INCONSISTENT_GPM_SCOPE",
            f"所有场景必须同时提供 {key}，或全部通过兼容表单字段提供",
        )
    values = [scene.get(key) for scene in scenes if scene.get(key) is not None]
    if not values:
        return None
    normalized = {str(value).strip() for value in values}
    if len(normalized) != 1:
        raise http_error(422, "INCONSISTENT_GPM_SCOPE", f"所有场景的 {key} 必须一致")
    return values[0]


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
            image = image.convert("RGB")
            image.thumbnail((480, 270), Image.Resampling.LANCZOS)
            image.save(target, "WEBP", quality=78, method=4)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise http_error(422, "INVALID_SCREENSHOT", f"无法解析截图 {source.name}: {exc}")


def _insert_upload_graph(
    connection: sqlite3.Connection,
    *,
    scenes: list[dict],
    image_entries: dict[str, zipfile.ZipInfo],
    relative_root: PurePosixPath,
    batch_id: str,
    branch_tag: str,
    batch_url: str | None,
    captured_at: str,
    p4_version: int | None,
    platform: str,
    shading_quality: int,
    source_sha256: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO gpm_uploads (
            batch_id, branch_tag, batch_url, captured_at, p4_version,
            platform, shading_quality, source_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id, branch_tag, batch_url, captured_at, p4_version,
            platform, shading_quality, source_sha256,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    upload_id = int(cursor.lastrowid)
    for scene in scenes:
        scene_cursor = connection.execute(
            """
            INSERT INTO gpm_scenes (
                upload_id, scene_id, map_name, pic_id, show_z, show_direction,
                x_reverse, y_reverse, heat_map_json, trend_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                upload_id, str(scene["pic_name"]), str(scene["map_name"]), scene.get("pic_id"),
                int(bool(scene.get("show_z", 0))), int(bool(scene.get("show_direction", 1))),
                int(bool(scene.get("x_reverse", 0))), int(bool(scene.get("y_reverse", 1))),
                json.dumps(scene.get("heat_map", []), ensure_ascii=False),
                json.dumps(scene.get("trend", []), ensure_ascii=False),
            ),
        )
        scene_row_id = int(scene_cursor.lastrowid)
        for point in scene["detail"]:
            screenshot_id = str(point["screenshot_id"])
            info = image_entries[screenshot_id]
            safe_id = safe_segment(screenshot_id, "point")
            original = relative_root / "originals" / f"{safe_id}{PurePosixPath(info.filename).suffix.lower()}"
            thumb = relative_root / "thumbs" / f"{safe_id}.webp"
            point_key = point.get("point_key") or point.get("teleport_point_id")
            connection.execute(
                """
                INSERT INTO gpm_points (
                    scene_row_id, point_index, screenshot_id, point_key,
                    position_json, direction_json, view_json,
                    heat_map_data_json, trend_data_json, detail_data_json,
                    screenshot_path, thumbnail_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scene_row_id, int(point["index"]), screenshot_id,
                    str(point_key) if point_key is not None else None,
                    json.dumps(point["position"], ensure_ascii=False),
                    json.dumps(point["direction"], ensure_ascii=False),
                    json.dumps(point.get("view", {}), ensure_ascii=False),
                    json.dumps(point.get("heat_map_data", {}), ensure_ascii=False),
                    json.dumps(point.get("trend_data", {}), ensure_ascii=False),
                    json.dumps(point.get("detail_data", []), ensure_ascii=False),
                    original.as_posix(), thumb.as_posix(),
                ),
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
    pipeline_data: Annotated[str | None, Form(description="流水线元数据 JSON")] = None,
    batch_id: Annotated[str | None, Form(description="兼容旧调用；新调用写入 pipeline_data")] = None,
    captured_at: Annotated[str | None, Form(description="兼容旧调用；新调用写入 pipeline_data")] = None,
    platform: Annotated[str | None, Form(description="兼容旧报告；新报告在场景中携带")] = None,
    shading_quality: Annotated[int | None, Form(description="兼容旧报告；新报告在场景中携带")] = None,
    branch_tag: Annotated[str | None, Form(description="兼容旧调用；新调用写入 pipeline_data")] = None,
    batch_url: Annotated[str | None, Form()] = None,
    p4_version: Annotated[int | None, Form()] = None,
    overwrite: Annotated[bool, Form()] = False,
):
    report_bytes = report.file.read(MAX_REPORT_BYTES + 1)
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise http_error(413, "REPORT_TOO_LARGE", "GPMHeatmap.json 超过 64 MiB")
    try:
        payload = json.loads(report_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise http_error(422, "INVALID_GPM_JSON", "GPMHeatmap.json 无法解析")
    scenes = _validate_report(payload)

    pipeline = _parse_pipeline_data(pipeline_data)
    batch_id = require_identifier(
        str(_metadata_value(pipeline.get("batch_id"), batch_id, "batch_id", required=True)),
        "batch_id", maximum=120,
    )
    resolved_branch = _metadata_value(pipeline.get("branch_tag"), branch_tag, "branch_tag") or "main"
    branch_tag = require_identifier(str(resolved_branch).strip().lower(), "branch_tag", maximum=120)
    captured_at = _parse_iso_datetime(str(_metadata_value(
        pipeline.get("captured_at"), captured_at, "captured_at", required=True,
    )))
    batch_url = _metadata_value(pipeline.get("batch_url"), batch_url, "batch_url")
    if batch_url is not None:
        batch_url = str(batch_url).strip() or None
        if batch_url and len(batch_url) > 2048:
            raise http_error(422, "INVALID_BATCH_URL", "batch_url 不能超过 2048 个字符")

    platform = require_platform(_metadata_value(
        _report_scope_value(scenes, "platform"), platform, "platform", required=True,
    ))
    raw_quality = _metadata_value(
        _report_scope_value(scenes, "shading_quality"), shading_quality,
        "shading_quality", required=True,
    )
    try:
        shading_quality = int(raw_quality)
    except (TypeError, ValueError):
        raise http_error(422, "INVALID_SHADING_QUALITY", "shading_quality 必须在 0 到 5 之间")
    if not 0 <= shading_quality <= 5:
        raise http_error(422, "INVALID_SHADING_QUALITY", "shading_quality 必须在 0 到 5 之间")
    raw_p4 = _metadata_value(
        _report_scope_value(scenes, "p4_version"), p4_version, "p4_version", required=True,
    )
    try:
        p4_version = int(raw_p4) if raw_p4 not in (None, "") else None
    except (TypeError, ValueError):
        raise http_error(422, "INVALID_P4_VERSION", "p4_version 必须是非负整数")
    if p4_version is not None and p4_version < 0:
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
            for scene in scenes
            for point in scene["detail"]
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
                    JOIN gpm_scenes s ON s.id = p.scene_row_id
                    WHERE s.upload_id = ?
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
                scenes=scenes,
                image_entries=image_entries,
                relative_root=relative_root,
                batch_id=batch_id,
                branch_tag=branch_tag,
                batch_url=batch_url,
                captured_at=captured_at,
                p4_version=p4_version,
                platform=platform,
                shading_quality=shading_quality,
                source_sha256=hashlib.sha256(report_bytes).hexdigest(),
            )
            connection.commit()
            _remove_replaced_asset_dirs(old_asset_dirs, batch_root)
            return {
                "id": upload_id,
                "batch_id": batch_id,
                "branch_tag": branch_tag,
                "scene_count": len(scenes),
                "point_count": sum(len(scene["detail"]) for scene in scenes),
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
