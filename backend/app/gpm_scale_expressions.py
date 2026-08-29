"""GPMHeatmap 颜色区间表达式的解析与编译。

模块接口只接受当前表达式结构；语法、边界归属、完整覆盖与冲突判定全部封装
在这里，调用方不需要理解区间实现。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


MIN_SEGMENTS = 2
MAX_SEGMENTS = 10
DEFAULT_SEGMENTS = [
    {"color": "#52e817", "expression": "<100"},
    {"color": "#b7f400", "expression": ">=100 & <200"},
    {"color": "#ffb20a", "expression": ">=200 & <300"},
    {"color": "#ff4a0a", "expression": ">=300 & <400"},
    {"color": "#ff1111", "expression": ">=400"},
]

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
    """解析颜色段并返回规范化表达式与按数值升序的颜色。"""

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
        colors=[interval.color for interval in ordered_intervals],
    )


def default_scale_segments() -> list[dict]:
    return [dict(segment) for segment in DEFAULT_SEGMENTS]
