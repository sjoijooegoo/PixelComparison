"""GPMHeatmap 批次目录模块：统一筛选目录、批次列表和删除命令。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Query

from .gpm_common import PLATFORMS, QUALITY_LABELS, http_error, require_identifier
from .gpm_retention import remove_gpm_point_assets
from .gpm_storage import connect_gpm_database


router = APIRouter()


def _quality_dto(value: int) -> dict:
    return {"value": value, "label": QUALITY_LABELS.get(value, f"画质 {value}")}


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
        "shading_quality_label": QUALITY_LABELS.get(row["shading_quality"], str(row["shading_quality"])),
    }


def _filter_date(value: str | None, field: str) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except (TypeError, ValueError):
        raise http_error(422, "INVALID_GPM_DATE_FILTER", f"{field} 必须是 YYYY-MM-DD 日期")


def _csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({item for item in value.split(",") if item}, key=str.casefold)


@router.get("/api/gpm-heatmaps/catalog")
def get_filter_catalog(branch_tag: str = Query("main")):
    branch_tag = require_identifier(branch_tag.strip().lower(), "branch_tag", maximum=120)
    connection = connect_gpm_database()
    try:
        branches = [
            row[0] for row in connection.execute(
                "SELECT DISTINCT branch_tag FROM gpm_uploads ORDER BY branch_tag"
            )
        ]
        data_rows = connection.execute(
            """
            SELECT u.platform, u.shading_quality, u.captured_at, m.map_name, COUNT(p.id) AS point_count
            FROM gpm_uploads u JOIN gpm_upload_maps m ON m.upload_id = u.id
            LEFT JOIN gpm_points p ON p.upload_map_id = m.id
            WHERE u.branch_tag = ?
            GROUP BY u.id, m.id ORDER BY u.captured_at_epoch DESC, u.id DESC
            """,
            (branch_tag,),
        ).fetchall()
        by_map: dict[str, dict] = {}
        for row in data_rows:
            item = by_map.setdefault(row["map_name"], {
                "batch_count": 0,
                "point_count": 0,
                "latest_at": None,
                "platforms": set(),
                "platform_qualities": {},
            })
            item["batch_count"] += 1
            item["point_count"] += int(row["point_count"] or 0)
            item["latest_at"] = item["latest_at"] or row["captured_at"]
            item["platforms"].add(row["platform"])
            item["platform_qualities"].setdefault(row["platform"], set()).add(row["shading_quality"])

        maps = []
        for definition in connection.execute(
            "SELECT map_id, map_name FROM gpm_map_definitions ORDER BY map_id, map_name COLLATE NOCASE"
        ):
            data = by_map.get(definition["map_name"], {})
            scopes = data.get("platform_qualities", {})
            qualities = {quality for values in scopes.values() for quality in values}
            maps.append({
                "id": definition["map_id"],
                "value": definition["map_name"],
                "has_data": bool(data),
                "batch_count": data.get("batch_count", 0),
                "point_count": data.get("point_count", 0),
                "latest_at": data.get("latest_at"),
                "platforms": sorted(data.get("platforms", set())),
                "shading_qualities": [_quality_dto(value) for value in sorted(qualities, reverse=True)],
                "platform_qualities": [
                    {
                        "platform": platform,
                        "shading_qualities": [_quality_dto(value) for value in sorted(values, reverse=True)],
                    }
                    for platform, values in sorted(scopes.items())
                ],
            })
        return {
            "branch_tag": branch_tag,
            "branch_tags": sorted(set(branches) | {"main"}),
            "platforms": list(PLATFORMS),
            "shading_qualities": [_quality_dto(value) for value in range(5, -1, -1)],
            "maps": maps,
        }
    finally:
        connection.close()


@router.get("/api/gpm-heatmaps/uploads")
def list_uploads(
    branch_tag: str = Query("main"),
    platform: str | None = Query(None),
    map_name: str | None = Query(None),
    shading_quality: int | None = Query(None, ge=0, le=5),
    captured_from: str | None = Query(None),
    captured_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    locate_batch_id: str | None = Query(None, max_length=120),
):
    branch_tag = require_identifier(branch_tag.strip().lower(), "branch_tag", maximum=120)
    captured_from = _filter_date(captured_from, "captured_from")
    captured_to = _filter_date(captured_to, "captured_to")
    if captured_from and captured_to and captured_from > captured_to:
        raise http_error(422, "INVALID_GPM_DATE_FILTER", "captured_from 不能晚于 captured_to")
    clauses = ["u.branch_tag = ?"]
    params: list[object] = [branch_tag]
    if platform:
        clauses.append("u.platform = ?")
        params.append(platform)
    if shading_quality is not None:
        clauses.append("u.shading_quality = ?")
        params.append(shading_quality)
    if map_name:
        clauses.append("EXISTS (SELECT 1 FROM gpm_upload_maps mf WHERE mf.upload_id = u.id AND mf.map_name = ?)")
        params.append(map_name)
    if captured_from:
        clauses.append("substr(u.captured_at, 1, 10) >= ?")
        params.append(captured_from)
    if captured_to:
        clauses.append("substr(u.captured_at, 1, 10) <= ?")
        params.append(captured_to)
    where = " AND ".join(clauses)

    connection = connect_gpm_database()
    try:
        # 定位、总数和当前页使用同一读取快照，页码与列表保持一致。
        connection.execute("BEGIN")
        located_batch_id = None
        if locate_batch_id:
            target = connection.execute(
                f"SELECT u.id FROM gpm_uploads u WHERE {where} AND u.batch_id = ?",
                (*params, locate_batch_id),
            ).fetchone()
            if target:
                preceding = connection.execute(
                    f"SELECT COUNT(*) FROM gpm_uploads u WHERE {where} AND u.id > ?",
                    (*params, target["id"]),
                ).fetchone()[0]
                page = int(preceding) // page_size + 1
                located_batch_id = locate_batch_id
            else:
                page = 1
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM gpm_uploads u WHERE {where}", tuple(params)
        ).fetchone()[0])
        rows = connection.execute(
            f"""
            SELECT u.*,
                   COUNT(DISTINCT p.id) AS point_count,
                   COUNT(DISTINCT p.id) AS screenshot_count,
                   GROUP_CONCAT(DISTINCT m.map_name) AS map_names_csv,
                   COUNT(DISTINCT m.map_name) AS map_count,
                   COUNT(DISTINCT CASE WHEN d.map_name IS NOT NULL THEN m.map_name END)
                     AS configured_map_count
            FROM gpm_uploads u
            JOIN gpm_upload_maps m ON m.upload_id = u.id
            LEFT JOIN gpm_points p ON p.upload_map_id = m.id
            LEFT JOIN gpm_map_definitions d ON d.map_name = m.map_name
            WHERE {where}
            GROUP BY u.id ORDER BY u.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
        items = []
        for row in rows:
            map_count = int(row["map_count"] or 0)
            configured = int(row["configured_map_count"] or 0)
            items.append({
                **_batch_dto(row),
                "created_at": row["created_at"],
                "map_names": _csv_values(row["map_names_csv"]),
                "point_count": int(row["point_count"] or 0),
                "screenshot_count": int(row["screenshot_count"] or 0),
                "map_count": map_count,
                "configured_map_count": configured,
                "map_status": "configured" if map_count and configured == map_count else (
                    "partial" if configured else "missing"
                ),
            })
        return {
            "items": items, "total": total, "page": page, "page_size": page_size,
            "located_batch_id": located_batch_id,
        }
    finally:
        connection.close()


