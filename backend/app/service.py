"""对比服务:批次 × 基线,按场景名配对逐对跑 diff。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .compare import compare_images
from .db import IMAGES_DIR
from .models import Baseline, Batch, Comparison, ComparisonItem, Screenshot
from .settings import DEFAULT_SETTINGS


def classify(diff_pct: float, fail_threshold: float, warn_threshold: float) -> str:
    if diff_pct >= fail_threshold:
        return "fail"
    if diff_pct >= warn_threshold:
        return "warn"
    return "pass"


def run_comparison(
    db: Session, comparison: Comparison, batch: Batch, ref_batch: Batch,
    baseline: Baseline | None = None, settings: dict | None = None,
    on_progress=None,
) -> Comparison:
    """把对比结果填进已存在的 comparison 行(force 重算时复用同一行/同一 id)。

    - 两边都有 -> 跑 diff,按阈值判 pass/warn/fail
    - 仅当前批次有 -> added(新增检查点,待人工确认)
    - 仅参照批次有 -> missing(检查点缺失,视为失败级问题)
    """
    cfg = settings or DEFAULT_SETTINGS
    current_shots = {
        s.scene_name: s
        for s in db.scalars(select(Screenshot).where(Screenshot.batch_id == batch.id))
    }
    baseline_shots = {
        s.scene_name: s
        for s in db.scalars(select(Screenshot).where(Screenshot.batch_id == ref_batch.id))
    }

    # 复用同一行:刷新基线关联并清掉旧明细(重算时 comparison.id 保持不变)
    comparison.baseline_id = baseline.id if baseline else None
    db.execute(delete(ComparisonItem).where(ComparisonItem.comparison_id == comparison.id))
    db.flush()

    heat_dir = IMAGES_DIR / "heatmaps" / str(comparison.id)
    heat_dir.mkdir(parents=True, exist_ok=True)

    names = sorted(set(current_shots) | set(baseline_shots))
    paired = [n for n in names if n in current_shots and n in baseline_shots]

    # 两边都有的检查点:并行跑像素对比(compare_images 纯计算 + 写热力图文件,不碰 DB)
    def _compare(name: str):
        cur, base = current_shots[name], baseline_shots[name]
        return name, compare_images(
            str(IMAGES_DIR / cur.path),
            str(IMAGES_DIR / base.path),
            str(IMAGES_DIR / f"heatmaps/{comparison.id}/{name}.png"),
            pixel_threshold=int(cfg["pixel_diff_threshold"]),
            heatmap_blur=cfg["heatmap_blur"],
            heatmap_sensitivity=cfg["heatmap_sensitivity"],
        )

    metrics_by_name: dict = {}
    total = len(paired)
    if on_progress:
        on_progress(0, total)
    if paired:
        done = 0
        with ThreadPoolExecutor(max_workers=min(8, total)) as ex:
            for fut in as_completed(ex.submit(_compare, n) for n in paired):
                name, metrics = fut.result()
                metrics_by_name[name] = metrics
                done += 1
                if on_progress:
                    on_progress(done, total)

    diffs: list[float] = []
    has_fail = has_warn = False

    for name in names:
        cur, base = current_shots.get(name), baseline_shots.get(name)

        if cur and base:
            metrics = metrics_by_name[name]
            status = classify(metrics["diff_pct"], cfg["fail_threshold"], cfg["warn_threshold"])
            diffs.append(metrics["diff_pct"])
            item = ComparisonItem(
                comparison_id=comparison.id, scene_name=name,
                current_shot_id=cur.id, baseline_shot_id=base.id,
                status=status, diff_pct=metrics["diff_pct"],
                metrics=metrics, heatmap_path=f"heatmaps/{comparison.id}/{name}.png",
            )
        elif cur:
            status = "added"
            item = ComparisonItem(
                comparison_id=comparison.id, scene_name=name,
                current_shot_id=cur.id, status=status,
            )
        else:
            status = "missing"
            item = ComparisonItem(
                comparison_id=comparison.id, scene_name=name,
                baseline_shot_id=base.id, status=status,
            )

        has_fail |= status in ("fail", "missing")
        has_warn |= status in ("warn", "added")
        db.add(item)

    comparison.diff_avg = sum(diffs) / len(diffs) if diffs else 0.0
    comparison.status = "fail" if has_fail else "warn" if has_warn else "pass"
    return comparison


def promote_baseline(db: Session, batch: Batch, version: str) -> Baseline:
    """把批次晋升为基线;同平台同版本的旧基线退役。"""
    old = db.scalars(
        select(Baseline).where(
            Baseline.scene_id == batch.scene_id,
            Baseline.platform == batch.platform,
            Baseline.version == version,
            Baseline.status == "active",
        )
    ).all()
    for b in old:
        b.status = "retired"
    baseline = Baseline(
        version=version, scene_id=batch.scene_id,
        platform=batch.platform, source_batch_id=batch.id,
    )
    db.add(baseline)
    db.flush()
    return baseline
