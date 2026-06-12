"""对比服务:批次 × 基线,按场景名配对逐对跑 diff。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .compare import compare_images
from .db import IMAGES_DIR
from .models import Baseline, Batch, Comparison, ComparisonItem, Screenshot

# 失败/警告判定阈值(差异率 %)
FAIL_THRESHOLD = 2.0
WARN_THRESHOLD = 0.3


def classify(diff_pct: float) -> str:
    if diff_pct >= FAIL_THRESHOLD:
        return "fail"
    if diff_pct >= WARN_THRESHOLD:
        return "warn"
    return "pass"


def run_comparison(
    db: Session, batch: Batch, ref_batch: Batch, baseline: Baseline | None = None
) -> Comparison:
    """配对两个批次的截图并逐场景对比。

    - 两边都有 -> 跑 diff,按阈值判 pass/warn/fail
    - 仅当前批次有 -> added(新增场景,待人工确认)
    - 仅参照批次有 -> missing(场景缺失,视为失败级问题)
    """
    current_shots = {
        s.scene_name: s
        for s in db.scalars(select(Screenshot).where(Screenshot.batch_id == batch.id))
    }
    baseline_shots = {
        s.scene_name: s
        for s in db.scalars(select(Screenshot).where(Screenshot.batch_id == ref_batch.id))
    }

    comparison = Comparison(
        batch_id=batch.id,
        ref_batch_id=ref_batch.id,
        baseline_id=baseline.id if baseline else None,
    )
    db.add(comparison)
    db.flush()  # 取 comparison.id,热力图按它归档

    heat_dir = IMAGES_DIR / "heatmaps" / str(comparison.id)
    heat_dir.mkdir(parents=True, exist_ok=True)

    diffs: list[float] = []
    has_fail = has_warn = False

    for name in sorted(set(current_shots) | set(baseline_shots)):
        cur, base = current_shots.get(name), baseline_shots.get(name)

        if cur and base:
            heatmap_path = f"heatmaps/{comparison.id}/{name}.png"
            metrics = compare_images(
                str(IMAGES_DIR / cur.path),
                str(IMAGES_DIR / base.path),
                str(IMAGES_DIR / heatmap_path),
            )
            status = classify(metrics["diff_pct"])
            diffs.append(metrics["diff_pct"])
            item = ComparisonItem(
                comparison_id=comparison.id, scene_name=name,
                current_shot_id=cur.id, baseline_shot_id=base.id,
                status=status, diff_pct=metrics["diff_pct"],
                metrics=metrics, heatmap_path=heatmap_path,
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
            Baseline.project == batch.project,
            Baseline.platform == batch.platform,
            Baseline.version == version,
            Baseline.status == "active",
        )
    ).all()
    for b in old:
        b.status = "retired"
    baseline = Baseline(
        version=version, project=batch.project,
        platform=batch.platform, source_batch_id=batch.id,
    )
    db.add(baseline)
    db.flush()
    return baseline
