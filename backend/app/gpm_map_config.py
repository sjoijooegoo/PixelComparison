"""GPMHeatmap 地图配置深模块。

模块统一管理地图的自动登记、完整配置保存、删除与运行时解析。地图定义、
标尺绑定和可选图片由模块保持原子一致，调用方不需要处理半保存状态。
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .gpm_common import IMAGE_SUFFIXES, asset_url, http_error, require_identifier, require_platform, safe_segment
from .gpm_storage import connect_gpm_database, gpm_assets_dir


MAX_MAP_IMAGE_BYTES = 32 * 1024 * 1024
_LOG = logging.getLogger("pixelcomp")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _pair(value: object, label: str, *, positive: bool = False) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", f"{label} 必须包含两个数字")
    try:
        pair = (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", f"{label} 必须包含两个数字") from exc
    if not all(math.isfinite(number) for number in pair):
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", f"{label} 必须包含两个有限数字")
    if positive and any(number <= 0 for number in pair):
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", f"{label} 必须大于 0")
    return pair


def _map_payload(map_name: str, payload: object) -> dict:
    if not isinstance(payload, dict):
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", "地图配置必须是对象")
    description = str(payload.get("description") or map_name).strip()
    if len(description) > 500:
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", "地图描述不能超过 500 个字符")
    origin_x, origin_y = _pair(payload.get("origin"), "origin")
    range_x, range_y = _pair(payload.get("range"), "range", positive=True)
    x_reverse = payload.get("x_reverse", False)
    y_reverse = payload.get("y_reverse", True)
    if not isinstance(x_reverse, bool) or not isinstance(y_reverse, bool):
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", "坐标轴反转配置必须是布尔值")
    expected_revision = payload.get("expected_revision")
    if expected_revision is not None and (
        isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
    ):
        raise http_error(422, "INVALID_GPM_REVISION", "expected_revision 必须是整数")
    return {
        "description": description,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "range_x": range_x,
        "range_y": range_y,
        "x_reverse": x_reverse,
        "y_reverse": y_reverse,
        "expected_revision": expected_revision,
        "bindings": payload.get("bindings", []),
    }


def _validate_bindings(connection: sqlite3.Connection, raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise http_error(422, "INVALID_GPM_MAP_SCALE_BINDINGS", "地图标尺绑定必须是数组")
    bindings: list[dict] = []
    scopes: set[tuple[str, int]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise http_error(422, "INVALID_GPM_MAP_SCALE_BINDINGS", f"bindings[{index}] 必须是对象")
        platform = require_platform(item.get("platform"), f"bindings[{index}].platform")
        quality = item.get("shading_quality")
        if isinstance(quality, bool) or not isinstance(quality, int) or not 0 <= quality <= 5:
            raise http_error(
                422, "INVALID_GPM_MAP_SCALE_BINDINGS",
                f"bindings[{index}].shading_quality 必须在 0 到 5 之间",
            )
        scale_set_id = item.get("scale_set_id")
        if isinstance(scale_set_id, bool) or not isinstance(scale_set_id, int):
            raise http_error(
                422, "INVALID_GPM_MAP_SCALE_BINDINGS",
                f"bindings[{index}].scale_set_id 必须是整数",
            )
        if not connection.execute(
            "SELECT 1 FROM gpm_metric_scale_sets WHERE id = ?", (scale_set_id,)
        ).fetchone():
            raise http_error(404, "GPM_METRIC_SCALE_SET_NOT_FOUND", "指标标尺集不存在")
        scope = (platform, quality)
        if scope in scopes:
            raise http_error(422, "DUPLICATE_GPM_MAP_SCALE_BINDING", "平台和画质配置不能重复")
        scopes.add(scope)
        bindings.append({
            "platform": platform,
            "shading_quality": quality,
            "scale_set_id": scale_set_id,
        })
    return bindings


def _read_image(image: UploadFile | None) -> tuple[bytes, int, int, str] | None:
    if image is None:
        return None
    raw = image.file.read(MAX_MAP_IMAGE_BYTES + 1)
    if len(raw) > MAX_MAP_IMAGE_BYTES:
        raise http_error(413, "MAP_IMAGE_TOO_LARGE", "地图图片超过 32 MiB")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            width, height = opened.size
            image_format = str(opened.format or "").lower()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError):
        raise http_error(422, "INVALID_MAP_IMAGE", "地图图片无法解析")
    suffix = ".jpg" if image_format in {"jpg", "jpeg"} else f".{image_format}"
    if suffix not in IMAGE_SUFFIXES:
        raise http_error(422, "UNSUPPORTED_MAP_IMAGE", "地图仅支持 PNG/JPEG/WebP")
    return raw, width, height, suffix


def _map_bindings(connection: sqlite3.Connection, map_name: str) -> list[dict]:
    return [dict(row) for row in connection.execute(
        """
        SELECT b.platform, b.shading_quality, b.scale_set_id, s.name AS scale_set_name
        FROM gpm_map_scale_set_bindings b
        JOIN gpm_metric_scale_sets s ON s.id = b.scale_set_id
        WHERE b.map_name = ?
        ORDER BY b.platform, b.shading_quality DESC
        """,
        (map_name,),
    )]


def map_definition_dto(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    include_bindings: bool = True,
) -> dict:
    image = None
    if row["image_path"]:
        image = {
            "url": asset_url(row["image_path"]),
            "width": row["image_width"],
            "height": row["image_height"],
        }
    return {
        "id": row["map_id"],
        "map_name": row["map_name"],
        "description": row["description"],
        "origin": [row["origin_x"], row["origin_y"]],
        "range": [row["range_x"], row["range_y"]],
        "x_reverse": bool(row["x_reverse"]),
        "y_reverse": bool(row["y_reverse"]),
        "revision": row["revision"],
        "image": image,
        "bindings": _map_bindings(connection, row["map_name"]) if include_bindings else [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_map_definitions(
    connection: sqlite3.Connection, *, include_bindings: bool = True,
) -> list[dict]:
    definitions = [
        map_definition_dto(connection, row, include_bindings=include_bindings)
        for row in connection.execute(
            "SELECT * FROM gpm_map_definitions ORDER BY map_id, map_name COLLATE NOCASE"
        )
    ]
    return definitions


def _next_map_id(connection: sqlite3.Connection) -> int:
    return int(connection.execute(
        "SELECT COALESCE(MAX(map_id), -1) + 1 FROM gpm_map_definitions"
    ).fetchone()[0])


def ensure_map_definitions(
    connection: sqlite3.Connection,
    map_names: Iterable[str],
) -> list[str]:
    """在上报事务中登记尚未出现的地图身份。

    自动登记只创建“待配置”记录：不猜测图片、坐标范围或标尺绑定。
    当前 schema 要求坐标为正数范围，因此使用不会被运行时解析的 1x1
    占位范围；只有上传图片后 runtime_map_config 才会返回地图投影配置。
    调用方必须持有写事务，以保证 ID 分配与上报数据一起提交。
    """

    normalized_names: list[str] = []
    seen: set[str] = set()
    for raw_name in map_names:
        map_name = require_identifier(raw_name, "map_name")
        if map_name in seen:
            continue
        seen.add(map_name)
        normalized_names.append(map_name)

    rows = connection.execute(
        "SELECT map_name, map_id FROM gpm_map_definitions"
    ).fetchall()
    existing_names = {row["map_name"] for row in rows}
    next_map_id = max((int(row["map_id"]) for row in rows), default=-1) + 1
    created: list[str] = []
    now = _now()
    for map_name in normalized_names:
        if map_name in existing_names:
            continue
        connection.execute(
            """
            INSERT INTO gpm_map_definitions (
                map_name, map_id, description, origin_x, origin_y, range_x, range_y,
                x_reverse, y_reverse, image_path, image_width, image_height,
                revision, created_at, updated_at
            ) VALUES (?, ?, ?, 0, 0, 1, 1, 0, 1, NULL, NULL, NULL, 1, ?, ?)
            """,
            (map_name, next_map_id, map_name, now, now),
        )
        existing_names.add(map_name)
        created.append(map_name)
        next_map_id += 1
    return created


def save_map_configuration(
    map_name: str,
    payload: object,
    image: UploadFile | None = None,
) -> dict:
    """原子保存定义和标尺绑定，并在成功后切换到新图片。"""

    map_name = require_identifier(map_name, "map_name")
    item = _map_payload(map_name, payload)
    prepared_image = _read_image(image)
    connection = connect_gpm_database()
    new_destination: Path | None = None
    old_image_path: str | None = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT * FROM gpm_map_definitions WHERE map_name = ?", (map_name,)
        ).fetchone()
        if current and item["expected_revision"] is None:
            raise http_error(
                409,
                "GPM_MAP_NAME_EXISTS",
                "地图名称已经存在；请从地图列表进入配置后再保存",
            )
        if current and item["expected_revision"] is not None and item["expected_revision"] != current["revision"]:
            raise http_error(409, "GPM_MAP_REVISION_CONFLICT", "地图配置已更新，请刷新后重试")
        bindings = _validate_bindings(connection, item["bindings"])
        now = _now()
        image_path = current["image_path"] if current else None
        image_width = current["image_width"] if current else None
        image_height = current["image_height"] if current else None
        old_image_path = image_path
        if prepared_image:
            raw, image_width, image_height, suffix = prepared_image
            relative = PurePosixPath("maps") / safe_segment(map_name, "map") / f"{uuid.uuid4().hex}{suffix}"
            new_destination = gpm_assets_dir() / Path(*relative.parts)
            new_destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = new_destination.with_name(f".{new_destination.name}.tmp")
            temporary.write_bytes(raw)
            os.replace(temporary, new_destination)
            image_path = relative.as_posix()

        if current:
            connection.execute(
                """
                UPDATE gpm_map_definitions SET description = ?, origin_x = ?, origin_y = ?,
                    range_x = ?, range_y = ?, x_reverse = ?, y_reverse = ?,
                    image_path = ?, image_width = ?, image_height = ?,
                    revision = revision + 1, updated_at = ? WHERE map_name = ?
                """,
                (
                    item["description"], item["origin_x"], item["origin_y"],
                    item["range_x"], item["range_y"], int(item["x_reverse"]),
                    int(item["y_reverse"]), image_path, image_width, image_height,
                    now, map_name,
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
                    map_name, _next_map_id(connection), item["description"],
                    item["origin_x"], item["origin_y"], item["range_x"], item["range_y"],
                    int(item["x_reverse"]), int(item["y_reverse"]),
                    image_path, image_width, image_height, now, now,
                ),
            )
        connection.execute("DELETE FROM gpm_map_scale_set_bindings WHERE map_name = ?", (map_name,))
        connection.executemany(
            """
            INSERT INTO gpm_map_scale_set_bindings (
                map_name, platform, shading_quality, scale_set_id
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (map_name, binding["platform"], binding["shading_quality"], binding["scale_set_id"])
                for binding in bindings
            ],
        )
        row = connection.execute(
            "SELECT * FROM gpm_map_definitions WHERE map_name = ?", (map_name,)
        ).fetchone()
        connection.commit()
        result = map_definition_dto(connection, row)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        if new_destination:
            new_destination.unlink(missing_ok=True)
        raise http_error(409, "GPM_MAP_CONFIGURATION_CONFLICT", "地图配置与现有数据冲突") from exc
    except Exception:
        connection.rollback()
        if new_destination:
            new_destination.unlink(missing_ok=True)
        raise
    finally:
        connection.close()

    if new_destination and old_image_path:
        old_file = gpm_assets_dir() / Path(*PurePosixPath(old_image_path).parts)
        try:
            old_file.unlink(missing_ok=True)
        except OSError:
            pass
    return result


