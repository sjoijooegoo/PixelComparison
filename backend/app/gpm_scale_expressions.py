"""GPMHeatmap 颜色区间表达式的解析与编译。

模块接口只暴露“表达式列表 -> 可执行标尺”和旧标尺转换；语法、边界归属、
完整覆盖与冲突判定都集中在这里，接口层和迁移代码无需重复解释表达式。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


MIN_SEGMENTS = 2
MAX_SEGMENTS = 10
DEFAULT_COLORS = ["#52e817", "#b7f400", "#ffb20a", "#ff4a0a", "#ff1111"]
DEFAULT_THRESHOLDS = [100.0, 200.0, 300.0, 400.0]

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_COMPARISON = re.compile(rf"^(<=|>=|<|>)\s*({_NUMBER})$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ScaleExpressionError(ValueError):
    """标尺表达式无法形成无缝且无重叠的完整数轴覆盖。"""


@dataclass(frozen=True)
class _Bound:
    value: float
    inclusive: bool


@dataclass(frozen=True)
class _Interval:
    color: str
    lower: _Bound | None
    upper: _Bound | None


@dataclass(frozen=True)
class CompiledScale:
    segments: list[dict]
    thresholds: list[float]
    boundary_owners: list[str]
    colors: list[str]


def _number_text(value: float) -> str:
    if value == 0:
        return "0"
    return format(value, ".15g")


def _parse_expression(expression: object, row_number: int) -> _Interval:
    text = str(expression or "").strip().replace("≤", "<=").replace("≥", ">=")
    if not text:
        raise ScaleExpressionError(f"颜色段 {row_number} 的区间表达式不能为空")
    parts = [part.strip() for part in text.split("&")]
    if not 1 <= len(parts) <= 2 or any(not part for part in parts):
        raise ScaleExpressionError(
            f"颜色段 {row_number} 的表达式格式不正确；示例：<365 或 >=365 & <390"
        )

    lower: _Bound | None = None
    upper: _Bound | None = None
    for part in parts:
        match = _COMPARISON.fullmatch(part)
        if not match:
            raise ScaleExpressionError(
                f"颜色段 {row_number} 的表达式“{text}”无法解析；仅支持 <、<=、>、>= 和 &"
            )
        operator, raw_number = match.groups()
        number = float(raw_number)
        if not math.isfinite(number):
            raise ScaleExpressionError(f"颜色段 {row_number} 的边界必须是有限数字")
        if operator.startswith(">"):
            if lower is not None:
                raise ScaleExpressionError(f"颜色段 {row_number} 只能包含一个下界")
            lower = _Bound(number, operator == ">=")
        else:
            if upper is not None:
                raise ScaleExpressionError(f"颜色段 {row_number} 只能包含一个上界")
            upper = _Bound(number, operator == "<=")

    if lower and upper:
        if lower.value > upper.value:
            raise ScaleExpressionError(f"颜色段 {row_number} 的下界不能大于上界")
        if lower.value == upper.value:
            raise ScaleExpressionError(f"颜色段 {row_number} 不能是空区间或单点区间")
    return _Interval("", lower, upper)


def _canonical_expression(interval: _Interval) -> str:
    terms: list[str] = []
    if interval.lower:
        terms.append((">=" if interval.lower.inclusive else ">") + _number_text(interval.lower.value))
    if interval.upper:
        terms.append(("<=" if interval.upper.inclusive else "<") + _number_text(interval.upper.value))
    return " & ".join(terms)


def _sort_key(interval: _Interval) -> tuple[float, int]:
    if interval.lower is None:
        return (-math.inf, 0)
    return (interval.lower.value, 0 if interval.lower.inclusive else 1)


def compile_scale_segments(value: object) -> CompiledScale:
    """解析颜色段并返回按数值升序规范化的表达式和运行时阈值。"""

    if not isinstance(value, list) or not MIN_SEGMENTS <= len(value) <= MAX_SEGMENTS:
        raise ScaleExpressionError(f"颜色标尺必须包含 {MIN_SEGMENTS} 到 {MAX_SEGMENTS} 个颜色段")

    intervals: list[_Interval] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ScaleExpressionError(f"颜色段 {index} 必须是对象")
        color = str(raw.get("color") or "").strip().lower()
        if not _COLOR.fullmatch(color):
            raise ScaleExpressionError(f"颜色段 {index} 的颜色必须使用 #RRGGBB 格式")
        parsed = _parse_expression(raw.get("expression"), index)
        intervals.append(_Interval(color, parsed.lower, parsed.upper))

    ordered_intervals = sorted(intervals, key=_sort_key)
    if ordered_intervals[0].lower is not None:
        raise ScaleExpressionError("第一个颜色段必须没有下界，例如 <365")
    if ordered_intervals[-1].upper is not None:
        raise ScaleExpressionError("最后一个颜色段必须没有上界，例如 >=440")

    for left, right in zip(ordered_intervals, ordered_intervals[1:]):
        if left.upper is None:
            raise ScaleExpressionError(
                f"区间“{_canonical_expression(left)}”会覆盖其后的颜色段"
            )
        if right.lower is None:
            raise ScaleExpressionError("只能有一个没有下界的颜色段")
        if left.upper.value < right.lower.value:
            raise ScaleExpressionError(
                f"{_number_text(left.upper.value)} 到 {_number_text(right.lower.value)} 之间没有颜色覆盖"
            )
        if left.upper.value > right.lower.value:
            raise ScaleExpressionError(
                f"区间在 {_number_text(right.lower.value)} 附近发生重叠"
            )
        if left.upper.inclusive and right.lower.inclusive:
            raise ScaleExpressionError(
                f"边界 {_number_text(left.upper.value)} 同时属于两个颜色段"
            )
        if not left.upper.inclusive and not right.lower.inclusive:
            raise ScaleExpressionError(
                f"边界 {_number_text(left.upper.value)} 不属于任何颜色段；请将一侧改为 <= 或 >="
            )

    return CompiledScale(
        segments=[
            {"color": interval.color, "expression": _canonical_expression(interval)}
            for interval in intervals
        ],
        thresholds=[
            interval.upper.value for interval in ordered_intervals[:-1] if interval.upper
        ],
        # A shared boundary belongs to exactly one adjacent segment. Preserve that
        # ownership so clients do not silently turn ``<= n / > n`` into
        # ``< n / >= n`` when they render or evaluate the scale.
        boundary_owners=[
            "lower" if interval.upper and interval.upper.inclusive else "upper"
            for interval in ordered_intervals[:-1]
        ],
        colors=[interval.color for interval in ordered_intervals],
    )


def segments_from_legacy(
    thresholds: object,
    colors: object,
    direction: object = "lower_is_better",
) -> list[dict]:
    """把旧阈值标尺转换为等价的表达式列表。"""

    if not isinstance(colors, list) or not MIN_SEGMENTS <= len(colors) <= MAX_SEGMENTS:
        colors = list(DEFAULT_COLORS)
    if not isinstance(thresholds, list) or len(thresholds) != len(colors) - 1:
        thresholds = list(DEFAULT_THRESHOLDS)
        colors = list(DEFAULT_COLORS)

    numeric_thresholds: list[float] = []
    for item in thresholds:
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise ScaleExpressionError("旧标尺阈值无法转换为区间表达式") from exc
        if not math.isfinite(number):
            raise ScaleExpressionError("旧标尺阈值无法转换为区间表达式")
        numeric_thresholds.append(number)
    if any(right <= left for left, right in zip(numeric_thresholds, numeric_thresholds[1:])):
        raise ScaleExpressionError("旧标尺阈值必须严格递增")

    normalized_colors = [str(color).strip().lower() for color in colors]
    if str(direction or "lower_is_better") == "higher_is_better":
        normalized_colors.reverse()

    segments: list[dict] = []
    for index, color in enumerate(normalized_colors):
        if index == 0:
            expression = f"<{_number_text(numeric_thresholds[0])}"
        elif index == len(normalized_colors) - 1:
            expression = f">={_number_text(numeric_thresholds[-1])}"
        else:
            expression = (
                f">={_number_text(numeric_thresholds[index - 1])}"
                f" & <{_number_text(numeric_thresholds[index])}"
            )
        segments.append({"color": color, "expression": expression})
    return compile_scale_segments(segments).segments


def default_scale_segments() -> list[dict]:
    return segments_from_legacy(DEFAULT_THRESHOLDS, DEFAULT_COLORS)
