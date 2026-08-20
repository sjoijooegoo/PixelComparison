"""对比服务:批次 × 基线,按场景名配对逐对跑 diff。"""
from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .compare import compare_images
from .db import IMAGES_DIR
from .models import Baseline, Batch, Comparison, ComparisonItem, QualityRun, Screenshot
from .settings import DEFAULT_SETTINGS


def classify(diff_pct: float, fail_threshold: float, warn_threshold: float) -> str:
    if diff_pct >= fail_threshold:
        return "fail"
    if diff_pct >= warn_threshold:
        return "warn"
    return "pass"


def run_comparison(
    db: Session, comparison: Comparison, batch: Batch, ref_batch: Batch,
    current_run: QualityRun, reference_run: QualityRun,
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
        for s in db.scalars(select(Screenshot).where(
            Screenshot.quality_run_id == current_run.id,
            Screenshot.upload_status == "ready",
        ))
    }
    baseline_shots = {
        s.scene_name: s
        for s in db.scalars(select(Screenshot).where(
            Screenshot.quality_run_id == reference_run.id,
            Screenshot.upload_status == "ready",
        ))
    }

    heat_dir = IMAGES_DIR / "heatmaps" / str(comparison.id)
    if heat_dir.exists():
        shutil.rmtree(heat_dir)
    heat_dir.mkdir(parents=True, exist_ok=True)

    names = sorted(set(current_shots) | set(baseline_shots))
    paired = [n for n in names if n in current_shots and n in baseline_shots]

    # 两边都有的检查点:并行跑像素对比(compare_images 纯计算 + 写热力图文件,不碰 DB)
    def _compare(name: str):
        cur, base = current_shots[name], baseline_shots[name]
        return name, compare_images(
            str(IMAGES_DIR / cur.path),
            str(IMAGES_DIR / base.path),
            str(IMAGES_DIR / f"heatmaps/{comparison.id}/{name}.webp"),
            pixel_threshold=int(cfg["pixel_diff_threshold"]),
            heatmap_blur=cfg["heatmap_blur"],
            heatmap_sensitivity=cfg["heatmap_sensitivity"],
            heatmap_method=cfg["heatmap_method"],
            heatmap_norm_scale=cfg["heatmap_norm_scale"],
            heatmap_gamma=cfg["heatmap_gamma"],
            heatmap_density_radius=cfg["heatmap_density_radius"],
            heatmap_density_floor=cfg["heatmap_density_floor"],
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

    # 像素计算和热力图写盘可能持续数秒，这一阶段不能提前取得 SQLite
    # 写锁，否则所有上报和前端写操作都会被阻塞。只在纯计算结束后开启
    # 短事务，集中替换当前对比的数据库明细。
    comparison.baseline_id = baseline.id if baseline else None
    db.execute(delete(ComparisonItem).where(ComparisonItem.comparison_id == comparison.id))
    db.flush()

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
                metrics=metrics, heatmap_path=f"heatmaps/{comparison.id}/{name}.webp",
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


def promote_baseline(
    db: Session, batch: Batch, quality_run: QualityRun, version: str
) -> Baseline:
    """把批次晋升为基线;同分支、平台、版本的旧基线退役。"""
    old = db.scalars(
        select(Baseline)
        .join(QualityRun, Baseline.source_quality_run_id == QualityRun.id)
        .where(
            Baseline.branch_tag == batch.branch_tag,
            Baseline.scene_id == batch.scene_id,
            Baseline.platform == batch.platform,
            QualityRun.shading_quality == quality_run.shading_quality,
            Baseline.version == version,
            Baseline.status == "active",
        )
    ).all()
    for b in old:
        b.status = "retired"
    baseline = Baseline(
        version=version, branch_tag=batch.branch_tag, scene_id=batch.scene_id,
        platform=batch.platform, source_batch_id=batch.id,
        source_quality_run_id=quality_run.id,
    )
    db.add(baseline)
    db.flush()
    return baseline
