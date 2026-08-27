"""GPMHeatmap 地图配置与只读查询 API。

上传校验和文件发布由 gpm_upload 负责；数据库与路径配置由 gpm_storage 负责。
本模块保留地图版本、批次删除、筛选、点位详情、趋势和资源读取。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from .gpm_common import (
    IMAGE_SUFFIXES,
    QUALITY_LABELS,
    asset_url as _asset_url,
    http_error as _http_error,
    require_identifier as _require_identifier,
    safe_segment as _safe_segment,
)
from .gpm_storage import connect_gpm_database as _connect, gpm_assets_dir
from .gpm_upload import router as upload_router


router = APIRouter()
router.include_router(upload_router)


def _quality_dto(value: int) -> dict:
    return {"value": value, "label": QUALITY_LABELS.get(value, f"画质 {value}")}



@router.post("/api/gpm-heatmaps/maps/{scene_id}", status_code=201)
def upload_gpm_map(
    scene_id: str,
    image: Annotated[UploadFile, File()],
    origin_x: Annotated[float, Form()],
    origin_y: Annotated[float, Form()],
    range_x: Annotated[float, Form()],
    range_y: Annotated[float, Form()],
    x_reverse: Annotated[bool, Form()] = False,
    y_reverse: Annotated[bool, Form()] = True,
    color_ranges: Annotated[str, Form()] = "{}",
):
    scene_id = _require_identifier(scene_id, "scene_id")
    if range_x <= 0 or range_y <= 0:
        raise _http_error(422, "INVALID_MAP_CONFIG", "场景 ID 和正数坐标范围必填")
    try:
        parsed_ranges = json.loads(color_ranges)
        if not isinstance(parsed_ranges, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise _http_error(422, "INVALID_COLOR_RANGES", "color_ranges 必须是 JSON 对象")
    raw = image.file.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise _http_error(413, "MAP_IMAGE_TOO_LARGE", "地图图片超过 32 MiB")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            width, height = opened.size
            image_format = (opened.format or "PNG").lower()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise _http_error(422, "INVALID_MAP_IMAGE", "地图图片无法解析")
    suffix = ".jpg" if image_format in {"jpg", "jpeg"} else f".{image_format}"
    if suffix not in IMAGE_SUFFIXES:
        raise _http_error(422, "UNSUPPORTED_MAP_IMAGE", "地图仅支持 PNG/JPEG/WebP")

    connection = _connect()
    destination: Path | None = None
    temp_destination: Path | None = None
    published = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        revision = int(connection.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM gpm_map_revisions WHERE scene_id = ?",
            (scene_id,),
        ).fetchone()[0])
        relative = PurePosixPath("maps") / _safe_segment(scene_id, "scene") / f"r{revision}{suffix}"
        destination = gpm_assets_dir() / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_destination = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temp_destination.write_bytes(raw)
        os.replace(temp_destination, destination)
        published = True
        connection.execute("UPDATE gpm_map_revisions SET active = 0 WHERE scene_id = ?", (scene_id,))
        cursor = connection.execute(
            """
            INSERT INTO gpm_map_revisions (
                scene_id, revision, image_path, image_width, image_height,
                origin_x, origin_y, range_x, range_y, x_reverse, y_reverse,
                color_ranges_json, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                scene_id, revision, relative.as_posix(), width, height,
                origin_x, origin_y, range_x, range_y, int(x_reverse), int(y_reverse),
                json.dumps(parsed_ranges, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"),
            ),
        )
        connection.commit()
        return {"id": cursor.lastrowid, "scene_id": scene_id, "revision": revision, "active": True}
    except Exception:
        connection.rollback()
        if published and destination is not None:
            destination.unlink(missing_ok=True)
        if temp_destination is not None:
            temp_destination.unlink(missing_ok=True)
        raise
    finally:
        connection.close()


