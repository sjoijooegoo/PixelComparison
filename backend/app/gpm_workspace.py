"""GPMHeatmap 工作区读模型：地图帧、点位详情、趋势与资源。"""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from .gpm_batch_catalog import batch_dto
from .gpm_common import asset_url, http_error, require_identifier
from .gpm_map_config import runtime_map_config
from .gpm_metric_values import metric_change_percentages as _metric_change_percentages
from .gpm_scale_config import resolve_heat_scales
from .gpm_storage import connect_gpm_database, gpm_assets_dir


router = APIRouter()

TREND_DAYS = {7, 14, 30}
TREND_SUMMARY_FIELDS = {
    "Scene_DC": "AvgSceneDrawCall",
    "Scene_Tris": "AvgSceneTriangle",
    "Drawcall": "AvgDrawCall",
    "Triangle": "AvgTriangle",
}


def _trend_days(days: int) -> int:
    if days not in TREND_DAYS:
        raise http_error(422, "INVALID_GPM_TREND_DAYS", "趋势范围仅支持 7、14、30 天")
    return days


def _summary_metrics(raw_trend: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for item in json.loads(raw_trend):
        if not isinstance(item, dict):
            continue
        metric_key = item.get("key")
        field = TREND_SUMMARY_FIELDS.get(metric_key)
        summary = item.get("summary_data")
        value = summary.get(field) if field and isinstance(summary, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            metrics[metric_key] = value
    return metrics


def _point_dto(row, *, detail: bool = False) -> dict:
    item = {
        "id": row["id"],
        "index": row["point_index"],
        "screenshot_id": row["screenshot_id"],
        "position": [row["position_x"], row["position_y"]],
        "direction": [row["direction_x"], row["direction_y"]],
        "heat_map_data": json.loads(row["heat_map_data_json"]),
        "thumbnail_url": asset_url(row["thumbnail_path"]),
        "image_url": asset_url(row["screenshot_path"]),
    }
    if detail:
        item["trend_data"] = json.loads(row["trend_data_json"])
        item["detail_data"] = json.loads(row["detail_data_json"])
    return item


def _latest_platform_p4(
    connection,
    *,
    branch_tag: str,
    platform: str,
) -> int | None:
    """Return the highest reported P4 for one branch/platform scope."""

    row = connection.execute(
        """
        SELECT MAX(p4_version) AS latest_p4_version
        FROM gpm_uploads
        WHERE branch_tag = ? AND platform = ?
        """,
        (branch_tag, platform),
    ).fetchone()
    value = row["latest_p4_version"] if row else None
    return int(value) if value is not None else None


@router.get("/api/gpm-heatmaps/maps/{map_name}/frame")
def get_map_frame(
    map_name: str,
    branch_tag: str = Query("main"),
    platform: str | None = Query(None),
    shading_quality: int | None = Query(None, ge=0, le=5),
    batch_id: str | None = Query(None),
    nearest_p4_version: int | None = Query(None, ge=0),
    preferred_p4_version: int | None = Query(None, ge=0),
):
    map_name = require_identifier(map_name, "map_name")
    connection = connect_gpm_database()
    try:
        clauses = ["m.map_name = ?", "u.branch_tag = ?"]
        params: list[object] = [map_name, branch_tag]
        if platform:
            clauses.append("u.platform = ?")
            params.append(platform)
        if shading_quality is not None:
            clauses.append("u.shading_quality = ?")
            params.append(shading_quality)
        batches = connection.execute(
            f"""
            SELECT u.id, u.batch_id, u.branch_tag, u.batch_url, u.captured_at,
                   u.captured_at_epoch, u.p4_version, u.platform, u.shading_quality,
                   m.id AS upload_map_id, m.map_name, m.show_direction
            FROM gpm_uploads u JOIN gpm_upload_maps m ON m.upload_id = u.id
            WHERE {' AND '.join(clauses)}
            ORDER BY u.p4_version DESC, u.captured_at_epoch DESC, u.id DESC
            """,
            tuple(params),
        ).fetchall()
        if not batches:
            raise http_error(404, "GPM_MAP_DATA_NOT_FOUND", "当前筛选下没有热力图数据")
        latest_p4_version = (
            _latest_platform_p4(
                connection,
                branch_tag=branch_tag,
                platform=platform,
            )
            if platform
            else None
        )
        selected = next((row for row in batches if row["batch_id"] == batch_id), None) if batch_id else None
        if selected is None:
            if batch_id:
                raise http_error(404, "GPM_BATCH_NOT_FOUND", "当前筛选下找不到指定采集批次")
            if nearest_p4_version is not None:
                selected = min(
                    batches,
                    key=lambda row: (
                        abs(int(row["p4_version"]) - nearest_p4_version),
                        -int(row["p4_version"]),
                    ),
                )
            else:
                selected = (
                    next(
                        (
                            row for row in batches
                            if preferred_p4_version is not None
                            and int(row["p4_version"]) == preferred_p4_version
                        ),
                        None,
                    )
                    or next(
                        (
                            row for row in batches
                            if latest_p4_version is not None
                            and int(row["p4_version"]) == latest_p4_version
                        ),
                        batches[0],
                    )
                )
        if latest_p4_version is None:
            latest_p4_version = _latest_platform_p4(
                connection,
                branch_tag=branch_tag,
                platform=selected["platform"],
            )
        comparison_batches = sorted(
            (
                row for row in batches
                if row["platform"] == selected["platform"]
                and row["shading_quality"] == selected["shading_quality"]
            ),
            key=lambda row: int(row["id"]),
            reverse=True,
        )
        selected_index = next(
            index for index, row in enumerate(comparison_batches)
            if row["id"] == selected["id"]
        )
        previous = (
            comparison_batches[selected_index + 1]
            if selected_index + 1 < len(comparison_batches)
            else None
        )
        previous_metrics_by_index: dict[int, dict] = {}
        if previous:
            previous_point_rows = connection.execute(
                """
                SELECT point_index, heat_map_data_json
                FROM gpm_points WHERE upload_map_id = ?
                """,
                (previous["upload_map_id"],),
            ).fetchall()
            previous_metrics_by_index = {
                row["point_index"]: json.loads(row["heat_map_data_json"])
                for row in previous_point_rows
            }
        point_rows = connection.execute(
            """
            SELECT id, point_index, screenshot_id,
                   position_x, position_y, direction_x, direction_y,
                   heat_map_data_json, screenshot_path, thumbnail_path
            FROM gpm_points WHERE upload_map_id = ? ORDER BY point_index
            """,
            (selected["upload_map_id"],),
        ).fetchall()
        points = []
        for row in point_rows:
            point = _point_dto(row)
            point["metric_change_percent"] = _metric_change_percentages(
                point["heat_map_data"],
                previous_metrics_by_index.get(point["index"]),
            )
            points.append(point)
        map_payload = connection.execute(
            "SELECT heat_map_json, trend_json FROM gpm_upload_maps WHERE id = ?",
            (selected["upload_map_id"],),
        ).fetchone()
        heat_map = json.loads(map_payload["heat_map_json"])
        scales = resolve_heat_scales(
            connection,
            map_name=map_name,
            platform=selected["platform"],
            shading_quality=selected["shading_quality"],
            heat_map=heat_map,
            points=points,
        )
        for metric in heat_map:
            metric["scale"] = scales.get(metric.get("key"))
        return {
            "batch": batch_dto(selected),
            "previous_batch": batch_dto(previous) if previous else None,
            "available_batches": [batch_dto(row) for row in batches],
            "latest_p4_version": latest_p4_version,
            "map": {
                "map_name": map_name,
                "show_direction": bool(selected["show_direction"]),
            },
            "heat_map": heat_map,
            "trend": json.loads(map_payload["trend_json"]),
            "map_config": runtime_map_config(connection, map_name),
            "points": points,
        }
    finally:
        connection.close()


def get_point_details(point_ids: list[int]) -> dict[int, dict]:
    """批量读取点位详情，供在线详情接口与离线包导出共同复用。"""

    unique_ids = list(dict.fromkeys(int(point_id) for point_id in point_ids))
    if not unique_ids:
        return {}
    connection = connect_gpm_database()
    try:
        result = {}
        # SQLite 的变量数量存在上限，分块后可兼容点位很多的地图。
        for offset in range(0, len(unique_ids), 400):
            chunk = unique_ids[offset:offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""
                SELECT p.*, m.map_name, u.batch_id, u.branch_tag, u.captured_at,
                       u.p4_version, u.platform, u.shading_quality
                FROM gpm_points p JOIN gpm_upload_maps m ON m.id = p.upload_map_id
                JOIN gpm_uploads u ON u.id = m.upload_id WHERE p.id IN ({placeholders})
                """,
                tuple(chunk),
            ).fetchall()
            for row in rows:
                result[int(row["id"])] = {
                    **_point_dto(row, detail=True),
                    "map_name": row["map_name"],
                    "batch_id": row["batch_id"],
                    "captured_at": row["captured_at"],
                    "p4_version": row["p4_version"],
                    "platform": row["platform"],
                    "shading_quality": row["shading_quality"],
                }
        return result
    finally:
        connection.close()


@router.get("/api/gpm-heatmaps/points/{point_id}")
def get_point_detail(point_id: int):
    detail = get_point_details([point_id]).get(point_id)
    if not detail:
        raise http_error(404, "GPM_POINT_NOT_FOUND", "点位不存在")
    return detail


@router.get("/api/gpm-heatmaps/maps/{map_name}/trends")
def get_map_trends(
    map_name: str,
    branch_tag: str = Query("main"),
    platform: str = Query(...),
    shading_quality: int = Query(..., ge=0, le=5),
    days: int = Query(14),
):
    days = _trend_days(days)
    map_name = require_identifier(map_name, "map_name")
    connection = connect_gpm_database()
    try:
        latest = connection.execute(
            """
            SELECT u.captured_at_epoch FROM gpm_upload_maps m
            JOIN gpm_uploads u ON u.id = m.upload_id
            WHERE m.map_name = ? AND u.branch_tag = ? AND u.platform = ? AND u.shading_quality = ?
            ORDER BY u.captured_at_epoch DESC, u.id DESC LIMIT 1
            """,
            (map_name, branch_tag, platform, shading_quality),
        ).fetchone()
        if not latest:
            raise http_error(404, "GPM_MAP_DATA_NOT_FOUND", "当前筛选下没有热力图数据")
        start_epoch = int(latest["captured_at_epoch"]) - (days - 1) * 86400
        rows = connection.execute(
            """
            SELECT u.batch_id, u.captured_at, u.p4_version, m.trend_json
            FROM gpm_upload_maps m JOIN gpm_uploads u ON u.id = m.upload_id
            WHERE m.map_name = ? AND u.branch_tag = ? AND u.platform = ? AND u.shading_quality = ?
              AND u.captured_at_epoch >= ?
            ORDER BY u.captured_at_epoch, u.id
            """,
            (map_name, branch_tag, platform, shading_quality, start_epoch),
        ).fetchall()
        points = [{
            "batch_id": row["batch_id"],
            "captured_at": row["captured_at"],
            "p4_version": row["p4_version"],
            "metrics": _summary_metrics(row["trend_json"]),
        } for row in rows]
        return {
            "available": any(point["metrics"] for point in points),
            "reason": None,
            "days": days,
            "points": points,
        }
    finally:
        connection.close()


@router.get("/api/gpm-heatmaps/points/{point_id}/trends")
def get_point_trends(point_id: int, days: int = Query(14)):
    days = _trend_days(days)
    connection = connect_gpm_database()
    try:
        current = connection.execute(
            """
            SELECT p.point_index, p.trend_data_json, m.map_name,
                   u.branch_tag, u.platform, u.shading_quality,
                   u.captured_at, u.captured_at_epoch, u.p4_version, u.batch_id
            FROM gpm_points p JOIN gpm_upload_maps m ON m.id = p.upload_map_id
            JOIN gpm_uploads u ON u.id = m.upload_id WHERE p.id = ?
            """,
            (point_id,),
        ).fetchone()
        if not current:
            raise http_error(404, "GPM_POINT_NOT_FOUND", "点位不存在")
        latest = connection.execute(
            """
            SELECT MAX(u.captured_at_epoch) FROM gpm_upload_maps m
            JOIN gpm_uploads u ON u.id = m.upload_id
            WHERE m.map_name = ? AND u.branch_tag = ? AND u.platform = ? AND u.shading_quality = ?
            """,
            (current["map_name"], current["branch_tag"], current["platform"], current["shading_quality"]),
        ).fetchone()[0]
        start_epoch = int(latest) - (days - 1) * 86400
        rows = connection.execute(
            """
            SELECT u.batch_id, u.captured_at, u.p4_version, p.trend_data_json
            FROM gpm_points p JOIN gpm_upload_maps m ON m.id = p.upload_map_id
            JOIN gpm_uploads u ON u.id = m.upload_id
            WHERE p.point_index = ? AND m.map_name = ? AND u.branch_tag = ?
              AND u.platform = ? AND u.shading_quality = ? AND u.captured_at_epoch >= ?
            ORDER BY u.captured_at_epoch, u.id
            """,
            (
                current["point_index"], current["map_name"], current["branch_tag"],
                current["platform"], current["shading_quality"], start_epoch,
            ),
        ).fetchall()
        return {
            "available": True,
            "reason": None,
            "days": days,
            "points": [{
                "batch_id": row["batch_id"],
                "captured_at": row["captured_at"],
                "p4_version": row["p4_version"],
                "metrics": json.loads(row["trend_data_json"]),
            } for row in rows],
        }
    finally:
        connection.close()


@router.get("/gpm-assets/{asset_path:path}")
def get_asset(asset_path: str):
    root = gpm_assets_dir().resolve()
    target = (root / Path(*PurePosixPath(asset_path).parts)).resolve()
    if target == root or root not in target.parents or not target.is_file():
        raise http_error(404, "GPM_ASSET_NOT_FOUND", "GPMHeatmap 资源不存在")
    return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})
