import pytest

from app.gpm_scale_expressions import (
    ScaleExpressionError,
    compile_scale_segments,
)


def test_scale_expressions_preserve_list_order_and_compile_runtime_intervals():
    compiled = compile_scale_segments([
        {"color": "#ff0000", "expression": ">= 390"},
        {"color": "#00ffff", "expression": ">=365 & <390"},
        {"color": "#00ff00", "expression": "<365"},
    ])

    assert compiled.segments == [
        {"color": "#ff0000", "expression": ">=390"},
        {"color": "#00ffff", "expression": ">=365 & <390"},
        {"color": "#00ff00", "expression": "<365"},
    ]
    assert compiled.colors == ["#00ff00", "#00ffff", "#ff0000"]


def test_scale_expressions_preserve_lower_segment_boundary_ownership():
    compiled = compile_scale_segments([
        {"color": "#00ff00", "expression": "<=100"},
        {"color": "#ff0000", "expression": ">100"},
    ])

    assert compiled.segments == [
        {"color": "#00ff00", "expression": "<=100"},
        {"color": "#ff0000", "expression": ">100"},
    ]


@pytest.mark.parametrize(
    ("segments", "message"),
    [
        ([
            {"color": "#00ff00", "expression": "<365"},
            {"color": "#00ffff", "expression": ">365 & <390"},
            {"color": "#ff0000", "expression": ">=390"},
        ], "边界 365 不属于任何颜色段"),
        ([
            {"color": "#00ff00", "expression": "<=365"},
            {"color": "#00ffff", "expression": ">=365 & <390"},
            {"color": "#ff0000", "expression": ">=390"},
        ], "边界 365 同时属于两个颜色段"),
        ([
            {"color": "#00ff00", "expression": "<365"},
            {"color": "#00ffff", "expression": ">=360 & <390"},
            {"color": "#ff0000", "expression": ">=390"},
        ], "区间在 360 附近发生重叠"),
    ],
)
def test_scale_expressions_reject_gaps_and_overlaps(segments, message):
    with pytest.raises(ScaleExpressionError, match=message):
        compile_scale_segments(segments)