@router.delete("/api/gpm-heatmaps/uploads/{batch_id}")
def delete_gpm_upload(batch_id: str, branch_tag: str = Query("main")):
    """按 GPM 模块自己的批次身份删除，绝不触碰截图对比批次。"""

    batch_id = _require_identifier(batch_id, "batch_id", maximum=120)
    branch_tag = _require_identifier(branch_tag.strip().lower(), "branch_tag", maximum=120)
    relative_root = (
        PurePosixPath("uploads")
        / _safe_segment(branch_tag, "main")
        / _safe_segment(batch_id, "batch")
    )
    asset_root = gpm_assets_dir() / Path(*relative_root.parts)
    trash = asset_root.with_name(f".{asset_root.name}.deleted-{uuid.uuid4().hex}")
    moved = False
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id FROM gpm_uploads WHERE branch_tag = ? AND batch_id = ?",
            (branch_tag, batch_id),
        ).fetchone()
        if not row:
            raise _http_error(404, "GPM_BATCH_NOT_FOUND", "GPMHeatmap 批次不存在")
        if asset_root.exists():
            asset_root.rename(trash)
            moved = True
        connection.execute("DELETE FROM gpm_uploads WHERE id = ?", (row["id"],))
        connection.commit()
        if moved:
            shutil.rmtree(trash, ignore_errors=True)
        return {"batch_id": batch_id, "branch_tag": branch_tag, "deleted": True}
    except Exception:
        connection.rollback()
        if moved and trash.exists():
            trash.rename(asset_root)
        raise
    finally:
        connection.close()


def _batch_dto(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "branch_tag": row["branch_tag"],
        "batch_url": row["batch_url"],
        "captured_at": row["captured_at"],
        "p4_version": row["p4_version"],
        "platform": row["platform"],
        "shading_quality": row["shading_quality"],
        "shading_quality_label": QUALITY_LABELS.get(row["shading_quality"], f"画质 {row['shading_quality']}"),
    }


@router.get("/api/gpm-heatmaps/meta")
def gpm_meta(branch_tag: str = Query("main")):
    connection = _connect()
    try:
        rows = connection.execute(
            """
            SELECT u.*, s.scene_id, COUNT(p.id) AS point_count
            FROM gpm_uploads u
            JOIN gpm_scenes s ON s.upload_id = u.id
            LEFT JOIN gpm_points p ON p.scene_row_id = s.id
            WHERE u.branch_tag = ?
            GROUP BY u.id, s.id
            ORDER BY u.captured_at DESC, u.id DESC
            """,
            (branch_tag,),
        ).fetchall()
        scene_map: dict[str, dict] = {}
        for row in rows:
            scene = scene_map.setdefault(row["scene_id"], {
                "value": row["scene_id"], "batch_count": 0, "point_count": 0,
                "latest_at": row["captured_at"], "platforms": set(), "qualities": set(),
                "scope_qualities": {},
            })
            scene["batch_count"] += 1
            scene["point_count"] += row["point_count"]
            scene["platforms"].add(row["platform"])
            scene["qualities"].add(row["shading_quality"])
            scene["scope_qualities"].setdefault(row["platform"], set()).add(row["shading_quality"])
        scenes = []
        for scene in scene_map.values():
            scene["platforms"] = sorted(scene["platforms"])
            scene["shading_qualities"] = [_quality_dto(value) for value in sorted(scene.pop("qualities"), reverse=True)]
            scene["platform_qualities"] = [
                {
                    "platform": platform,
                    "shading_qualities": [_quality_dto(value) for value in sorted(values, reverse=True)],
                }
                for platform, values in sorted(scene.pop("scope_qualities").items())
            ]
            scenes.append(scene)
        return {
            "branch_tag": branch_tag,
            "platforms": sorted({row["platform"] for row in rows}),
            "shading_qualities": [_quality_dto(value) for value in sorted({row["shading_quality"] for row in rows}, reverse=True)],
            "scene_ids": scenes,
        }
    finally:
        connection.close()


