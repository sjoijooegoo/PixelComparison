"""对比算法可配置参数:默认值 + 持久化读写。

参数存于 settings 表单行(id=1, JSON);未设置时回落到 DEFAULT_SETTINGS。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Setting

DEFAULT_SETTINGS: dict = {
    "pixel_diff_threshold": 8,     # 单像素通道差 > 此值才算"差异像素"
    "fail_threshold": 2.0,         # 差异率 >= 此值 -> 红色(原"失败"级)
    "warn_threshold": 0.3,         # 差异率 >= 此值 -> 橙色(原"警告"级)
    "heatmap_blur": 6,             # 热力图高斯模糊半径
    "heatmap_sensitivity": 0.25,   # 热力图归一化下限(越小越灵敏,越易显红)
}

# 各参数允许范围 (min, max),保存时夹紧
RANGES: dict = {
    "pixel_diff_threshold": (0, 255),
    "fail_threshold": (0.0, 100.0),
    "warn_threshold": (0.0, 100.0),
    "heatmap_blur": (0, 50),
    "heatmap_sensitivity": (0.01, 1.0),
}


def get_settings(db: Session) -> dict:
    """返回当前配置(默认值 + 已存储覆盖)。"""
    data = dict(DEFAULT_SETTINGS)
    row = db.get(Setting, 1)
    if row and row.payload:
        data.update({k: v for k, v in row.payload.items() if k in DEFAULT_SETTINGS})
    return data


def save_settings(db: Session, patch: dict) -> dict:
    """合并并夹紧后持久化,返回保存后的完整配置。"""
    data = get_settings(db)
    for k, v in patch.items():
        if k not in DEFAULT_SETTINGS or v is None:
            continue
        lo, hi = RANGES[k]
        data[k] = max(lo, min(hi, v))
    row = db.get(Setting, 1)
    if row:
        row.payload = dict(data)   # 重新赋值以触发 JSON 列更新
    else:
        db.add(Setting(id=1, payload=dict(data)))
    db.commit()
    return data
