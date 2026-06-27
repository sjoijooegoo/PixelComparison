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
    "heatmap_sensitivity": 0.25,   # 热力图归一化下限(越小越灵敏,越易显红);仅 legacy 方法用
    # 热力图渲染方法:enhanced=绝对幅度+gamma+密度门控(强化区域感/抑噪);legacy=旧峰值归一化
    "heatmap_method": "enhanced",
    "heatmap_norm_scale": 80.0,    # enhanced:绝对量程,越小越敏感(差异除以此值)
    "heatmap_gamma": 1.4,          # enhanced:低端抑制强度(>1 压弱信号)
    "heatmap_density_radius": 16.0,  # enhanced:密度门控的邻域尺度
    "heatmap_density_floor": 0.2,  # enhanced:散点容忍下限(邻域变化密度低于此值被压)
    "default_shading_quality": 5,  # 筛选默认画质;-1 表示「全部画质」(不筛选)
    "default_date_range_days": 7,  # 筛选默认日期范围:最近 N 天
    # 筛选框画质下拉显示哪几档(value 列表);默认全显,与无配置时一致
    "filter_shading_qualities": [5, 4, 3, 2, 1, 0],
}

# 画质合法档位(0=节能 … 5=电影);用于 filter_shading_qualities 规整
VALID_SHADING_QUALITIES = frozenset(range(0, 6))

# 非数值参数的合法取值(save 时校验)
ENUMS: dict = {
    "heatmap_method": ("enhanced", "legacy"),
}

# 各参数允许范围 (min, max),保存时夹紧
RANGES: dict = {
    "pixel_diff_threshold": (0, 255),
    "fail_threshold": (0.0, 100.0),
    "warn_threshold": (0.0, 100.0),
    "heatmap_blur": (0, 50),
    "heatmap_sensitivity": (0.01, 1.0),
    "heatmap_norm_scale": (4.0, 255.0),
    "heatmap_gamma": (0.5, 4.0),
    "heatmap_density_radius": (0.0, 60.0),
    "heatmap_density_floor": (0.0, 0.9),
    "default_shading_quality": (-1, 5),
    "default_date_range_days": (1, 365),
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
        if k == "filter_shading_qualities":
            # 规整:去重、仅保留合法档位、降序;空集则忽略本次(保留原值,避免下拉为空)
            cleaned = sorted({q for q in v if q in VALID_SHADING_QUALITIES}, reverse=True)
            if cleaned:
                data[k] = cleaned
            continue
        if k in ENUMS:
            if v in ENUMS[k]:
                data[k] = v
            continue
        lo, hi = RANGES[k]
        data[k] = max(lo, min(hi, v))
    # 一致性:默认画质必须落在可见集合内(或 -1 全部画质),否则回退为 -1
    if data["default_shading_quality"] != -1 \
            and data["default_shading_quality"] not in data["filter_shading_qualities"]:
        data["default_shading_quality"] = -1
    row = db.get(Setting, 1)
    if row:
        row.payload = dict(data)   # 重新赋值以触发 JSON 列更新
    else:
        db.add(Setting(id=1, payload=dict(data)))
    db.commit()
    return data
