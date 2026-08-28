"""GPMHeatmap 指标标尺、指标标尺集与地图作用域绑定。

调用方只请求最终标尺；标尺集匹配和动态回退均封装在本模块中。
"""

from __future__ import annotations

import json
import hashlib
import math
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Body

from .gpm_common import QUALITY_LABELS, http_error, require_identifier, require_platform
from .gpm_scale_expressions import (
    ScaleExpressionError,
    compile_scale_segments,
    segments_from_legacy,
)
from .gpm_storage import connect_gpm_database


router = APIRouter()

FIVE_LEVEL_PALETTE = {
    "id": "gpm-five-v1",
    "colors": ["#52e817", "#b7f400", "#ffb20a", "#ff4a0a", "#ff1111"],
    "labels": ["优秀", "良好", "可接受", "关注", "超标"],
}
_DIRECTIONS = {"lower_is_better", "higher_is_better"}
_MIN_COLOR_BANDS = 2
_MAX_COLOR_BANDS = 10


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _required_text(payload: dict, key: str, label: str, maximum: int) -> str:
    value = str(payload.get(key) or "").strip()
    if not value or len(value) > maximum:
        raise http_error(422, "INVALID_GPM_SCALE_CONFIG", f"{label}不能为空且不能超过 {maximum} 个字符")
    return value


def _metric_key(value: object, label: str) -> str:
    key = str(value or "").strip()
    if not key or len(key) > 200 or any(ord(character) < 32 for character in key):
        raise http_error(
            422, "INVALID_GPM_METRIC_KEY",
            f"{label} 不能为空、不能包含控制字符且不能超过 200 个字符",
        )
    return key


def _colors(value: object) -> list[str]:
    if value is None:
        return list(FIVE_LEVEL_PALETTE["colors"])
    if not isinstance(value, list) or not _MIN_COLOR_BANDS <= len(value) <= _MAX_COLOR_BANDS:
        raise http_error(
            422, "INVALID_GPM_SCALE_COLORS",
            f"颜色标尺必须包含 {_MIN_COLOR_BANDS} 到 {_MAX_COLOR_BANDS} 个颜色段",
        )
    colors: list[str] = []
    for item in value:
        color = str(item or "").strip().lower()
        if len(color) != 7 or not color.startswith("#"):
            raise http_error(422, "INVALID_GPM_SCALE_COLORS", "颜色必须使用 #RRGGBB 格式")
        try:
            int(color[1:], 16)
        except ValueError as exc:
            raise http_error(422, "INVALID_GPM_SCALE_COLORS", "颜色必须使用 #RRGGBB 格式") from exc
        colors.append(color)
    return colors


def _thresholds(value: object, color_count: int) -> list[float]:
    expected = color_count - 1
    if not isinstance(value, list) or len(value) != expected:
        raise http_error(
            422, "INVALID_GPM_SCALE_THRESHOLDS",
            f"{color_count} 个颜色段必须包含 {expected} 个递增阈值",
        )
    result: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise http_error(422, "INVALID_GPM_SCALE_THRESHOLDS", "标尺阈值必须是有限数字")
        try:
            number = float(item)
        except (TypeError, ValueError):
            raise http_error(422, "INVALID_GPM_SCALE_THRESHOLDS", "标尺阈值必须是有限数字")
        if not math.isfinite(number):
            raise http_error(422, "INVALID_GPM_SCALE_THRESHOLDS", "标尺阈值必须是有限数字")
        result.append(number)
    if any(right <= left for left, right in zip(result, result[1:])):
        raise http_error(422, "INVALID_GPM_SCALE_THRESHOLDS", "标尺阈值必须严格递增")
    return result


def _direction(value: object) -> str:
    direction = str(value or "lower_is_better")
    if direction not in _DIRECTIONS:
        raise http_error(422, "INVALID_GPM_SCALE_DIRECTION", "指标方向不受支持")
    return direction


