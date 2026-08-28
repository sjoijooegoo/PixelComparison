"""GPMHeatmap 项目地图清单、图片版本与坐标预览。

地图定义来自项目内的 DataForInstance.json；地图图片是独立、可多次替换的资源。
本模块把导入校验、原子替换、图片发布和运行时配置解析集中在同一个 seam。
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from PIL import Image, UnidentifiedImageError

from .gpm_common import (
    IMAGE_SUFFIXES,
    asset_url,
    http_error,
    require_identifier,
    safe_segment,
)
from .gpm_storage import connect_gpm_database, gpm_assets_dir


router = APIRouter()

_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_MAX_MAP_IMAGE_BYTES = 32 * 1024 * 1024
_MAX_MAPS = 5000


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{field} 必须是有限数字")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{field} 必须是有限数字")
    if not math.isfinite(number):
        raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{field} 必须是有限数字")
    return number


def _pair(value: object, field: str, *, positive: bool = False) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{field} 必须包含两个数字")
    left = _finite_number(value[0], f"{field}[0]")
    right = _finite_number(value[1], f"{field}[1]")
    if positive and (left <= 0 or right <= 0):
        raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{field} 必须为正数")
    return left, right


def _parse_project_config(raw: bytes) -> tuple[dict, list[dict]]:
    if not raw:
        raise http_error(422, "EMPTY_GPM_PROJECT_CONFIG", "配置文件不能为空")
    if len(raw) > _MAX_CONFIG_BYTES:
        raise http_error(413, "GPM_PROJECT_CONFIG_TOO_LARGE", "配置文件超过 4 MiB")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", "配置文件不是有效的 UTF-8 JSON")
    entries = payload.get("GpmConfig") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", "GpmConfig 必须是非空数组")
    if len(entries) > _MAX_MAPS:
        raise http_error(422, "TOO_MANY_GPM_MAPS", f"地图数量不能超过 {_MAX_MAPS}")

    definitions: list[dict] = []
    names: set[str] = set()
    ids: set[int] = set()
    for index, entry in enumerate(entries):
        prefix = f"GpmConfig[{index}]"
        if not isinstance(entry, dict):
            raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{prefix} 必须是对象")
        map_name = require_identifier(entry.get("pic_name"), f"{prefix}.pic_name")
        map_id = entry.get("map_id")
        if isinstance(map_id, bool) or not isinstance(map_id, int) or map_id < 0:
            raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{prefix}.map_id 必须是非负整数")
        if map_name in names:
            raise http_error(422, "DUPLICATE_GPM_MAP_NAME", f"地图名称重复: {map_name}")
        if map_id in ids:
            raise http_error(422, "DUPLICATE_GPM_MAP_ID", f"地图 ID 重复: {map_id}")
        description = str(entry.get("desc") or map_name).strip()
        if len(description) > 500:
            raise http_error(422, "INVALID_GPM_PROJECT_CONFIG", f"{prefix}.desc 不能超过 500 个字符")
        origin_x, origin_y = _pair(entry.get("start_pos"), f"{prefix}.start_pos")
        range_x, range_y = _pair(entry.get("map_size"), f"{prefix}.map_size", positive=True)
        names.add(map_name)
        ids.add(map_id)
        definitions.append({
            "map_name": map_name,
            "map_id": map_id,
            "description": description,
            "origin_x": origin_x,
            "origin_y": origin_y,
            "range_x": range_x,
            "range_y": range_y,
        })
    definitions.sort(key=lambda item: (item["map_id"], item["map_name"].casefold()))
    return payload, definitions


def _latest_import(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute(
        "SELECT * FROM gpm_config_imports ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "source_filename": row["source_filename"],
        "source_sha256": row["source_sha256"],
        "map_count": row["map_count"],
        "imported_at": row["imported_at"],
    }


def _ratio_difference(range_x: float, range_y: float, width: int, height: int) -> float:
    coordinate_ratio = range_x / range_y
    image_ratio = width / height
    return abs(image_ratio / coordinate_ratio - 1)


def _definition_dto(row: sqlite3.Row) -> dict:
    image = None
    difference = None
    if row["image_revision"] is not None:
        difference = _ratio_difference(
            row["range_x"], row["range_y"], row["image_width"], row["image_height"]
        )
        image = {
            "revision": row["image_revision"],
            "image_url": asset_url(row["image_path"]),
            "width": row["image_width"],
            "height": row["image_height"],
            "created_at": row["image_created_at"],
        }
    return {
        "map_name": row["map_name"],
        "map_id": row["map_id"],
        "description": row["description"],
        "origin": [row["origin_x"], row["origin_y"]],
        "range": [row["range_x"], row["range_y"]],
        "x_reverse": bool(row["x_reverse"]),
        "y_reverse": bool(row["y_reverse"]),
        "image": image,
        "coordinate_ratio": row["range_x"] / row["range_y"],
        "ratio_difference": difference,
        "upload_status": "uploaded" if image else "missing",
    }


def _active_definitions(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT d.*,
               r.revision AS image_revision, r.image_path,
               r.image_width, r.image_height, r.created_at AS image_created_at
        FROM gpm_map_definitions d
        LEFT JOIN gpm_map_revisions r ON r.map_name = d.map_name AND r.active = 1
        WHERE d.active = 1
        ORDER BY d.map_id, d.map_name COLLATE NOCASE
        """
    ).fetchall()
    return [_definition_dto(row) for row in rows]


