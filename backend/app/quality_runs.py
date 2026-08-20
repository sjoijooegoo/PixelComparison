"""画质运行的完整性、兼容推断与 DTO。

业务代码统一通过本模块解析 (batch_id, shading_quality)，避免继续把
Batch.shading_quality 当作多画质事实来源。
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from .models import QualityRun, Screenshot


DEFAULT_LEGACY_SHADING_QUALITY = 4
# SQLite 的默认单条语句变量上限通常为 999；计数查询本身还会绑定
# ``upload_status``，因此保留余量，避免大项目的全量元数据请求触发 500。
_READY_COUNT_RUN_ID_CHUNK_SIZE = 900


def ready_count_query():
    return (
        select(Screenshot.quality_run_id, func.count(Screenshot.id))
        .where(Screenshot.upload_status == "ready")
        .group_by(Screenshot.quality_run_id)
    )


def ready_counts(db: Session, run_ids: list[int] | None = None) -> dict[int, int]:
    if run_ids is None:
        return {
            int(run_id): int(count)
            for run_id, count in db.execute(ready_count_query())
            if run_id is not None
        }

    # ``IN`` 绑定变量不能超过 SQLite 的编译上限。去重还能避免同一调用方
    # 重复传入运行 ID 时发出无意义的参数和查询。
    unique_run_ids = list(dict.fromkeys(run_ids))
    if not unique_run_ids:
        return {}

    counts: dict[int, int] = {}
    for start in range(0, len(unique_run_ids), _READY_COUNT_RUN_ID_CHUNK_SIZE):
        run_id_chunk = unique_run_ids[start:start + _READY_COUNT_RUN_ID_CHUNK_SIZE]
        stmt = ready_count_query().where(Screenshot.quality_run_id.in_(run_id_chunk))
        counts.update(
            (int(run_id), int(count))
            for run_id, count in db.execute(stmt)
            if run_id is not None
        )
    return counts


def ready_scene_counts_by_batch(db: Session, batch_ids: list[str]) -> dict[str, int]:
    """按批次统计唯一检查点，避免多画质运行把同一检查点重复累加。"""
    if not batch_ids:
        return {}
    rows = db.execute(
        select(Screenshot.batch_id, func.count(func.distinct(Screenshot.scene_name)))
        .where(
            Screenshot.batch_id.in_(batch_ids),
            Screenshot.upload_status == "ready",
        )
        .group_by(Screenshot.batch_id)
    )
    return {str(batch_id): int(count) for batch_id, count in rows}


def is_run_available(run: QualityRun, count: int) -> bool:
    if run.capture_status == "legacy":
        return count > 0
    return (
        run.capture_status == "complete"
        and run.expected_screenshot_count > 0
        and count == run.expected_screenshot_count
    )


def quality_run_dto(run: QualityRun, count: int) -> dict:
    return {
        "id": run.id,
        "quality_run_index": run.quality_run_index,
        "shading_quality": run.shading_quality,
        "tex_quality": run.tex_quality,
        "capture_status": run.capture_status,
        "expected_screenshot_count": run.expected_screenshot_count,
        "ready_screenshot_count": count,
        "is_complete": is_run_available(run, count),
    }


def runs_by_batch(db: Session, batch_ids: list[str]) -> dict[str, list[QualityRun]]:
    grouped: dict[str, list[QualityRun]] = defaultdict(list)
    if not batch_ids:
        return grouped
    runs = db.scalars(
        select(QualityRun)
        .where(QualityRun.batch_id.in_(batch_ids))
        .order_by(QualityRun.batch_id, QualityRun.shading_quality.desc())
    ).all()
    for run in runs:
        grouped[run.batch_id].append(run)
    return grouped


def runs_with_ready_counts_by_batch(
    db: Session, batch_ids: list[str]
) -> tuple[dict[str, list[QualityRun]], dict[int, int], dict[str, int]]:
    grouped: dict[str, list[QualityRun]] = defaultdict(list)
    counts: dict[int, int] = {}
    scene_counts: dict[str, int] = {}
    if not batch_ids:
        return grouped, counts, scene_counts
    ready_shot = aliased(Screenshot)
    batch_shot = aliased(Screenshot)
    scene_count = (
        select(func.count(func.distinct(batch_shot.scene_name)))
        .where(
            batch_shot.batch_id == QualityRun.batch_id,
            batch_shot.upload_status == "ready",
        )
        .correlate(QualityRun)
        .scalar_subquery()
    )
    rows = db.execute(
        select(QualityRun, func.count(ready_shot.id), scene_count)
        .outerjoin(ready_shot, and_(
            ready_shot.quality_run_id == QualityRun.id,
            ready_shot.upload_status == "ready",
        ))
        .where(QualityRun.batch_id.in_(batch_ids))
        .group_by(QualityRun.id)
        .order_by(QualityRun.batch_id, QualityRun.shading_quality.desc())
    ).all()
    for run, count, batch_scene_count in rows:
        grouped[run.batch_id].append(run)
        counts[run.id] = int(count)
        scene_counts[run.batch_id] = int(batch_scene_count)
    return grouped, counts, scene_counts


def resolve_quality_run(
    db: Session,
    batch_id: str,
    shading_quality: int | None,
    *,
    require_available: bool = False,
    infer_available: bool = True,
) -> tuple[QualityRun | None, int]:
    stmt = select(QualityRun).where(QualityRun.batch_id == batch_id)
    if shading_quality is not None:
        stmt = stmt.where(QualityRun.shading_quality == shading_quality)
    runs = db.scalars(stmt.order_by(QualityRun.shading_quality.desc())).all()
    if shading_quality is None:
        if len(runs) == 1:
            run = runs[0]
        elif not infer_available:
            return None, 0
        else:
            counts = ready_counts(db, [candidate.id for candidate in runs])
            available = [
                candidate for candidate in runs
                if is_run_available(candidate, counts.get(candidate.id, 0))
            ]
            if len(available) != 1:
                return None, 0
            run = available[0]
            count = counts.get(run.id, 0)
            return run, count
    else:
        run = runs[0] if runs else None
    if run is None:
        return None, 0
    count = ready_counts(db, [run.id]).get(run.id, 0)
    if require_available and not is_run_available(run, count):
        return None, count
    return run, count