def _scale_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise http_error(422, "INVALID_GPM_SCALE_CONFIG", "指标标尺必须是对象")
    try:
        if "segments" in payload:
            compiled = compile_scale_segments(payload.get("segments"))
        else:
            colors = _colors(payload.get("colors"))
            thresholds = _thresholds(payload.get("thresholds"), len(colors))
            compiled = compile_scale_segments(segments_from_legacy(
                thresholds, colors, _direction(payload.get("direction")),
            ))
    except ScaleExpressionError as exc:
        raise http_error(422, "INVALID_GPM_SCALE_EXPRESSIONS", str(exc)) from exc
    return {
        "name": _required_text(payload, "name", "指标标尺名称", 100),
        "segments": compiled.segments,
        "thresholds": compiled.thresholds,
        "boundary_owners": compiled.boundary_owners,
        "colors": compiled.colors,
        "direction": "lower_is_better",
    }


def _compiled_row_scale(row: sqlite3.Row):
    try:
        raw_segments = json.loads(row["segments_json"])
        return compile_scale_segments(raw_segments)
    except (IndexError, KeyError, TypeError, json.JSONDecodeError, ScaleExpressionError):
        return compile_scale_segments(segments_from_legacy(
            json.loads(row["thresholds_json"]),
            json.loads(row["colors_json"]),
            row["direction"],
        ))


def _scale_dto(row: sqlite3.Row) -> dict:
    compiled = _compiled_row_scale(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "segments": compiled.segments,
        "thresholds": compiled.thresholds,
        "boundary_owners": compiled.boundary_owners,
        "colors": compiled.colors,
        "direction": "lower_is_better",
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "usage_count": row["usage_count"] if "usage_count" in row.keys() else 0,
    }