def _remove_map_image(image_path: str | None) -> None:
    if not image_path:
        return
    relative = PurePosixPath(image_path)
    if relative.is_absolute() or ".." in relative.parts:
        _LOG.warning("忽略不安全的 GPM 地图图片路径: %s", image_path)
        return
    assets = gpm_assets_dir().resolve()
    target = (assets / Path(*relative.parts)).resolve()
    if target == assets or assets not in target.parents:
        _LOG.warning("忽略超出 GPM 资源目录的地图图片路径: %s", image_path)
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        # 数据库删除已经提交；资源清理失败不能伪装成用户操作失败。
        _LOG.exception("清理 GPM 地图图片失败: %s", target)
        return
    try:
        target.parent.rmdir()
    except OSError:
        # 目录中可能还有历史文件，不影响当前图片已被删除。
        pass


def delete_map_configuration(map_name: str, expected_revision: int) -> dict:
    """删除独立地图配置，保留同 map_name 的历史上报图。"""

    map_name = require_identifier(map_name, "map_name")
    connection = connect_gpm_database()
    image_path: str | None = None
    result: dict
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT map_id, revision, image_path FROM gpm_map_definitions WHERE map_name = ?",
            (map_name,),
        ).fetchone()
        if not current:
            raise http_error(404, "GPM_MAP_DEFINITION_NOT_FOUND", "地图配置不存在")
        if expected_revision != current["revision"]:
            raise http_error(409, "GPM_MAP_REVISION_CONFLICT", "地图配置已更新，请刷新后重试")
        image_path = current["image_path"]
        result = {
            "deleted": True,
            "map_name": map_name,
            "id": current["map_id"],
            "retained_upload_data": bool(connection.execute(
                "SELECT 1 FROM gpm_upload_maps WHERE map_name = ? LIMIT 1", (map_name,)
            ).fetchone()),
        }
        # 标尺绑定由外键 ON DELETE CASCADE 原子清理；上报表没有
        # 指向地图配置的外键，因此历史批次、点位和截图均会保留。
        connection.execute("DELETE FROM gpm_map_definitions WHERE map_name = ?", (map_name,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    _remove_map_image(image_path)
    return result


def runtime_map_config(connection: sqlite3.Connection, map_name: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM gpm_map_definitions WHERE map_name = ? AND image_path IS NOT NULL",
        (map_name,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["map_id"],
        "map_name": row["map_name"],
        "image_url": asset_url(row["image_path"]),
        "image_width": row["image_width"],
        "image_height": row["image_height"],
        "origin": [row["origin_x"], row["origin_y"]],
        "range": [row["range_x"], row["range_y"]],
        "x_reverse": bool(row["x_reverse"]),
        "y_reverse": bool(row["y_reverse"]),
    }


def map_preview(map_name: str) -> dict:
    map_name = require_identifier(map_name, "map_name")
    connection = connect_gpm_database()
    try:
        definition = connection.execute(
            "SELECT * FROM gpm_map_definitions WHERE map_name = ?", (map_name,)
        ).fetchone()
        if not definition:
            raise http_error(404, "GPM_MAP_DEFINITION_NOT_FOUND", "地图配置不存在")
        source = connection.execute(
            """
            SELECT u.batch_id, u.captured_at, u.platform, u.shading_quality,
                   m.id AS upload_map_id
            FROM gpm_upload_maps m JOIN gpm_uploads u ON u.id = m.upload_id
            WHERE m.map_name = ? ORDER BY u.captured_at_epoch DESC, u.id DESC LIMIT 1
            """,
            (map_name,),
        ).fetchone()
        points = []
        if source:
            points = [{
                "id": row["id"],
                "index": row["index"],
                "position": [row["x"], row["y"]],
            } for row in connection.execute(
                """
                SELECT id, point_index AS `index`, position_x AS x, position_y AS y
                FROM gpm_points WHERE upload_map_id = ? ORDER BY point_index
                """,
                (source["upload_map_id"],),
            )]
        return {
            "map": map_definition_dto(connection, definition),
            "source": dict(source) if source else None,
            "points": points,
            "point_count": len(points),
        }
    finally:
        connection.close()
