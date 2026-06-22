"""生成多批"上报数据包",模拟采集模块(渲染农场 / CI)的产出(新版 manifest 格式)。

每个批次包是一个独立目录:
    <批次ID>/
        manifest.json         批次元信息(pipeline_data + ue_data)+ 截图清单
        Screenshot/*.png      各截图(screenshots[].name 即配对键)

内置数据覆盖多种对比场景:同平台回归、跨平台、新增/缺失、多项目。

差异类型(variant,仅影响"新版本"批次,基线批次全为 0):
    0 = 无差异(对比为通过)
    2 = 噪声(警告级,约 1.8%)
    3 = 大幅楼体位移(失败级,约 6%)

用法(需用后端 venv,内含 Pillow/numpy):
    backend\\.venv\\Scripts\\python mock_uploads\\generate.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.imagegen import generate_scene  # noqa: E402

RESOLUTION = {"width": 1920, "height": 1080}
DEVOPS = "https://devops.woa.com/console/pipeline/arashi/p-mock/detail"

# UE 上报的平台名带 Editor 后缀(平台侧会归一化为 Windows/iOS/Android)
UE_PLATFORM = {"Windows": "WindowsEditor", "iOS": "IOSEditor", "Android": "AndroidEditor"}

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

# 每个批次:id / 场景ID / P4 / 平台 / 采集时间 / 场景池 / 场景编号 / 差异(编号->variant)
BATCHES = [
    # —— Starfall · Windows:基线 → 回归(2 失败 + 2 警告) ——
    dict(id="7", scene_id="Lv_Starfall", p4_version=251200,
         platform="Windows", captured_at="2024-06-01T10:00:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={}),
    dict(id="8", scene_id="Lv_Starfall", p4_version=251640,
         platform="Windows", captured_at="2024-06-08T16:00:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={2: 3, 4: 2, 6: 3, 8: 2}),

    # —— Starfall · iOS:基线 → 回归(1 失败 + 1 警告) ——
    dict(id="9", scene_id="Lv_Starfall", p4_version=251205,
         platform="iOS", captured_at="2024-06-01T10:30:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={}),
    dict(id="10", scene_id="Lv_Starfall", p4_version=251645,
         platform="iOS", captured_at="2024-06-08T16:30:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 7, 8], variants={3: 3, 5: 2}),

    # —— Starfall · Windows:删场景 07、增场景 09(演示 缺失/新增) ——
    dict(id="11", scene_id="Lv_Starfall", p4_version=252180,
         platform="Windows", captured_at="2024-06-15T09:00:00",
         pool="starfall", scenes=[1, 2, 3, 4, 5, 6, 8, 9], variants={2: 2, 4: 3}),

    # —— Nebula · Android:基线 → 回归(演示多项目 + 项目筛选) ——
    dict(id="12", scene_id="Lv_Nebula", p4_version=251800,
         platform="Android", captured_at="2024-06-10T11:00:00",
         pool="nebula", scenes=[1, 2, 3, 4], variants={}),
    dict(id="13", scene_id="Lv_Nebula", p4_version=252100,
         platform="Android", captured_at="2024-06-14T11:00:00",
         pool="nebula", scenes=[1, 2, 3, 4], variants={2: 3, 3: 2}),
]


def fake_camera(seed: int, idx: int) -> dict:
    """由 seed/idx 生成确定性的相机位姿(仅用于演示)。"""
    return {
        "location": {
            "x": round(-50000 + seed * 13 + idx * 137.5, 3),
            "y": round(-30000 + seed * 7 - idx * 91.25, 3),
            "z": round(-5000 + (seed % 17) * 60 + idx * 12.5, 3),
        },
        "rotation": {
            "pitch": round(((seed + idx) % 60) - 30 + 0.4, 6),
            "yaw": round(((seed * 3 + idx * 7) % 360) - 180 + 0.7, 6),
            "roll": 0.0,
        },
    }


def build_batch(cfg: dict) -> None:
    pool = SCENE_POOLS[cfg["pool"]]
    batch_dir = ROOT / cfg["id"]
    img_dir = batch_dir / "Screenshot"
    # 清掉旧结构(老版本的 images/ 扁平目录)
    if (batch_dir / "images").exists():
        shutil.rmtree(batch_dir / "images")
    img_dir.mkdir(parents=True, exist_ok=True)

    seq_name = f"Seq_{cfg['scene_id']}"
    shots_meta = []
    for i, idx in enumerate(cfg["scenes"]):
        area, spot, tod, seed = pool[idx]
        name = f"{idx:02d}_{area}_{spot}_{tod}"
        night = tod == "夜"
        variant = cfg["variants"].get(idx, 0)
        rel_img = f"Screenshot/{name}.png"
        generate_scene(str(batch_dir / rel_img), seed, night, variant=variant)
        shots_meta.append({
            "index": i,
            "name": name,
            "image": rel_img,
            "camera": fake_camera(seed, i),
        })

    manifest = {
        "format_version": 1,
        "capture_type": "levelsequence",
        "pipeline_data": {
            "batch_id": cfg["id"],
            "batch_url": f"{DEVOPS}/b-{cfg['id']}/executeDetail",
            "captured_at": cfg["captured_at"],
        },
        "ue_data": {
            "levelsequence_path": f"/Game/Cinematics/{seq_name}.{seq_name}",
            "levelsequence_name": seq_name,
            "world_name": cfg["scene_id"],
            "platform": UE_PLATFORM.get(cfg["platform"], cfg["platform"]),
            "p4_version": str(cfg["p4_version"]),
            "resolution": RESOLUTION,
        },
        "screenshots": shots_meta,
    }
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  {cfg['id']:>4}  {cfg['scene_id']:<16} {cfg['p4_version']:<10} "
          f"{manifest['ue_data']['platform']:<14} {len(shots_meta)} 截图")


def main() -> None:
    print("生成上报数据包(新版 manifest)…")
    for cfg in BATCHES:
        build_batch(cfg)
    print(f"完成,共 {len(BATCHES)} 批。上报命令:  python mock_uploads/upload.py")


if __name__ == "__main__":
    main()