def _scale_row(connection: sqlite3.Connection, scale_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM gpm_metric_scales WHERE id = ?", (scale_id,)).fetchone()
    if not row:
        raise http_error(404, "GPM_METRIC_SCALE_NOT_FOUND", "指标标尺不存在")
    return row


def _scale_set_row(connection: sqlite3.Connection, scale_set_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM gpm_metric_scale_sets WHERE id = ?", (scale_set_id,)
    ).fetchone()
    if not row:
        raise http_error(404, "GPM_METRIC_SCALE_SET_NOT_FOUND", "指标标尺集不存在")
    return row


def _validated_set_items(connection: sqlite3.Connection, raw_items: object) -> list[dict]:
    if not isinstance(raw_items, list) or not raw_items:
        raise http_error(422, "INVALID_GPM_METRIC_SCALE_SET", "指标标尺集至少需要一个 Key")
    items: list[dict] = []
    metric_keys: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise http_error(422, "INVALID_GPM_METRIC_SCALE_SET", f"items[{index}] 必须是对象")
        metric_key = _metric_key(raw.get("metric_key"), f"items[{index}].metric_key")
        scale_id = raw.get("scale_id")
        if isinstance(scale_id, bool) or not isinstance(scale_id, int):
            raise http_error(422, "INVALID_GPM_METRIC_SCALE_SET", f"items[{index}].scale_id 必须是整数")
        _scale_row(connection, scale_id)
        if metric_key in metric_keys:
            raise http_error(422, "DUPLICATE_GPM_METRIC_SCALE_SET_KEY", "同一标尺集内指标 Key 不能重复")
        metric_keys.add(metric_key)
        items.append({"metric_key": metric_key, "scale_id": scale_id})
    return items


def _scale_set_payload(connection: sqlite3.Connection, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise http_error(422, "INVALID_GPM_METRIC_SCALE_SET", "指标标尺集必须是对象")
    return {
        "name": _required_text(payload, "name", "指标标尺集名称", 100),
        "items": _validated_set_items(connection, payload.get("items")),
    }


def _scale_set_items(connection: sqlite3.Connection, scale_set_id: int) -> list[dict]:
    return [dict(row) for row in connection.execute(
        """
        SELECT i.metric_key, i.scale_id, s.name AS scale_name
        FROM gpm_metric_scale_set_items i
        JOIN gpm_metric_scales s ON s.id = i.scale_id
        WHERE i.scale_set_id = ?
        ORDER BY i.metric_key
        """,
        (scale_set_id,),
    )]


def _replace_scale_set_items(
    connection: sqlite3.Connection, scale_set_id: int, items: list[dict],
) -> None:
    connection.execute(
        "DELETE FROM gpm_metric_scale_set_items WHERE scale_set_id = ?", (scale_set_id,)
    )
    connection.executemany(
        """
        INSERT INTO gpm_metric_scale_set_items (scale_set_id, metric_key, scale_id)
        VALUES (?, ?, ?)
        """,
        [(scale_set_id, item["metric_key"], item["scale_id"]) for item in items],
    )


def _scale_set_dto(connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
    bindings = [dict(item) for item in connection.execute(
        """
        SELECT map_name, platform, shading_quality
        FROM gpm_map_scale_set_bindings
        WHERE scale_set_id = ?
        ORDER BY map_name, platform, shading_quality DESC
        """,
        (row["id"],),
    )]
    return {
        "id": row["id"], "name": row["name"], "revision": row["revision"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "items": _scale_set_items(connection, row["id"]),
        "bindings": bindings,
    }


def _validated_map_bindings(connection: sqlite3.Connection, raw_bindings: object) -> list[dict]:
    if raw_bindings is None:
        return []
    if not isinstance(raw_bindings, list):
        raise http_error(422, "INVALID_GPM_MAP_SCALE_BINDINGS", "地图标尺绑定必须是数组")
    bindings: list[dict] = []
    scopes: set[tuple[str, int]] = set()
    for index, raw in enumerate(raw_bindings):
        if not isinstance(raw, dict):
            raise http_error(422, "INVALID_GPM_MAP_SCALE_BINDINGS", f"bindings[{index}] 必须是对象")
        platform = require_platform(raw.get("platform"), f"bindings[{index}].platform")
        quality = raw.get("shading_quality")
        if isinstance(quality, bool) or not isinstance(quality, int) or not 0 <= quality <= 5:
            raise http_error(
                422, "INVALID_GPM_MAP_SCALE_BINDINGS",
                f"bindings[{index}].shading_quality 必须在 0 到 5 之间",
            )
        scale_set_id = raw.get("scale_set_id")
        if isinstance(scale_set_id, bool) or not isinstance(scale_set_id, int):
            raise http_error(
                422, "INVALID_GPM_MAP_SCALE_BINDINGS",
                f"bindings[{index}].scale_set_id 必须是整数",
            )
        _scale_set_row(connection, scale_set_id)
        scope = (platform, quality)
        if scope in scopes:
            raise http_error(
                422, "DUPLICATE_GPM_MAP_SCALE_BINDING",
                "同一地图的平台和画质只能关联一个指标标尺集",
            )
        scopes.add(scope)
        bindings.append({
            "platform": platform, "shading_quality": quality,
            "scale_set_id": scale_set_id,
        })
    return bindings


def _expect_revision(payload: dict, current: int, code: str, label: str) -> None:
    expected = payload.get("expected_revision")
    if expected is None:
        return
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise http_error(422, "INVALID_GPM_REVISION", "expected_revision 必须是整数")
    if expected != current:
        raise http_error(409, code, f"{label}已被其他用户更新，请刷新后重试")


def _binding_revision(bindings: list[dict]) -> str:
    normalized = sorted(
        (
            str(item["platform"]), int(item["shading_quality"]), int(item["scale_set_id"]),
        )
        for item in bindings
    )
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _catalog(connection: sqlite3.Connection) -> dict:
    scales = [_scale_dto(row) for row in connection.execute(
        """
        SELECT s.*,
          (SELECT COUNT(*) FROM gpm_metric_scale_set_items i WHERE i.scale_id = s.id)
          AS usage_count
        FROM gpm_metric_scales s ORDER BY s.name COLLATE NOCASE
        """
    )]
    scale_set_rows = connection.execute(
        "SELECT * FROM gpm_metric_scale_sets ORDER BY name COLLATE NOCASE"
    ).fetchall()
    items_by_set: dict[int, list[dict]] = {row["id"]: [] for row in scale_set_rows}
    for item in connection.execute(
        """
        SELECT i.scale_set_id, i.metric_key, i.scale_id, s.name AS scale_name
        FROM gpm_metric_scale_set_items i
        JOIN gpm_metric_scales s ON s.id = i.scale_id
        ORDER BY i.scale_set_id, i.metric_key
        """
    ):
        items_by_set.setdefault(item["scale_set_id"], []).append({
            "metric_key": item["metric_key"], "scale_id": item["scale_id"],
            "scale_name": item["scale_name"],
        })
    bindings_by_set: dict[int, list[dict]] = {row["id"]: [] for row in scale_set_rows}
    bindings_by_map: dict[str, list[dict]] = {}
    for item in connection.execute(
        """
        SELECT b.map_name, b.platform, b.shading_quality, b.scale_set_id,
               s.name AS scale_set_name
        FROM gpm_map_scale_set_bindings b
        JOIN gpm_metric_scale_sets s ON s.id = b.scale_set_id
        ORDER BY b.map_name, b.platform, b.shading_quality DESC
        """
    ):
        binding = {
            "map_name": item["map_name"], "platform": item["platform"],
            "shading_quality": item["shading_quality"], "scale_set_id": item["scale_set_id"],
            "scale_set_name": item["scale_set_name"],
        }
        bindings_by_set.setdefault(item["scale_set_id"], []).append({
            key: binding[key] for key in ("map_name", "platform", "shading_quality")
        })
        bindings_by_map.setdefault(item["map_name"], []).append({
            key: binding[key]
            for key in ("platform", "shading_quality", "scale_set_id", "scale_set_name")
        })
    scale_sets = [{
        "id": row["id"], "name": row["name"], "revision": row["revision"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "items": items_by_set.get(row["id"], []),
        "bindings": bindings_by_set.get(row["id"], []),
    } for row in scale_set_rows]
    map_rows = connection.execute(
        """
        SELECT map_name, map_id FROM gpm_map_definitions
        WHERE active = 1 ORDER BY map_id, map_name COLLATE NOCASE
        """
    ).fetchall()
    maps: list[dict] = []
    for row in map_rows:
        bindings = bindings_by_map.get(row["map_name"], [])
        maps.append({
            "map_name": row["map_name"], "map_id": row["map_id"],
            "bindings": bindings,
            "binding_revision": _binding_revision(bindings),
        })
    platforms = [row[0] for row in connection.execute(
        "SELECT DISTINCT platform FROM gpm_uploads ORDER BY platform"
    )]
    quality_values = [row[0] for row in connection.execute(
        "SELECT DISTINCT shading_quality FROM gpm_uploads ORDER BY shading_quality DESC"
    )]
    return {
        "palette": FIVE_LEVEL_PALETTE,
        "platforms": platforms,
        "shading_qualities": [
            {"value": value, "label": QUALITY_LABELS.get(value, f"画质 {value}")}
            for value in quality_values
        ],
        "metric_scales": scales,
        "scale_sets": scale_sets,
        "maps": maps,
    }


@router.get("/api/gpm-heatmaps/project-config/scales")
def get_scale_catalog():
    connection = connect_gpm_database()
    try:
        return _catalog(connection)
    finally:
        connection.close()


@router.post("/api/gpm-heatmaps/project-config/metric-scales", status_code=201)
def create_metric_scale(payload: dict = Body(...)):
    item = _scale_payload(payload)
    now = _now()
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            INSERT INTO gpm_metric_scales (
                name, metric_key, thresholds_json, colors_json, segments_json, direction,
                revision, created_at, updated_at
            ) VALUES (?, '*', ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                item["name"], json.dumps(item["thresholds"]), json.dumps(item["colors"]),
                json.dumps(item["segments"], ensure_ascii=False), item["direction"], now, now,
            ),
        )
        row = _scale_row(connection, int(cursor.lastrowid))
        connection.commit()
        return _scale_dto(row)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise http_error(409, "GPM_METRIC_SCALE_NAME_EXISTS", "指标标尺名称已经存在") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.put("/api/gpm-heatmaps/project-config/metric-scales/{scale_id}")
def update_metric_scale(scale_id: int, payload: dict = Body(...)):
    item = _scale_payload(payload)
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _scale_row(connection, scale_id)
        _expect_revision(
            payload, current["revision"], "GPM_METRIC_SCALE_REVISION_CONFLICT", "指标标尺",
        )
        connection.execute(
            """
            UPDATE gpm_metric_scales SET name = ?, thresholds_json = ?, colors_json = ?,
                segments_json = ?, direction = ?, revision = revision + 1,
                updated_at = ? WHERE id = ?
            """,
            (
                item["name"], json.dumps(item["thresholds"]), json.dumps(item["colors"]),
                json.dumps(item["segments"], ensure_ascii=False), item["direction"],
                _now(), scale_id,
            ),
        )
        row = _scale_row(connection, scale_id)
        connection.commit()
        return _scale_dto(row)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise http_error(409, "GPM_METRIC_SCALE_NAME_EXISTS", "指标标尺名称已经存在") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.delete("/api/gpm-heatmaps/project-config/metric-scales/{scale_id}")
def delete_metric_scale(scale_id: int):
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        _scale_row(connection, scale_id)
        usage = connection.execute(
            "SELECT COUNT(*) FROM gpm_metric_scale_set_items WHERE scale_id = ?", (scale_id,)
        ).fetchone()[0]
        if usage:
            raise http_error(409, "GPM_METRIC_SCALE_IN_USE", "指标标尺仍被指标标尺集引用")
        connection.execute("DELETE FROM gpm_metric_scales WHERE id = ?", (scale_id,))
        connection.commit()
        return {"deleted": True, "id": scale_id}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.post("/api/gpm-heatmaps/project-config/metric-scale-sets", status_code=201)
def create_metric_scale_set(payload: dict = Body(...)):
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        item = _scale_set_payload(connection, payload)
        now = _now()
        cursor = connection.execute(
            """
            INSERT INTO gpm_metric_scale_sets (name, revision, created_at, updated_at)
            VALUES (?, 1, ?, ?)
            """,
            (item["name"], now, now),
        )
        scale_set_id = int(cursor.lastrowid)
        _replace_scale_set_items(connection, scale_set_id, item["items"])
        connection.commit()
        return _scale_set_dto(connection, _scale_set_row(connection, scale_set_id))
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise http_error(409, "GPM_METRIC_SCALE_SET_NAME_EXISTS", "指标标尺集名称已经存在") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.put("/api/gpm-heatmaps/project-config/metric-scale-sets/{scale_set_id}")
def update_metric_scale_set(scale_set_id: int, payload: dict = Body(...)):
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _scale_set_row(connection, scale_set_id)
        _expect_revision(
            payload, current["revision"], "GPM_METRIC_SCALE_SET_REVISION_CONFLICT", "指标标尺集",
        )
        item = _scale_set_payload(connection, payload)
        connection.execute(
            """
            UPDATE gpm_metric_scale_sets SET name = ?, revision = revision + 1,
                updated_at = ? WHERE id = ?
            """,
            (item["name"], _now(), scale_set_id),
        )
        _replace_scale_set_items(connection, scale_set_id, item["items"])
        connection.commit()
        return _scale_set_dto(connection, _scale_set_row(connection, scale_set_id))
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise http_error(409, "GPM_METRIC_SCALE_SET_NAME_EXISTS", "指标标尺集名称已经存在") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.delete("/api/gpm-heatmaps/project-config/metric-scale-sets/{scale_set_id}")
def delete_metric_scale_set(scale_set_id: int):
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        _scale_set_row(connection, scale_set_id)
        bound = connection.execute(
            "SELECT COUNT(*) FROM gpm_map_scale_set_bindings WHERE scale_set_id = ?",
            (scale_set_id,),
        ).fetchone()[0]
        if bound:
            raise http_error(409, "GPM_METRIC_SCALE_SET_IN_USE", "指标标尺集仍被地图作用域关联")
        connection.execute("DELETE FROM gpm_metric_scale_sets WHERE id = ?", (scale_set_id,))
        connection.commit()
        return {"deleted": True, "id": scale_set_id}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.put("/api/gpm-heatmaps/project-config/maps/{map_name}/scale-bindings")
def update_map_scale_bindings(map_name: str, payload: dict = Body(...)):
    map_name = require_identifier(map_name, "map_name")
    if not isinstance(payload, dict):
        raise http_error(422, "INVALID_GPM_MAP_SCALE_BINDINGS", "地图标尺绑定必须是对象")
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        exists = connection.execute(
            "SELECT 1 FROM gpm_map_definitions WHERE map_name = ? AND active = 1", (map_name,)
        ).fetchone()
        if not exists:
            raise http_error(404, "GPM_MAP_DEFINITION_NOT_FOUND", "项目地图不存在")
        current_bindings = [dict(row) for row in connection.execute(
            """
            SELECT platform, shading_quality, scale_set_id
            FROM gpm_map_scale_set_bindings WHERE map_name = ?
            """,
            (map_name,),
        )]
        expected_revision = payload.get("expected_revision")
        if expected_revision is not None:
            if not isinstance(expected_revision, str):
                raise http_error(422, "INVALID_GPM_REVISION", "expected_revision 必须是字符串")
            if expected_revision != _binding_revision(current_bindings):
                raise http_error(
                    409, "GPM_MAP_BINDING_REVISION_CONFLICT",
                    "地图应用已被其他用户更新，请刷新后重试",
                )
        bindings = _validated_map_bindings(connection, payload.get("bindings"))
        now = _now()
        connection.execute("DELETE FROM gpm_map_scale_set_bindings WHERE map_name = ?", (map_name,))
        connection.executemany(
            """
            INSERT INTO gpm_map_scale_set_bindings (
                map_name, platform, shading_quality, scale_set_id, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (map_name, item["platform"], item["shading_quality"], item["scale_set_id"], now)
                for item in bindings
            ],
        )
        connection.commit()
        return {
            "map_name": map_name, "bindings": bindings,
            "binding_revision": _binding_revision(bindings),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _configured_scale_dto(
    row: sqlite3.Row, scale_set_id: int, scale_set_name: str,
) -> dict:
    compiled = _compiled_row_scale(row)
    return {
        "mode": "configured",
        "palette": {
            "id": f"gpm-scale-{row['id']}-v{row['revision']}",
            "colors": compiled.colors,
            "labels": [f"区间 {index + 1}" for index in range(len(compiled.colors))],
        },
        "thresholds": compiled.thresholds,
        "boundary_owners": compiled.boundary_owners,
        "direction": "lower_is_better",
        "source": {
            "type": "scale_set",
            "scale_id": row["id"],
            "scale_name": row["name"],
            "scale_set_id": scale_set_id,
            "scale_set_name": scale_set_name,
        },
    }


def resolve_heat_scales(
    connection: sqlite3.Connection,
    *,
    map_name: str,
    platform: str,
    shading_quality: int,
    heat_map: list[dict],
    points: list[dict],
) -> dict[str, dict]:
    """按地图、平台、画质选择标尺集，再用上报 Key 精确匹配指标标尺。"""

    binding = connection.execute(
        """
        SELECT b.scale_set_id, s.name
        FROM gpm_map_scale_set_bindings b
        JOIN gpm_metric_scale_sets s ON s.id = b.scale_set_id
        WHERE b.map_name = ? AND b.platform = ? AND b.shading_quality = ?
        """,
        (map_name, platform, shading_quality),
    ).fetchone()
    configured: dict[str, dict] = {}
    if binding:
        rows = connection.execute(
            """
            SELECT i.metric_key AS assigned_metric_key, s.*
            FROM gpm_metric_scale_set_items i
            JOIN gpm_metric_scales s ON s.id = i.scale_id
            WHERE i.scale_set_id = ?
            """,
            (binding["scale_set_id"],),
        ).fetchall()
        configured = {
            row["assigned_metric_key"]: _configured_scale_dto(
                row, binding["scale_set_id"], binding["name"],
            )
            for row in rows
        }

    result: dict[str, dict] = {}
    for metric in heat_map:
        metric_key = str(metric.get("key") or "")
        if not metric_key:
            continue
        if metric_key in configured:
            result[metric_key] = configured[metric_key]
            continue
        values = []
        for point in points:
            value = point.get("heat_map_data", {}).get(metric_key)
            if isinstance(value, bool) or value is None or value == "":
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number)
        result[metric_key] = {
            "mode": "dynamic",
            "palette": {
                "id": "gpm-linear-v1",
                "colors": [FIVE_LEVEL_PALETTE["colors"][0], FIVE_LEVEL_PALETTE["colors"][-1]],
                "labels": ["低", "高"],
            },
            "range": [min(values), max(values)] if values else [0, 0],
            "source": {
                "type": "dynamic", "scale_id": None, "scale_name": None,
                "scale_set_id": None, "scale_set_name": None,
            },
        }
    return result
