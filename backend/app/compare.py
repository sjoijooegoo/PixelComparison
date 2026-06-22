"""图片对比引擎:差异指标、热力图、直方图。

仅依赖 Pillow + numpy,便于本地跑通;生产环境可替换为
OpenCV / scikit-image(windowed SSIM)实现。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

# 单像素任一通道差值超过该阈值则计为"差异像素"
PIXEL_DIFF_THRESHOLD = 8

# 热力图为纯展示派生物(不参与对比),用 WebP 有损压缩省盘;q90 观感无损
HEATMAP_WEBP_QUALITY = 90

# jet 色带控制点 (位置, RGB)
_JET = [
    (0.00, (27, 27, 179)),
    (0.25, (0, 179, 255)),
    (0.50, (0, 210, 106)),
    (0.75, (255, 224, 0)),
    (0.90, (255, 106, 0)),
    (1.00, (224, 0, 0)),
]


def _jet_colormap(norm: np.ndarray) -> np.ndarray:
    """norm: HxW float [0,1] -> HxWx3 uint8"""
    out = np.zeros((*norm.shape, 3), dtype=np.float32)
    for (p0, c0), (p1, c1) in zip(_JET[:-1], _JET[1:]):
        mask = (norm >= p0) & (norm <= p1)
        t = np.zeros_like(norm)
        span = p1 - p0
        t[mask] = (norm[mask] - p0) / span
        for ch in range(3):
            out[..., ch][mask] = c0[ch] + (c1[ch] - c0[ch]) * t[mask]
    return out.astype(np.uint8)


def _global_ssim(a: np.ndarray, b: np.ndarray) -> float:
    """简化版全局 SSIM(灰度)。生产可换 skimage.metrics.structural_similarity。"""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = a.mean(), b.mean()
    var_a, var_b = a.var(), b.var()
    cov = ((a - mu_a) * (b - mu_b)).mean()
    return float(
        ((2 * mu_a * mu_b + c1) * (2 * cov + c2))
        / ((mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2))
    )


def _histogram(arr: np.ndarray, bins: int = 32) -> list[list[int]]:
    """RGB 各通道直方图,返回 3 x bins。"""
    return [
        np.histogram(arr[..., ch], bins=bins, range=(0, 256))[0].tolist()
        for ch in range(3)
    ]


def compare_images(
    current_path: str,
    baseline_path: str,
    heatmap_path: str,
    pixel_threshold: int = PIXEL_DIFF_THRESHOLD,
    heatmap_blur: float = 6,
    heatmap_sensitivity: float = 0.25,
    heatmap_method: str = "enhanced",
    heatmap_norm_scale: float = 80.0,
    heatmap_gamma: float = 1.4,
    heatmap_density_radius: float = 16.0,
    heatmap_density_floor: float = 0.2,
) -> dict:
    """对比两张图,生成热力图文件,返回指标字典。"""
    cur_img = Image.open(current_path).convert("RGB")
    base_img = Image.open(baseline_path).convert("RGB")
    if cur_img.size != base_img.size:
        base_img = base_img.resize(cur_img.size)

    cur = np.asarray(cur_img, dtype=np.int16)
    base = np.asarray(base_img, dtype=np.int16)

    abs_diff = np.abs(cur - base)                  # HxWx3
    per_pixel_max = abs_diff.max(axis=2)           # HxW
    diff_mask = per_pixel_max > pixel_threshold

    total_pixels = int(diff_mask.size)
    diff_pixels = int(diff_mask.sum())
    diff_pct = diff_pixels / total_pixels * 100

    gray_cur = np.asarray(cur_img.convert("L"))
    gray_base = np.asarray(base_img.convert("L"))
    mse = float(((cur - base).astype(np.float64) ** 2).mean())
    psnr = float("inf") if mse == 0 else 10 * np.log10(255**2 / mse)

    metrics = {
        "diff_pct": round(diff_pct, 4),
        "diff_pixels": diff_pixels,
        "total_pixels": total_pixels,
        "max_diff": int(per_pixel_max.max()),
        "mean_diff_changed": round(float(per_pixel_max[diff_mask].mean()), 2) if diff_pixels else 0.0,
        "rms": round(float(np.sqrt(mse)), 2),
        "ssim": round(_global_ssim(gray_cur, gray_base), 4),
        "psnr": round(min(psnr, 99.0), 2),
        "channel_diff": {
            ch: round(float((abs_diff[..., i] > pixel_threshold).mean() * 100), 3)
            for i, ch in enumerate(("R", "G", "B"))
        },
        "hist_current": _histogram(np.asarray(cur_img)),
        "hist_baseline": _histogram(np.asarray(base_img)),
    }

    _write_heatmap(
        base_img, per_pixel_max, heatmap_path,
        method=heatmap_method, blur=heatmap_blur, sensitivity=heatmap_sensitivity,
        norm_scale=heatmap_norm_scale, gamma=heatmap_gamma,
        density_radius=heatmap_density_radius, density_floor=heatmap_density_floor,
        pixel_threshold=pixel_threshold,
    )
    return metrics


def _blur_l(arr: np.ndarray, radius: float) -> np.ndarray:
    """对单通道强度数组做高斯模糊,返回 float32(0–255)。"""
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")
    if radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.asarray(img, dtype=np.float32)


def _norm_legacy(per_pixel_max: np.ndarray, blur: float, sensitivity: float) -> np.ndarray:
    """M0:逐图峰值归一化(每张图拉满量程)。弱/强差异观感趋同。"""
    norm = _blur_l(per_pixel_max, blur) / 255.0
    if norm.max() > 0:
        norm = np.clip(norm / max(float(norm.max()), sensitivity), 0, 1)
    return norm


def _norm_enhanced(
    per_pixel_max: np.ndarray, blur: float, norm_scale: float, gamma: float,
    density_radius: float, density_floor: float, pixel_threshold: int,
) -> np.ndarray:
    """M4:绝对幅度 + gamma 低端抑制 + 空间密度门控。
    - 绝对幅度(除以固定 norm_scale 而非峰值):弱差异天然偏冷,可跨图比较;
    - gamma>1:进一步压低端弥散噪声;
    - 密度门控:邻域'变化像素'密度低的散点被掐灭,成片大改放行。"""
    n = np.clip(_blur_l(per_pixel_max, blur) / max(norm_scale, 1e-6), 0, 1) ** gamma
    density = _blur_l((per_pixel_max > pixel_threshold).astype(np.float32) * 255.0,
                      density_radius) / 255.0
    gate = np.clip((density - density_floor) / 0.5, 0, 1)
    return np.clip(n * gate, 0, 1)


def _write_heatmap(
    base_img: Image.Image, per_pixel_max: np.ndarray, out_path: str, *,
    method: str = "enhanced", blur: float = 6, sensitivity: float = 0.25,
    norm_scale: float = 80.0, gamma: float = 1.4,
    density_radius: float = 16.0, density_floor: float = 0.2,
    pixel_threshold: int = PIXEL_DIFF_THRESHOLD,
) -> None:
    """差异强度 -> jet 色热力图,叠加在压暗的基线图上。
    method='enhanced' 强化区域感/抑制弱散噪声(默认);'legacy' 为旧的峰值归一化。"""
    if method == "legacy":
        norm = _norm_legacy(per_pixel_max, blur, sensitivity)
    else:
        norm = _norm_enhanced(per_pixel_max, blur, norm_scale, gamma,
                              density_radius, density_floor, pixel_threshold)

    heat = _jet_colormap(norm).astype(np.float32)
    backdrop = np.asarray(base_img, dtype=np.float32) * 0.25
    backdrop[..., 2] += 40  # 偏蓝底色,贴近"低差异为深蓝"的视觉
    alpha = np.clip(norm * 1.6, 0, 0.9)[..., None]
    blended = backdrop * (1 - alpha) + heat * alpha
    Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8)).save(
        out_path, format="WEBP", quality=HEATMAP_WEBP_QUALITY, method=6)
