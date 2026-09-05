"""在线与离线共用的标尺读模型，不依赖数据库或 Web 框架。"""

from __future__ import annotations

import math

from .gpm_scale_expressions import compile_scale_segments


def configured_scale_dto(
    row, scale_set_id: int, scale_set_name: str,
) -> dict:
    compiled = compile_scale_segments(row["segments"])
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


def resolve_metric_scales(heat_map: list[dict], points: list[dict], configured: dict[str, dict]) -> dict[str, dict]:
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
                "colors": ["#52e817", "#ff1111"],
                "labels": ["低", "高"],
            },
            "range": [min(values), max(values)] if values else [0, 0],
            "source": {
                "type": "dynamic", "scale_id": None, "scale_name": None,
                "scale_set_id": None, "scale_set_name": None,
            },
        }
    return result
