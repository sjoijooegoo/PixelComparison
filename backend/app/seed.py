"""生成演示数据(批次 vs 基线批次模型)。

流程:
  1. 生成 3 个基线采集批次(Windows/PS5 的 v1.1.5、Windows 的 v1.1.4)并晋升为基线
  2. 生成 3 个新批次(含一个新增场景、一个缺失场景)
  3. 真实跑对比引擎,结果入库

用法:在 backend 目录下执行  python -m app.seed
"""
from __future__ import annotations

import random
from datetime import datetime

from .db import IMAGES_DIR, Base, SessionLocal, engine
from .imagegen import generate_scene
from .models import Batch, Screenshot
from .service import promote_baseline, run_comparison

AREAS = ["废弃都市", "工业区", "地下设施", "森林边境"]
SPOTS = ["广场", "街道", "室内", "室外", "码头"]

# 20 个标准场景:名字、随机种子、昼夜
SCENES = [
    (
        f"{i:02d}_{AREAS[(i - 1) // 5]}_{SPOTS[(i - 1) % 5]}_{'夜' if i % 2 == 0 else '昼'}",
        100 + i,
        i % 2 == 0,
    )
    for i in range(1, 21)
]
NEW_SCENE = ("21_空间站_走廊_昼", 121, False)


def create_batch(db, batch_id, branch, platform, creator, created, scene_specs):
    """scene_specs: list[(name, seed, night, variant)]"""
    batch = Batch(
        id=batch_id, project="Project_Starfall", branch=branch,
        platform=platform, creator=creator,
        created_at=datetime.strptime(created, "%Y-%m-%d %H:%M"),
    )
    db.add(batch)
    out_dir = IMAGES_DIR / "batches" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, seed, night, variant in scene_specs:
        path = f"batches/{batch_id}/{name}.png"
        generate_scene(str(IMAGES_DIR / path), seed, night, variant=variant)
        db.add(Screenshot(batch_id=batch_id, scene_name=name, path=path))
    db.flush()
    return batch


def with_variants(scenes, rnd, p_fail=0.15, p_warn=0.2):
    """为每个场景随机指定 variant(1=楼体位移失败级 2=噪声警告级 0=不变)。"""
    out = []
    for name, seed, night in scenes:
        roll = rnd.random()
        variant = 1 if roll < p_fail else 2 if roll < p_fail + p_warn else 0
        out.append((name, seed, night, variant))
    return out


def seed() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    rnd = random.Random(42)

    baseline_specs = [(n, s, ng, 0) for n, s, ng in SCENES]

    # ---- 1. 基线采集批次 -> 晋升为基线 ----
    print("生成基线批次…")
    bl_win = create_batch(db, "20240510_0900", "release/1.1.5", "Windows", "CI机器人", "2024-05-10 09:00", baseline_specs)
    bl_ps5 = create_batch(db, "20240510_0930", "release/1.1.5", "iOS", "CI机器人", "2024-05-10 09:30", baseline_specs)
    bl_old = create_batch(db, "20240426_1800", "release/1.1.4", "Windows", "CI机器人", "2024-04-26 18:00", baseline_specs)
    v115_win = promote_baseline(db, bl_win, "v1.1.5")
    v115_ps5 = promote_baseline(db, bl_ps5, "v1.1.5")
    v114_win = promote_baseline(db, bl_old, "v1.1.4")

    # ---- 2. 新批次 ----
    print("生成新批次…")
    # B1:回归较多,且第 5 个场景缺失、多出一个新场景
    b1_scenes = with_variants([s for i, s in enumerate(SCENES) if i != 4], rnd) \
        + [(*NEW_SCENE, 0)]
    b1 = create_batch(db, "20240524_1530", "release/1.2.0", "Windows", "张三", "2024-05-24 15:30", b1_scenes)

    b2 = create_batch(db, "20240524_1022", "release/1.2.0", "iOS", "李四", "2024-05-24 10:22",
                      with_variants(SCENES, rnd, p_fail=0.0, p_warn=0.25))
    b3 = create_batch(db, "20240523_2147", "release/1.2.0", "Windows", "王五", "2024-05-23 21:47",
                      with_variants(SCENES, rnd, p_fail=0.05, p_warn=0.1))

    # ---- 3. 跑对比 ----
    print("运行对比…")
    for batch, ref_batch, baseline in (
        (b1, bl_win, v115_win),
        (b2, bl_ps5, v115_ps5),
        (b3, bl_old, v114_win),
    ):
        comparison = run_comparison(db, batch, ref_batch, baseline)
        comparison.created_at = batch.created_at
        db.flush()  # autoflush 关闭,flush 后 items 惰性加载才可见
        by_status: dict[str, int] = {}
        for it in comparison.items:
            by_status[it.status] = by_status.get(it.status, 0) + 1
        print(f"  {batch.id} vs {baseline.version}({baseline.platform}): "
              f"{comparison.status} diff_avg={comparison.diff_avg:.2f}% {by_status}")

    db.commit()
    db.close()
    print("seed done.")


if __name__ == "__main__":
    seed()