@router.get("/api/gpm-heatmaps/project-config")
def get_project_config():
    connection = connect_gpm_database()
    try:
        maps = _active_definitions(connection)
        return {
            "latest_import": _latest_import(connection),
            "maps": maps,
            "summary": {
                "total": len(maps),
                "configured": sum(item["image"] is not None for item in maps),
                "missing": sum(item["image"] is None for item in maps),
            },
        }
    finally:
        connection.close()


@router.post("/api/gpm-heatmaps/project-config/import", status_code=201)
def import_project_config(config: Annotated[UploadFile, File()]):
    raw = config.file.read(_MAX_CONFIG_BYTES + 1)
    payload, definitions = _parse_project_config(raw)
    filename = Path(config.filename or "DataForInstance.json").name[:255]
    now = datetime.now().isoformat(timespec="seconds")
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            INSERT INTO gpm_config_imports (
                source_filename, source_sha256, raw_json, map_count, imported_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                filename,
                hashlib.sha256(raw).hexdigest(),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                len(definitions),
                now,
            ),
        )
        import_id = int(cursor.lastrowid)
        connection.execute("UPDATE gpm_map_definitions SET active = 0, updated_at = ?", (now,))
        for item in definitions:
            connection.execute(
                """
                INSERT INTO gpm_map_definitions (
                    map_name, map_id, description, origin_x, origin_y, range_x, range_y,
                    x_reverse, y_reverse, active, import_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, 1, ?, ?, ?)
                ON CONFLICT(map_name) DO UPDATE SET
                    map_id = excluded.map_id,
                    description = excluded.description,
                    origin_x = excluded.origin_x,
                    origin_y = excluded.origin_y,
                    range_x = excluded.range_x,
                    range_y = excluded.range_y,
                    active = 1,
                    import_id = excluded.import_id,
                    updated_at = excluded.updated_at
                """,
                (
                    item["map_name"], item["map_id"], item["description"],
                    item["origin_x"], item["origin_y"], item["range_x"], item["range_y"],
                    import_id, now, now,
                ),
            )
        # Bindings belong to the authoritative project map list. Keeping bindings
        # for removed maps makes them invisible in the UI while still blocking
        # scale-set deletion.
        connection.execute(
            """
            DELETE FROM gpm_map_scale_set_bindings
            WHERE NOT EXISTS (
                SELECT 1 FROM gpm_map_definitions d
                WHERE d.map_name = gpm_map_scale_set_bindings.map_name AND d.active = 1
            )
            """
        )
        connection.commit()
        maps = _active_definitions(connection)
        return {
            "latest_import": _latest_import(connection),
            "maps": maps,
            "summary": {
                "total": len(maps),
                "configured": sum(item["image"] is not None for item in maps),
                "missing": sum(item["image"] is None for item in maps),
            },
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _read_map_image(image: UploadFile) -> tuple[bytes, int, int, str]:
    raw = image.file.read(_MAX_MAP_IMAGE_BYTES + 1)
    if len(raw) > _MAX_MAP_IMAGE_BYTES:
        raise http_error(413, "MAP_IMAGE_TOO_LARGE", "地图图片超过 32 MiB")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            width, height = opened.size
            image_format = (opened.format or "PNG").lower()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise http_error(422, "INVALID_MAP_IMAGE", "地图图片无法解析")
    suffix = ".jpg" if image_format in {"jpg", "jpeg"} else f".{image_format}"
    if suffix not in IMAGE_SUFFIXES:
        raise http_error(422, "UNSUPPORTED_MAP_IMAGE", "地图仅支持 PNG/JPEG/WebP")
    return raw, width, height, suffix


def store_map_image(
    map_name: str,
    image: UploadFile,
    *,
    origin_x: float,
    origin_y: float,
    range_x: float,
    range_y: float,
    x_reverse: bool = False,
    y_reverse: bool = True,
    color_ranges: dict | None = None,
    require_active_definition: bool = False,
) -> dict:
    raw, width, height, suffix = _read_map_image(image)
    connection = connect_gpm_database()
    destination: Path | None = None
    temporary: Path | None = None
    published = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        if require_active_definition:
            definition = connection.execute(
                "SELECT * FROM gpm_map_definitions WHERE map_name = ? AND active = 1",
                (map_name,),
            ).fetchone()
            if not definition:
                raise http_error(
                    404, "GPM_MAP_DEFINITION_NOT_FOUND", "当前项目配置中不存在该地图",
                )
            origin_x = definition["origin_x"]
            origin_y = definition["origin_y"]
            range_x = definition["range_x"]
            range_y = definition["range_y"]
            x_reverse = bool(definition["x_reverse"])
            y_reverse = bool(definition["y_reverse"])
        revision = int(connection.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM gpm_map_revisions WHERE map_name = ?",
            (map_name,),
        ).fetchone()[0])
        relative = PurePosixPath("maps") / safe_segment(map_name, "map") / f"r{revision}{suffix}"
        destination = gpm_assets_dir() / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, destination)
        published = True
        connection.execute("UPDATE gpm_map_revisions SET active = 0 WHERE map_name = ?", (map_name,))
        cursor = connection.execute(
            """
            INSERT INTO gpm_map_revisions (
                map_name, scene_id, revision, image_path, image_width, image_height,
                origin_x, origin_y, range_x, range_y, x_reverse, y_reverse,
                color_ranges_json, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                map_name, map_name, revision, relative.as_posix(), width, height,
                origin_x, origin_y, range_x, range_y, int(x_reverse), int(y_reverse),
                json.dumps(color_ranges or {}, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        connection.commit()
        difference = _ratio_difference(range_x, range_y, width, height)
        return {
            "id": cursor.lastrowid,
            "map_name": map_name,
            "scene_id": map_name,
            "revision": revision,
            "active": True,
            "image_url": asset_url(relative.as_posix()),
            "image_width": width,
            "image_height": height,
            "ratio_difference": difference,
            "upload_status": "uploaded",
        }
    except Exception:
        connection.rollback()
        if published and destination is not None:
            destination.unlink(missing_ok=True)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    finally:
        connection.close()


@router.post("/api/gpm-heatmaps/maps/{map_name}", status_code=201)
def upload_legacy_map(
    map_name: str,
    image: Annotated[UploadFile, File()],
    origin_x: Annotated[float, Form()],
    origin_y: Annotated[float, Form()],
    range_x: Annotated[float, Form()],
    range_y: Annotated[float, Form()],
    x_reverse: Annotated[bool, Form()] = False,
    y_reverse: Annotated[bool, Form()] = True,
    color_ranges: Annotated[str, Form()] = "{}",
):
    map_name = require_identifier(map_name, "map_name")
    if range_x <= 0 or range_y <= 0:
        raise http_error(422, "INVALID_MAP_CONFIG", "地图坐标范围必须为正数")
    try:
        parsed_ranges = json.loads(color_ranges)
        if not isinstance(parsed_ranges, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise http_error(422, "INVALID_COLOR_RANGES", "color_ranges 必须是 JSON 对象")
    return store_map_image(
        map_name, image,
        origin_x=origin_x, origin_y=origin_y, range_x=range_x, range_y=range_y,
        x_reverse=x_reverse, y_reverse=y_reverse, color_ranges=parsed_ranges,
    )


@router.post("/api/gpm-heatmaps/project-config/maps/{map_name}/image", status_code=201)
def upload_project_map_image(map_name: str, image: Annotated[UploadFile, File()]):
    map_name = require_identifier(map_name, "map_name")
    return store_map_image(
        map_name, image,
        origin_x=0, origin_y=0, range_x=1, range_y=1,
        require_active_definition=True,
    )


@router.get("/api/gpm-heatmaps/project-config/maps/{map_name}/preview")
def get_map_preview(map_name: str):
    map_name = require_identifier(map_name, "map_name")
    connection = connect_gpm_database()
    try:
        definition = connection.execute(
            "SELECT * FROM gpm_map_definitions WHERE map_name = ? AND active = 1",
            (map_name,),
        ).fetchone()
        if not definition:
            raise http_error(404, "GPM_MAP_DEFINITION_NOT_FOUND", "当前项目配置中不存在该地图")
        scene = connection.execute(
            """
            SELECT s.id, s.scene_id, u.batch_id, u.branch_tag, u.captured_at
            FROM gpm_scenes s JOIN gpm_uploads u ON u.id = s.upload_id
            WHERE s.map_name = ?
            ORDER BY datetime(u.captured_at) DESC, u.id DESC LIMIT 1
            """,
            (map_name,),
        ).fetchone()
        points = []
        if scene:
            rows = connection.execute(
                "SELECT id, point_index, position_json FROM gpm_points WHERE scene_row_id = ? ORDER BY point_index",
                (scene["id"],),
            ).fetchall()
            for row in rows:
                position = json.loads(row["position_json"])
                in_bounds = (
                    definition["origin_x"] <= position[0] <= definition["origin_x"] + definition["range_x"]
                    and definition["origin_y"] <= position[1] <= definition["origin_y"] + definition["range_y"]
                )
                points.append({
                    "id": row["id"], "index": row["point_index"],
                    "position": position, "in_bounds": in_bounds,
                })
        return {
            "map_name": map_name,
            "source": None if not scene else {
                "scene_id": scene["scene_id"], "batch_id": scene["batch_id"],
                "branch_tag": scene["branch_tag"], "captured_at": scene["captured_at"],
            },
            "points": points,
            "point_count": len(points),
            "in_bounds_count": sum(point["in_bounds"] for point in points),
        }
    finally:
        connection.close()


def runtime_map_config(connection: sqlite3.Connection, map_name: str) -> dict | None:
    """优先使用导入清单中的坐标；尚未导入清单的旧库继续使用图片版本快照。"""

    catalog_initialized = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM gpm_config_imports)"
    ).fetchone()[0]
    if catalog_initialized:
        row = connection.execute(
            """
            SELECT r.*, d.origin_x AS definition_origin_x, d.origin_y AS definition_origin_y,
                   d.range_x AS definition_range_x, d.range_y AS definition_range_y,
                   d.x_reverse AS definition_x_reverse, d.y_reverse AS definition_y_reverse
            FROM gpm_map_definitions d
            JOIN gpm_map_revisions r ON r.map_name = d.map_name AND r.active = 1
            WHERE d.map_name = ? AND d.active = 1
            """,
            (map_name,),
        ).fetchone()
        if not row:
            return None
        origin = [row["definition_origin_x"], row["definition_origin_y"]]
        coordinate_range = [row["definition_range_x"], row["definition_range_y"]]
        x_reverse = bool(row["definition_x_reverse"])
        y_reverse = bool(row["definition_y_reverse"])
    else:
        row = connection.execute(
            "SELECT * FROM gpm_map_revisions WHERE map_name = ? AND active = 1",
            (map_name,),
        ).fetchone()
        if not row:
            return None
        origin = [row["origin_x"], row["origin_y"]]
        coordinate_range = [row["range_x"], row["range_y"]]
        x_reverse = bool(row["x_reverse"])
        y_reverse = bool(row["y_reverse"])
    return {
        "id": row["id"], "map_name": row["map_name"], "revision": row["revision"],
        "image_url": asset_url(row["image_path"]),
        "image_width": row["image_width"], "image_height": row["image_height"],
        "origin": origin, "range": coordinate_range,
        "x_reverse": x_reverse, "y_reverse": y_reverse,
        "color_ranges": json.loads(row["color_ranges_json"]),
    }
