"""程序化生成"废墟都市"风格演示截图(种子数据用)。

variant 含义:
  0 = 基线
  1 = 楼体位移 + 曝光偏移(模拟渲染回归,失败级)
  2 = 轻微噪声 + 亮度微调(警告级)
"""
from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageDraw

W, H = 960, 540


def generate_scene(path: str, seed: int, night: bool = False, variant: int = 0) -> None:
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H))
    dr = ImageDraw.Draw(img, "RGBA")

    # 天空渐变
    top, bottom = ((10, 18, 48), (42, 53, 88)) if night else ((174, 191, 212), (223, 230, 234))
    for y in range(H):
        t = y / H
        dr.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))

    if night:
        for _ in range(80):
            x, y = rnd.uniform(0, W), rnd.uniform(0, H * 0.45)
            dr.point((x, y), fill=(255, 255, 255, 200))

    # 三层楼群
    for layer in range(3):
        if night:
            col = (26 + layer * 8, 34 + layer * 10, 56 + layer * 12)
        else:
            col = (120 - layer * 18, 134 - layer * 16, 148 - layer * 14)
        horizon = H * (0.42 + layer * 0.09)
        x = -20.0
        while x < W + 40:
            bw = 30 + rnd.random() * 70
            bh = H * (0.12 + rnd.random() * 0.3) * (1 + layer * 0.25)
            shift = -H * 0.06 if (variant == 1 and W * 0.3 < x < W * 0.45) else 0
            dr.rectangle([x, horizon - bh + shift, x + bw, H], fill=col)
            if rnd.random() > 0.55:
                dr.rectangle([x + bw * 0.2, horizon - bh + shift - 8, x + bw * 0.45, horizon - bh + shift], fill=col)
            if layer == 2:  # 窗(独立随机源:循环次数随 shift 变化,不能影响主序列)
                wrnd = random.Random(seed * 31 + int(x) * 7)
                win = (255, 220, 120, 130) if night else (255, 255, 255, 64)
                wy = horizon - bh + shift + 10
                while wy < horizon - 14:
                    wx = x + 5
                    while wx < x + bw - 8:
                        if wrnd.random() > 0.6:
                            dr.rectangle([wx, wy, wx + 5, wy + 7], fill=win)
                        wx += 12
                    wy += 14
            x += bw + rnd.random() * 24

    # 植被
    veg = (28, 51, 34) if night else (74, 110, 63)
    for _ in range(26):
        gx, gy = rnd.uniform(0, W), H * (0.62 + rnd.random() * 0.1)
        gr = 8 + rnd.random() * 26
        dr.ellipse([gx - gr, gy - gr, gx + gr, gy], fill=veg)

    # 地面
    g_top, g_bot = ((21, 32, 61), (11, 18, 38)) if night else ((142, 154, 163), (93, 106, 114))
    for y in range(int(H * 0.68), H):
        t = (y - H * 0.68) / (H * 0.32)
        dr.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(g_top, g_bot)))

    # 碎石板
    for _ in range(18):
        px, py = rnd.uniform(0, W), H * (0.72 + rnd.random() * 0.24)
        pw, ph = 30 + rnd.random() * 80, 8 + rnd.random() * 16
        if night:
            col = (int(40 + rnd.random() * 20), int(50 + rnd.random() * 20), int(70 + rnd.random() * 20))
        else:
            col = (int(110 + rnd.random() * 40), int(118 + rnd.random() * 40), int(124 + rnd.random() * 40))
        dr.polygon(
            [(px, py), (px + pw, py - ph * 0.3), (px + pw * 0.9, py + ph), (px - pw * 0.08, py + ph * 0.8)],
            fill=col,
        )

    # 水洼反光
    glow = (120, 160, 255, 30) if night else (255, 255, 255, 46)
    for _ in range(6):
        cx, cy = rnd.uniform(0, W), H * (0.78 + rnd.random() * 0.16)
        rx, ry = 30 + rnd.random() * 60, 6 + rnd.random() * 10
        dr.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=glow)

    arr = np.asarray(img, dtype=np.float32)

    if variant == 1:  # 轻微曝光偏移(低于像素阈值,主要差异来自楼体位移)
        arr = np.clip(arr * 1.015 + 2, 0, 255)
    elif variant == 2:  # 轻噪声(少量像素越过阈值,警告级)
        noise = np.random.default_rng(seed).normal(0, 3.2, arr.shape)
        arr = np.clip(arr + noise, 0, 255)

    # 暗角
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    vignette = np.clip(1 - 0.3 * np.clip(d - 0.5, 0, 1) ** 2, 0, 1)
    arr *= vignette[..., None]

    Image.fromarray(arr.astype(np.uint8)).save(path)
