"""GPMHeatmap 地图配置与只读查询 API。

上传校验和文件发布由 gpm_upload 负责；数据库与路径配置由 gpm_storage 负责。
本模块保留地图版本、批次删除、筛选、点位详情、趋势和资源读取。
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from .gpm_common import (
    QUALITY_LABELS,
    asset_url as _asset_url,
    http_error as _http_error,
    require_identifier as _require_identifier,
    safe_segment as _safe_segment,
)
from .gpm_storage import connect_gpm_database as _connect, gpm_assets_dir
from .gpm_upload import router as upload_router
from .gpm_project_config import router as project_config_router, runtime_map_config
from .gpm_scale_config import resolve_heat_scales, router as scale_config_router


router = APIRouter()
router.include_router(upload_router)
router.include_router(project_config_router)
router.include_router(scale_config_router)

_TREND_DAYS = {7, 14, 30}
_TREND_SUMMARY_FIELDS = {
    "Scene_DC": "AvgSceneDrawCall",
    "Scene_Tris": "AvgSceneTriangle",
    "Drawcall": "AvgDrawCall",
    "Triangle": "AvgTriangle",
}


def _quality_dto(value: int) -> dict:
    return {"value": value, "label": QUALITY_LABELS.get(value, f"画质 {value}")}


def _validated_trend_days(days: int) -> int:
    if days not in _TREND_DAYS:
        raise _http_error(422, "INVALID_GPM_TREND_DAYS", "趋势范围仅支持 7、14、30 天")
    return days


def _trend_window_start(latest_captured_at: str, days: int) -> str:
    latest = datetime.fromisoformat(str(latest_captured_at).replace("Z", "+00:00"))
    return (latest - timedelta(days=days - 1)).isoformat(timespec="seconds")


def _summary_trend_metrics(raw_trend: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for item in json.loads(raw_trend):
        metric_key = item.get("key")
        summary_field = _TREND_SUMMARY_FIELDS.get(metric_key)
        value = item.get("summary_data", {}).get(summary_field) if summary_field else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[metric_key] = value
    return metrics

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
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id FROM gpm_uploads WHERE branch_tag = ? AND batch_id = ?",
            (branch_tag, batch_id),
        ).fetchone()
        if not row:
            raise _http_error(404, "GPM_BATCH_NOT_FOUND", "GPMHeatmap 批次不存在")
        connection.execute("DELETE FROM gpm_uploads WHERE id = ?", (row["id"],))
        connection.commit()
        assets_removed = True
        try:
            # 数据库提交是删除的事实边界。即使进程在清理文件时退出，也只会留下
            # 不可达的孤儿资源，不会让仍可查询的批次突然丢失图片。
            if asset_root.exists():
                shutil.rmtree(asset_root)
        except OSError:
            assets_removed = False
            logging.getLogger("pixelcomp").exception(
                "GPMHeatmap 批次已删除，但资源目录清理失败: %s", asset_root,
            )
        return {
            "batch_id": batch_id,
            "branch_tag": branch_tag,
            "deleted": True,
            "assets_removed": assets_removed,
        }
    except Exception:
        connection.rollback()
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


def _validated_filter_date(value: str | None, field: str) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except (TypeError, ValueError):
        raise _http_error(422, "INVALID_GPM_DATE_FILTER", f"{field} 必须是 YYYY-MM-DD 日期")


def _csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({item for item in value.split(",") if item}, key=str.casefold)


@router.get("/api/gpm-heatmaps/uploads/meta")
def gpm_upload_meta(branch_tag: str = Query("main")):
    branch_tag = _require_identifier(branch_tag.strip().lower(), "branch_tag", maximum=120)
    connection = _connect()
    try:
        branches = [
            row["branch_tag"] for row in connection.execute(
                "SELECT DISTINCT branch_tag FROM gpm_uploads ORDER BY branch_tag"
            ).fetchall()
        ]
        rows = connection.execute(
            """
            SELECT DISTINCT u.platform, u.shading_quality, s.scene_id
            FROM gpm_uploads u JOIN gpm_scenes s ON s.upload_id = u.id
            WHERE u.branch_tag = ?
            ORDER BY s.scene_id, u.platform, u.shading_quality DESC
            """,
            (branch_tag,),
        ).fetchall()
        return {
            "branch_tags": sorted(set(branches) | {"main"}),
            "platforms": sorted({row["platform"] for row in rows}, key=str.casefold),
            "scene_ids": sorted({row["scene_id"] for row in rows}, key=str.casefold),
            "shading_qualities": [
                _quality_dto(value)
                for value in sorted({row["shading_quality"] for row in rows}, reverse=True)
            ],
        }
    finally:
        connection.close()


@router.get("/api/gpm-heatmaps/uploads")
def list_gpm_uploads(
    branch_tag: str = Query("main"),
    platform: str | None = Query(None),
    scene_id: str | None = Query(None),
    shading_quality: int | None = Query(None, ge=0, le=5),
    captured_from: str | None = Query(None),
    captured_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    """按一次完整 GPM 上报分页；场景、点位和地图状态均聚合到批次行。"""

    branch_tag = _require_identifier(branch_tag.strip().lower(), "branch_tag", maximum=120)
    captured_from = _validated_filter_date(captured_from, "captured_from")
    captured_to = _validated_filter_date(captured_to, "captured_to")
    if captured_from and captured_to and captured_from > captured_to:
        raise _http_error(422, "INVALID_GPM_DATE_FILTER", "captured_from 不能晚于 captured_to")

    clauses = ["u.branch_tag = ?"]
    params: list[object] = [branch_tag]
    if platform:
        clauses.append("u.platform = ?")
        params.append(platform)
    if shading_quality is not None:
        clauses.append("u.shading_quality = ?")
        params.append(shading_quality)
    if scene_id:
        clauses.append("EXISTS (SELECT 1 FROM gpm_scenes sf WHERE sf.upload_id = u.id AND sf.scene_id = ?)")
        params.append(scene_id)
    if captured_from:
        # captured_at records the collection-side wall-clock date (with its
        # timezone). Filtering the ISO prefix avoids SQLite converting it to
        # UTC and accidentally moving an early-morning capture to yesterday.
        clauses.append("substr(u.captured_at, 1, 10) >= ?")
        params.append(captured_from)
    if captured_to:
        clauses.append("substr(u.captured_at, 1, 10) <= ?")
        params.append(captured_to)
    where = " AND ".join(clauses)

    connection = _connect()
    try:
        catalog_initialized = bool(connection.execute(
            "SELECT EXISTS(SELECT 1 FROM gpm_config_imports)"
        ).fetchone()[0])
        configured_map_condition = (
            "m.id IS NOT NULL AND d.active = 1"
            if catalog_initialized else "m.id IS NOT NULL"
        )
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM gpm_uploads u WHERE {where}", tuple(params),
        ).fetchone()[0])
        rows = connection.execute(
            f"""
            SELECT u.*,
                   COUNT(DISTINCT s.id) AS scene_count,
                   COUNT(DISTINCT p.id) AS point_count,
                   COUNT(DISTINCT CASE WHEN p.screenshot_path IS NOT NULL THEN p.id END)
                     AS screenshot_count,
                   GROUP_CONCAT(DISTINCT s.scene_id) AS scene_ids_csv,
                   GROUP_CONCAT(DISTINCT s.map_name) AS map_names_csv,
                   COUNT(DISTINCT s.map_name) AS map_count,
                   COUNT(DISTINCT CASE WHEN {configured_map_condition} THEN s.map_name END)
                     AS configured_map_count
            FROM gpm_uploads u
            JOIN gpm_scenes s ON s.upload_id = u.id
            LEFT JOIN gpm_points p ON p.scene_row_id = s.id
            LEFT JOIN gpm_map_revisions m ON m.map_name = s.map_name AND m.active = 1
            LEFT JOIN gpm_map_definitions d ON d.map_name = s.map_name
            WHERE {where}
            GROUP BY u.id
            ORDER BY datetime(u.captured_at) DESC, u.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
        items = []
        for row in rows:
            map_count = int(row["map_count"] or 0)
            configured = int(row["configured_map_count"] or 0)
            map_status = "configured" if map_count and configured == map_count else (
                "partial" if configured else "missing"
            )
            items.append({
                **_batch_dto(row),
                "created_at": row["created_at"],
                "scene_ids": _csv_values(row["scene_ids_csv"]),
                "map_names": _csv_values(row["map_names_csv"]),
                "scene_count": int(row["scene_count"] or 0),
                "point_count": int(row["point_count"] or 0),
                "screenshot_count": int(row["screenshot_count"] or 0),
                "map_count": map_count,
                "configured_map_count": configured,
                "map_status": map_status,
            })
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        connection.close()


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
            ORDER BY datetime(u.captured_at) DESC, u.id DESC
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
                   s.map_name, s.x_reverse, s.y_reverse, s.heat_map_json, s.trend_json
            FROM gpm_uploads u JOIN gpm_scenes s ON s.upload_id = u.id
            WHERE {scope}
            ORDER BY datetime(u.captured_at) DESC, u.id DESC
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
        point_dtos = [
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
        ]
        heat_map = json.loads(selected["heat_map_json"])
        resolved_scales = resolve_heat_scales(
            connection,
            map_name=selected["map_name"],
            platform=selected["platform"],
            shading_quality=selected["shading_quality"],
            heat_map=heat_map,
            points=point_dtos,
        )
        for metric in heat_map:
            metric["scale"] = resolved_scales.get(metric.get("key"))
        return {
            "batch": _batch_dto(selected),
            "available_batches": [_batch_dto(row) for row in batches],
            "scene": {
                "id": scene_id, "pic_id": selected["pic_id"],
                "map_name": selected["map_name"],
                "show_z": bool(selected["show_z"]),
                "show_direction": bool(selected["show_direction"]),
                "x_reverse": bool(selected["x_reverse"]),
                "y_reverse": bool(selected["y_reverse"]),
            },
            "heat_map": heat_map,
            "trend": json.loads(selected["trend_json"]),
            "map_config": runtime_map_config(connection, selected["map_name"]),
            "points": point_dtos,
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


@router.get("/api/gpm-heatmaps/scenes/{scene_id}/trends")
def gpm_scene_trends(
    scene_id: str,
    branch_tag: str = Query("main"),
    platform: str = Query(...),
    shading_quality: int = Query(..., ge=0, le=5),
    days: int = Query(14),
):
    days = _validated_trend_days(days)
    connection = _connect()
    try:
        params = (scene_id, branch_tag, platform, shading_quality)
        latest = connection.execute(
            """
            SELECT u.captured_at
            FROM gpm_scenes s JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE s.scene_id = ? AND u.branch_tag = ?
              AND u.platform = ? AND u.shading_quality = ?
            ORDER BY datetime(u.captured_at) DESC, u.id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if not latest:
            raise _http_error(404, "GPM_SCENE_NOT_FOUND", "当前筛选下没有 GPMHeatmap 场景数据")
        latest_captured_at = latest["captured_at"]
        start = _trend_window_start(latest_captured_at, days)
        rows = connection.execute(
            """
            SELECT u.batch_id, u.captured_at, u.p4_version, s.trend_json
            FROM gpm_scenes s JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE s.scene_id = ? AND u.branch_tag = ?
              AND u.platform = ? AND u.shading_quality = ?
              AND datetime(u.captured_at) >= datetime(?)
            ORDER BY datetime(u.captured_at) ASC, u.id ASC
            """,
            (*params, start),
        ).fetchall()
        points = [{
            "batch_id": row["batch_id"],
            "captured_at": row["captured_at"],
            "p4_version": row["p4_version"],
            "metrics": _summary_trend_metrics(row["trend_json"]),
        } for row in rows]
        available = any(point["metrics"] for point in points)
        return {
            "available": available,
            "reason": None if available else "上报数据没有整体平均指标",
            "days": days,
            "points": points,
        }
    finally:
        connection.close()


@router.get("/api/gpm-heatmaps/points/{point_id}/trends")
def gpm_point_trends(point_id: int, days: int = Query(14)):
    days = _validated_trend_days(days)
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
        latest = connection.execute(
            """
            SELECT u.captured_at
            FROM gpm_scenes s JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE s.scene_id = ? AND u.branch_tag = ?
              AND u.platform = ? AND u.shading_quality = ?
            ORDER BY datetime(u.captured_at) DESC, u.id DESC
            LIMIT 1
            """,
            (
                current["scene_id"], current["branch_tag"],
                current["platform"], current["shading_quality"],
            ),
        ).fetchone()
        latest_captured_at = latest["captured_at"]
        start = _trend_window_start(latest_captured_at, days)
        rows = connection.execute(
            """
            SELECT u.batch_id, u.captured_at, u.p4_version, p.trend_data_json
            FROM gpm_points p JOIN gpm_scenes s ON s.id = p.scene_row_id
            JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE p.point_key = ? AND s.scene_id = ? AND u.branch_tag = ?
              AND u.platform = ? AND u.shading_quality = ?
              AND datetime(u.captured_at) >= datetime(?)
            ORDER BY datetime(u.captured_at) ASC, u.id ASC
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