def _map_config(connection: sqlite3.Connection, scene_id: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM gpm_map_revisions WHERE scene_id = ? AND active = 1",
        (scene_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"], "revision": row["revision"],
        "image_url": _asset_url(row["image_path"]),
        "image_width": row["image_width"], "image_height": row["image_height"],
        "origin": [row["origin_x"], row["origin_y"]],
        "range": [row["range_x"], row["range_y"]],
        "x_reverse": bool(row["x_reverse"]), "y_reverse": bool(row["y_reverse"]),
        "color_ranges": json.loads(row["color_ranges_json"]),
    }


@router.get("/api/gpm-heatmaps/scenes/{scene_id}/frame")
def gpm_scene_frame(
    scene_id: str,
    branch_tag: str = Query("main"),
    platform: str | None = Query(None),
    shading_quality: int | None = Query(None, ge=0, le=5),
    batch_id: str | None = Query(None),
):
    connection = _connect()
    try:
        clauses = ["s.scene_id = ?", "u.branch_tag = ?"]
        params: list[object] = [scene_id, branch_tag]
        if platform:
            clauses.append("u.platform = ?")
            params.append(platform)
        if shading_quality is not None:
            clauses.append("u.shading_quality = ?")
            params.append(shading_quality)
        scope = " AND ".join(clauses)
        batches = connection.execute(
            f"""
            SELECT u.*, s.id AS scene_row_id, s.pic_id, s.show_z, s.show_direction,
                   s.x_reverse, s.y_reverse, s.heat_map_json, s.trend_json
            FROM gpm_uploads u JOIN gpm_scenes s ON s.upload_id = u.id
            WHERE {scope}
            ORDER BY u.captured_at DESC, u.id DESC
            """,
            tuple(params),
        ).fetchall()
        if not batches:
            raise _http_error(404, "GPM_SCENE_NOT_FOUND", "当前筛选下没有 GPMHeatmap 场景数据")
        selected = next((row for row in batches if row["batch_id"] == batch_id), None) if batch_id else batches[0]
        if selected is None:
            raise _http_error(404, "GPM_BATCH_NOT_FOUND", "当前筛选下找不到指定采集批次")
        # 首屏禁止把体积较大的 detail_data_json 一并读出；用户选中点位后再走详情接口。
        points = connection.execute(
            """
            SELECT id, point_index, screenshot_id, point_key, position_json,
                   direction_json, view_json, heat_map_data_json, trend_data_json,
                   screenshot_path, thumbnail_path
            FROM gpm_points WHERE scene_row_id = ? ORDER BY point_index
            """,
            (selected["scene_row_id"],),
        ).fetchall()
        return {
            "batch": _batch_dto(selected),
            "available_batches": [_batch_dto(row) for row in batches],
            "scene": {
                "id": scene_id, "pic_id": selected["pic_id"],
                "show_z": bool(selected["show_z"]),
                "show_direction": bool(selected["show_direction"]),
                "x_reverse": bool(selected["x_reverse"]),
                "y_reverse": bool(selected["y_reverse"]),
            },
            "heat_map": json.loads(selected["heat_map_json"]),
            "trend": json.loads(selected["trend_json"]),
            "map_config": _map_config(connection, scene_id),
            "points": [
                {
                    "id": row["id"], "index": row["point_index"],
                    "screenshot_id": row["screenshot_id"], "point_key": row["point_key"],
                    "position": json.loads(row["position_json"]),
                    "direction": json.loads(row["direction_json"]),
                    "view": json.loads(row["view_json"]),
                    "heat_map_data": json.loads(row["heat_map_data_json"]),
                    "trend_data": json.loads(row["trend_data_json"]),
                    "thumbnail_url": _asset_url(row["thumbnail_path"]),
                    "image_url": _asset_url(row["screenshot_path"]),
                }
                for row in points
            ],
        }
    finally:
        connection.close()


@router.get("/api/gpm-heatmaps/points/{point_id}")
def gpm_point_detail(point_id: int):
    connection = _connect()
    try:
        row = connection.execute(
            """
            SELECT p.*, s.scene_id, u.batch_id, u.branch_tag, u.captured_at,
                   u.p4_version, u.platform, u.shading_quality
            FROM gpm_points p
            JOIN gpm_scenes s ON s.id = p.scene_row_id
            JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE p.id = ?
            """,
            (point_id,),
        ).fetchone()
        if not row:
            raise _http_error(404, "GPM_POINT_NOT_FOUND", "点位不存在")
        return {
            "id": row["id"], "index": row["point_index"],
            "screenshot_id": row["screenshot_id"], "point_key": row["point_key"],
            "scene_id": row["scene_id"], "batch_id": row["batch_id"],
            "captured_at": row["captured_at"], "p4_version": row["p4_version"],
            "platform": row["platform"], "shading_quality": row["shading_quality"],
            "position": json.loads(row["position_json"]),
            "direction": json.loads(row["direction_json"]),
            "view": json.loads(row["view_json"]),
            "heat_map_data": json.loads(row["heat_map_data_json"]),
            "trend_data": json.loads(row["trend_data_json"]),
            "detail_data": json.loads(row["detail_data_json"]),
            "thumbnail_url": _asset_url(row["thumbnail_path"]),
            "image_url": _asset_url(row["screenshot_path"]),
        }
    finally:
        connection.close()


@router.get("/api/gpm-heatmaps/points/{point_id}/trends")
def gpm_point_trends(point_id: int, days: int = Query(30, ge=1, le=90)):
    connection = _connect()
    try:
        current = connection.execute(
            """
            SELECT p.id, p.point_key, p.trend_data_json, s.scene_id,
                   u.branch_tag, u.platform, u.shading_quality,
                   u.captured_at, u.p4_version, u.batch_id
            FROM gpm_points p JOIN gpm_scenes s ON s.id = p.scene_row_id
            JOIN gpm_uploads u ON u.id = s.upload_id WHERE p.id = ?
            """,
            (point_id,),
        ).fetchone()
        if not current:
            raise _http_error(404, "GPM_POINT_NOT_FOUND", "点位不存在")
        if not current["point_key"]:
            return {
                "available": False,
                "reason": "当前上报数据没有稳定 point_key，无法安全关联跨批次点位",
                "days": days,
                "points": [{
                    "batch_id": current["batch_id"], "captured_at": current["captured_at"],
                    "p4_version": current["p4_version"],
                    "metrics": json.loads(current["trend_data_json"]),
                }],
            }
        # “最近 N 天”锚定当前筛选范围内的最新采集，而不是服务器当天；
        # 历史环境或暂停上报的项目仍能看到完整窗口。
        latest_captured_at = connection.execute(
            """
            SELECT MAX(u.captured_at)
            FROM gpm_scenes s JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE s.scene_id = ? AND u.branch_tag = ?
              AND u.platform = ? AND u.shading_quality = ?
            """,
            (
                current["scene_id"], current["branch_tag"],
                current["platform"], current["shading_quality"],
            ),
        ).fetchone()[0]
        latest = datetime.fromisoformat(str(latest_captured_at).replace("Z", "+00:00"))
        start = (latest - timedelta(days=days - 1)).isoformat(timespec="seconds")
        rows = connection.execute(
            """
            SELECT u.batch_id, u.captured_at, u.p4_version, p.trend_data_json
            FROM gpm_points p JOIN gpm_scenes s ON s.id = p.scene_row_id
            JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE p.point_key = ? AND s.scene_id = ? AND u.branch_tag = ?
              AND u.platform = ? AND u.shading_quality = ? AND u.captured_at >= ?
            ORDER BY u.captured_at ASC, u.id ASC
            """,
            (
                current["point_key"], current["scene_id"], current["branch_tag"],
                current["platform"], current["shading_quality"], start,
            ),
        ).fetchall()
        return {
            "available": True, "reason": None, "days": days,
            "points": [{
                "batch_id": row["batch_id"], "captured_at": row["captured_at"],
                "p4_version": row["p4_version"], "metrics": json.loads(row["trend_data_json"]),
            } for row in rows],
        }
    finally:
        connection.close()


@router.get("/gpm-assets/{asset_path:path}")
def gpm_asset(asset_path: str):
    root = gpm_assets_dir().resolve()
    target = (root / Path(*PurePosixPath(asset_path).parts)).resolve()
    if target == root or root not in target.parents or not target.is_file():
        raise _http_error(404, "GPM_ASSET_NOT_FOUND", "GPMHeatmap 资源不存在")
    return FileResponse(
        target,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
