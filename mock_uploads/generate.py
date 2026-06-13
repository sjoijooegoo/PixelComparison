"""生成多批"上报数据包",模拟采集模块(渲染农场 / CI)的产出。

每个批次包是一个独立目录:
    <批次ID>/
        manifest.json     批次元信息 + 场景清单
        images/*.png      各场景截图(场景名即配对键)

内置数据覆盖多种对比场景:同平台回归、跨平台、新增/缺失场景、多项目。

差异类型(variant,仅影响"新版本"批次,基线批次全为 0):
    0 = 无差异(对比为通过)
    2 = 噪声(警告级,约 1.8%)
    3 = 大幅楼体位移(失败级,约 6%)

用法(需用后端 venv,内含 Pillow/numpy):
    backend\\.venv\\Scripts\\python mock_uploads\\generate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.imagegen import generate_scene  # noqa: E402

RESOLUTION = "1920x1080"
ENGINE = "UE5.3"

# 场景池:编号 -> (区域, 地点, 昼夜, 随机种子)
SCENE_POOLS = {
    "starfall": {
        1: ("废弃都市", "广场", "昼", 301),
        2: ("废弃都市", "街道", "夜", 302),
        3: ("工业区", "室内", "昼", 303),
        4: ("工业区", "室外", "夜", 304),
        5: ("地下设施", "大厅", "昼", 305),
        6: ("地下设施", "走廊", "夜", 306),
        7: ("森林边境", "广场", "昼", 307),
        8: ("海滨要塞", "码头", "夜", 308),
        9: ("空间站", "舱体", "昼", 309),  # 1.3.2 新增场景
    },
    "nebula": {
        1: ("星港", "中庭", "昼", 401),
        2: ("星港", "机库", "夜", 402),
        3: ("环带城", "天桥", "昼", 403),
        4: ("环带城", "市集", "夜", 404),
    },
}

# 每个批次:id / 项目 / 分支 / 平台 / 采集时间 / 场景池 / 场景编号 / 差异(编号->variant)
BATCHES = [
    # —— Starfall · Windows:1.3.0 基线 → 1.3.1 回归(2 失败 + 2 警告) ——
    dict(id="20240601_1000", project="Project_Starfall", branch="release/1.3.0",
         platform="Windows", captured_at="2024-06-01T10:00:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={}),
    dict(id="20240608_1600", project="Project_Starfall", branch="release/1.3.1",
         platform="Windows", captured_at="2024-06-08T16:00:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={2: 3, 4: 2, 6: 3, 8: 2}),

    # —— Starfall · PS5:1.3.0 基线 → 1.3.1 回归(1 失败 + 1 警告) ——
    dict(id="20240601_1030", project="Project_Starfall", branch="release/1.3.0",
         platform="PS5", captured_at="2024-06-01T10:30:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={}),
    dict(id="20240608_1630", project="Project_Starfall", branch="release/1.3.1",
         platform="PS5", captured_at="2024-06-08T16:30:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={3: 3, 5: 2}),

    # —— Starfall · Windows · 1.3.2:删场景 07、增场景 09(演示 缺失/新增) ——
    dict(id="20240615_0900", project="Project_Starfall", branch="release/1.3.2",
         platform="Windows", captured_at="2024-06-15T09:00:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 8, 9], variants={2: 2, 4: 3}),

    # —— Nebula · Windows:develop 基线 → 回归(演示多项目 + 项目筛选) ——
    dict(id="20240610_1100", project="Project_Nebula", branch="develop",
         platform="Windows", captured_at="2024-06-10T11:00:00",
         pool="nebula", scenes=[1, 2, 3, 4], variants={}),
    dict(id="20240614_1100", project="Project_Nebula", branch="develop",
         platform="Windows", captured_at="2024-06-14T11:00:00",
         pool="nebula", scenes=[1, 2, 3, 4], variants={2: 3, 3: 2}),
]


def build_batch(cfg: dict) -> None:
    pool = SCENE_POOLS[cfg["pool"]]
    batch_dir = ROOT / cfg["id"]
    img_dir = batch_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    scenes_meta = []
    for idx in cfg["scenes"]:
        area, spot, tod, seed = pool[idx]
        name = f"{idx:02d}_{area}_{spot}_{tod}"
        night = tod == "夜"
        variant = cfg["variants"].get(idx, 0)
        rel_img = f"images/{name}.png"
        generate_scene(str(batch_dir / rel_img), seed, night, variant=variant)
        scenes_meta.append({
            "name": name, "image": rel_img, "area": area, "time_of_day": tod,
        })

    manifest = {
        "format_version": 1,
        "captured_at": cfg["captured_at"],
        "engine_version": ENGINE,
        "resolution": RESOLUTION,
        # batch 段直接对应 POST /api/batches 的请求体
        "batch": {
            "id": cfg["id"],
            "project": cfg["project"],
            "branch": cfg["branch"],
            "platform": cfg["platform"],
            "creator": "render-farm-ci",
        },
        "scenes": scenes_meta,
    }
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  {cfg['id']:>15}  {cfg['project']:<16} {cfg['branch']:<14} "
          f"{cfg['platform']:<8} {len(scenes_meta)} 场景")


def main() -> None:
    print("生成上报数据包…")
    for cfg in BATCHES:
        build_batch(cfg)
    print(f"完成,共 {len(BATCHES)} 批。上报命令:  python mock_uploads/upload.py")


if __name__ == "__main__":
    main()