@router.delete("/api/gpm-heatmaps/uploads/{batch_id}")
def delete_upload(batch_id: str, branch_tag: str = Query("main")):
    batch_id = require_identifier(batch_id, "batch_id", maximum=120)
    branch_tag = require_identifier(branch_tag.strip().lower(), "branch_tag", maximum=120)
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id FROM gpm_uploads WHERE branch_tag = ? AND batch_id = ?",
            (branch_tag, batch_id),
        ).fetchone()
        if not row:
            raise http_error(404, "GPM_BATCH_NOT_FOUND", "GPMHeatmap 批次不存在")
        asset_rows = connection.execute(
            """
            SELECT p.screenshot_path, p.thumbnail_path FROM gpm_points p
            JOIN gpm_upload_maps m ON m.id = p.upload_map_id WHERE m.upload_id = ?
            """,
            (row["id"],),
        ).fetchall()
        asset_paths = [item[key] for item in asset_rows for key in ("screenshot_path", "thumbnail_path")]
        connection.execute("DELETE FROM gpm_uploads WHERE id = ?", (row["id"],))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    _, failed = remove_gpm_point_assets(asset_paths)
    return {
        "batch_id": batch_id,
        "branch_tag": branch_tag,
        "deleted": True,
        "assets_removed": failed == 0,
    }


batch_dto = _batch_dto
