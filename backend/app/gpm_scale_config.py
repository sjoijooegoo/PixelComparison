"""GPMHeatmap 指标标尺、指标标尺集与地图作用域绑定。

调用方只请求最终标尺；标尺集匹配和动态回退均封装在本模块中。
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Body

from .gpm_common import QUALITY_LABELS, http_error
from .gpm_map_config import list_map_definitions
from .gpm_scale_expressions import (
    ScaleExpressionError,
    compile_scale_segments,
)
from .gpm_storage import connect_gpm_database


router = APIRouter()

FIVE_LEVEL_PALETTE = {
    "id": "gpm-five-v1",
    "colors": ["#52e817", "#b7f400", "#ffb20a", "#ff4a0a", "#ff1111"],
    "labels": ["优秀", "良好", "可接受", "关注", "超标"],
}
_CONFIG_ID_TABLES = frozenset({"gpm_metric_scales", "gpm_metric_scale_sets"})


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _next_config_id(connection: sqlite3.Connection, table_name: str) -> int:
    """在调用方持有 BEGIN IMMEDIATE 写锁时分配单调递增的配置 ID。"""

    if table_name not in _CONFIG_ID_TABLES:
        raise ValueError(f"不支持的 GPM 配置 ID 表: {table_name}")
    return int(connection.execute(
        f"SELECT COALESCE(MAX(id), -1) + 1 FROM {table_name}"
    ).fetchone()[0])


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


def _scale_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise http_error(422, "INVALID_GPM_SCALE_CONFIG", "指标标尺必须是对象")
    try:
        compiled = compile_scale_segments(payload.get("segments"))
    except ScaleExpressionError as exc:
        raise http_error(422, "INVALID_GPM_SCALE_EXPRESSIONS", str(exc)) from exc
    return {
        "name": _required_text(payload, "name", "指标标尺名称", 100),
        "segments": compiled.segments,
    }


def _compiled_row_scale(row: sqlite3.Row):
    return compile_scale_segments(json.loads(row["segments_json"]))


def _scale_dto(row: sqlite3.Row) -> dict:
    compiled = _compiled_row_scale(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "segments": compiled.segments,
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
        -- 条目表按用户提交顺序整组重建，rowid 是当前最终 schema 中的
        -- 顺序载体；普通读写和配置包导入导出必须统一按它读取。
        ORDER BY i.rowid
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


def _expect_revision(payload: dict, current: int, code: str, label: str) -> None:
    expected = payload.get("expected_revision")
    if expected is None:
        return
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise http_error(422, "INVALID_GPM_REVISION", "expected_revision 必须是整数")
    if expected != current:
        raise http_error(409, code, f"{label}已被其他用户更新，请刷新后重试")


def _catalog(connection: sqlite3.Connection) -> dict:
    scales = [_scale_dto(row) for row in connection.execute(
        """
        SELECT s.*,
          (SELECT COUNT(*) FROM gpm_metric_scale_set_items i WHERE i.scale_id = s.id)
          AS usage_count
        FROM gpm_metric_scales s ORDER BY s.id
        """
    )]
    scale_set_rows = connection.execute(
        "SELECT * FROM gpm_metric_scale_sets ORDER BY id"
    ).fetchall()
    items_by_set: dict[int, list[dict]] = {row["id"]: [] for row in scale_set_rows}
    for item in connection.execute(
        """
        SELECT i.scale_set_id, i.metric_key, i.scale_id, s.name AS scale_name
        FROM gpm_metric_scale_set_items i
        JOIN gpm_metric_scales s ON s.id = i.scale_id
        ORDER BY i.scale_set_id, i.rowid
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
    maps: list[dict] = []
    for definition in list_map_definitions(connection, include_bindings=False):
        bindings = bindings_by_map.get(definition["map_name"], [])
        maps.append({
            **definition,
            "bindings": bindings,
        })
    return {
        "palette": FIVE_LEVEL_PALETTE,
        "platforms": ["IOS", "Android", "Windows"],
        "shading_qualities": [
            {"value": value, "label": QUALITY_LABELS.get(value, f"画质 {value}")}
            for value in range(5, -1, -1)
        ],
        "metric_scales": scales,
        "scale_sets": scale_sets,
        "maps": maps,
    }


@router.get("/api/gpm-heatmaps/configuration")
def get_scale_catalog():
    connection = connect_gpm_database()
    try:
        return _catalog(connection)
    finally:
        connection.close()


@router.post("/api/gpm-heatmaps/configuration/scales", status_code=201)
def create_metric_scale(payload: dict = Body(...)):
    item = _scale_payload(payload)
    now = _now()
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        scale_id = _next_config_id(connection, "gpm_metric_scales")
        connection.execute(
            """
            INSERT INTO gpm_metric_scales (id, name, segments_json, revision, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (
                scale_id, item["name"], json.dumps(item["segments"], ensure_ascii=False), now, now,
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


@router.put("/api/gpm-heatmaps/configuration/scales/{scale_id}")
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
            UPDATE gpm_metric_scales SET name = ?, segments_json = ?,
                revision = revision + 1, updated_at = ? WHERE id = ?
            """,
            (
                item["name"], json.dumps(item["segments"], ensure_ascii=False), _now(), scale_id,
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


@router.delete("/api/gpm-heatmaps/configuration/scales/{scale_id}")
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


@router.post("/api/gpm-heatmaps/configuration/scale-sets", status_code=201)
def create_metric_scale_set(payload: dict = Body(...)):
    connection = connect_gpm_database()
    try:
        connection.execute("BEGIN IMMEDIATE")
        item = _scale_set_payload(connection, payload)
        now = _now()
        scale_set_id = _next_config_id(connection, "gpm_metric_scale_sets")
        connection.execute(
            """
            INSERT INTO gpm_metric_scale_sets (id, name, revision, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (scale_set_id, item["name"], now, now),
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


@router.put("/api/gpm-heatmaps/configuration/scale-sets/{scale_set_id}")
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


@router.delete("/api/gpm-heatmaps/configuration/scale-sets/{scale_set_id}")
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
        "segments": compiled.segments,
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
