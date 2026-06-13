"""生成两批"上报数据包",模拟采集模块(渲染农场 / CI)的产出。

每个批次包是一个独立目录:
    <批次ID>/
        manifest.json     批次元信息 + 场景清单
        images/*.png      各场景截图(场景名即配对键)

两批共用同一套场景名、同平台同项目;第二批故意让若干场景产生渲染差异,
上报后即可在界面里把两批互相对比,看到失败/警告级差异。

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

PROJECT = "Project_Starfall"
PLATFORM = "Windows"
RESOLUTION = "1920x1080"
ENGINE = "UE5.3"

# idx, 区域, 地点, 昼夜, 随机种子, 第二批的差异类型
#   0=无差异(通过)  2=噪声(警告级)  3=大幅楼体位移(失败级)
SCENES = [
    (1, "废弃都市", "广场", "昼", 301, 0),
    (2, "废弃都市", "街道", "夜", 302, 3),
    (3, "工业区", "室内", "昼", 303, 0),
    (4, "工业区", "室外", "夜", 304, 2),
    (5, "地下设施", "大厅", "昼", 305, 0),
    (6, "地下设施", "走廊", "夜", 306, 3),
    (7, "森林边境", "广场", "昼", 307, 0),
    (8, "海滨要塞", "码头", "夜", 308, 2),
]

# 两个批次:第一批为干净渲染,第二批引入差异(use_b_variant=True)
BATCHES = [
    {
        "id": "20240601_1000",
        "branch": "release/1.3.0",
        "creator": "render-farm-ci",
        "captured_at": "2024-06-01T10:00:00",
        "use_diff": False,
    },
    {
        "id": "20240608_1600",
        "branch": "release/1.3.1",
        "creator": "render-farm-ci",
        "captured_at": "2024-06-08T16:00:00",
        "use_diff": True,
    },
]


def build_batch(cfg: dict) -> None:
    batch_dir = ROOT / cfg["id"]
    img_dir = batch_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    scenes_meta = []
    for idx, area, spot, tod, seed, diff_variant in SCENES:
        name = f"{idx:02d}_{area}_{spot}_{tod}"
        night = tod == "夜"
        variant = diff_variant if cfg["use_diff"] else 0
        rel_img = f"images/{name}.png"
        generate_scene(str(batch_dir / rel_img), seed, night, variant=variant)
        scenes_meta.append({
            "name": name,
            "image": rel_img,
            "area": area,
            "time_of_day": tod,
        })

    manifest = {
        "format_version": 1,
        "captured_at": cfg["captured_at"],
        "engine_version": ENGINE,
        "resolution": RESOLUTION,
        # batch 段直接对应 POST /api/batches 的请求体
        "batch": {
            "id": cfg["id"],
            "project": PROJECT,
            "branch": cfg["branch"],
            "platform": PLATFORM,
            "creator": cfg["creator"],
        },
        "scenes": scenes_meta,
    }
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  生成 {cfg['id']}: {len(scenes_meta)} 个场景 -> {batch_dir}")


def main() -> None:
    print("生成上报数据包…")
    for cfg in BATCHES:
        build_batch(cfg)
    print("完成。上报命令:  python mock_uploads/upload.py")


if __name__ == "__main__":
    main()
