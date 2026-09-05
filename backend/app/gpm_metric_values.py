"""在线和离线热力图共用的有限数值及变化率计算。"""

import math


def finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def metric_change_percentages(current_metrics: dict, previous_metrics: dict | None) -> dict[str, float]:
    if not previous_metrics:
        return {}
    changes = {}
    for key, current_value in current_metrics.items():
        current_number = finite_number(current_value)
        previous_number = finite_number(previous_metrics.get(key))
        if current_number is None or previous_number is None or previous_number == 0:
            continue
        change = (current_number - previous_number) / abs(previous_number) * 100
        if math.isfinite(change):
            changes[key] = change
    return changes
