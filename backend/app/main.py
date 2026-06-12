from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import IMAGES_DIR, Base, engine, get_db
from .models import Baseline, Batch, Comparison, ComparisonItem, Screenshot
from .service import run_comparison

Base.metadata.create_all(engine)

app = FastAPI(title="ShotDiff API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

ITEM_STATUSES = ("fail", "warn", "pass", "added", "missing")


# ---------------------------------------------------------------- DTO

def batch_dto(b: Batch, db: Session) -> dict:
    return {
        "id": b.id,
        "project": b.project,
        "branch": b.branch,
        "platform": b.platform,
        "creator": b.creator,
        "created_at": b.created_at.strftime("%Y-%m-%d %H:%M"),
        "scene_count": db.scalar(
            select(func.count(Screenshot.id)).where(Screenshot.batch_id == b.id)
        ) or 0,
    }


def comparison_dto(c: Comparison, db: Session) -> dict:
    scene_count = db.scalar(
        select(func.count(Screenshot.id)).where(Screenshot.batch_id == c.batch_id)
    ) or 0
    compare_count = db.scalar(
        select(func.count(ComparisonItem.id)).where(
            ComparisonItem.comparison_id == c.id,
            ComparisonItem.current_shot_id.isnot(None),
            ComparisonItem.baseline_shot_id.isnot(None),
        )
    ) or 0
    return {
        "id": c.id,
        "batch_id": c.batch_id,
        "project": c.batch.project,
        "branch": c.batch.branch,
        "platform": c.batch.platform,
        "creator": c.batch.creator,
        "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
        # 参照批次:有基线版本则显示版本号,否则显示批次号
        "ref_batch_id": c.ref_batch_id,
        "ref_label": c.baseline.version if c.baseline else f"#{c.ref_batch_id}",
        "ref_branch": c.ref_batch.branch,
        "status": c.status,
        "diff_avg": round(c.diff_avg, 2),
        "scene_count": scene_count,
        "compare_count": compare_count,
    }


def item_dto(it: ComparisonItem, with_metrics: bool = False) -> dict:
    d = {
        "id": it.id,
        "comparison_id": it.comparison_id,
        "name": it.scene_name,
        "status": it.status,
        "diff_pct": round(it.diff_pct, 2) if it.diff_pct is not None else None,
        "current_url": it.current_shot.url if it.current_shot else None,
        "baseline_url": it.baseline_shot.url if it.baseline_shot else None,
        "heatmap_url": f"/images/{it.heatmap_path}" if it.heatmap_path else None,
    }
    d["thumb_url"] = d["current_url"] or d["baseline_url"]
    if with_metrics:
        d["metrics"] = it.metrics
    return d


# ---------------------------------------------------------------- 批次(上报 + 查询)

class BatchIn(BaseModel):
    id: str | None = None
    project: str
    branch: str
    platform: str
    creator: str = "CI机器人"


@app.get("/api/batches")
def list_batches(
    db: Session = Depends(get_db),
    project: str | None = None,
    platform: str | None = None,
):
    stmt = select(Batch).order_by(Batch.created_at.desc())
    if project:
        stmt = stmt.where(Batch.project == project)
    if platform:
        stmt = stmt.where(Batch.platform == platform)
    return {"items": [batch_dto(b, db) for b in db.scalars(stmt)]}


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, db: Session = Depends(get_db)):
    """其他模块上报批次:先建批次,再逐张上传截图。"""
    batch_id = body.id or datetime.now().strftime("%Y%m%d_%H%M%S")
    if db.get(Batch, batch_id):
        raise HTTPException(409, f"batch {batch_id} already exists")
    batch = Batch(
        id=batch_id, project=body.project, branch=body.branch,
        platform=body.platform, creator=body.creator,
    )
    db.add(batch)
    db.commit()
    return batch_dto(batch, db)


@app.post("/api/batches/{batch_id}/screenshots", status_code=201)
def upload_screenshot(
    batch_id: str,
    scene_name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not db.get(Batch, batch_id):
        raise HTTPException(404, "batch not found")
    exists = db.scalar(
        select(Screenshot).where(
            Screenshot.batch_id == batch_id, Screenshot.scene_name == scene_name
        )
    )
    if exists:
        raise HTTPException(409, f"scene {scene_name} already uploaded")
    out_dir = IMAGES_DIR / "batches" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = f"batches/{batch_id}/{scene_name}.png"
    (IMAGES_DIR / path).write_bytes(file.file.read())
    shot = Screenshot(batch_id=batch_id, scene_name=scene_name, path=path)
    db.add(shot)
    db.commit()
    return {"id": shot.id, "scene_name": scene_name, "url": shot.url}


# ---------------------------------------------------------------- 对比

class ComparisonIn(BaseModel):
    batch_id: str       # 当前批次
    ref_batch_id: str   # 参照批次


@app.post("/api/comparisons", status_code=201)
def create_comparison(body: ComparisonIn, db: Session = Depends(get_db)):
    """用户选择两个批次发起对比(演示为同步执行;生产应进任务队列)。"""
    batch = db.get(Batch, body.batch_id)
    ref = db.get(Batch, body.ref_batch_id)
    if not batch or not ref:
        raise HTTPException(404, "batch not found")
    if batch.id == ref.id:
        raise HTTPException(400, "不能与自身对比")
    if batch.platform != ref.platform:
        raise HTTPException(400, "两个批次的平台不同,对比无意义")

    # 参照批次若是某个 active 基线的来源批次,则带上版本号
    baseline = db.scalar(
        select(Baseline).where(
            Baseline.source_batch_id == ref.id, Baseline.status == "active"
        )
    )
    comparison = run_comparison(db, batch, ref, baseline)
    db.commit()
    return comparison_dto(comparison, db)


@app.get("/api/comparisons")
def list_comparisons(
    db: Session = Depends(get_db),
    project: str | None = None,
    platform: str | None = None,
    branch: str | None = None,
    baseline: str | None = None,
    status: str | None = None,
    q: str | None = None,
):
    stmt = (
        select(Comparison)
        .join(Batch, Comparison.batch_id == Batch.id)
        .order_by(Comparison.created_at.desc())
    )
    if project:
        stmt = stmt.where(Batch.project == project)
    if platform:
        stmt = stmt.where(Batch.platform == platform)
    if branch:
        stmt = stmt.where(Batch.branch == branch)
    if baseline:
        stmt = stmt.join(Baseline, Comparison.baseline_id == Baseline.id).where(
            Baseline.version == baseline
        )
    if status:
        stmt = stmt.where(Comparison.status == status)
    if q:
        stmt = stmt.where(Batch.id.contains(q) | Batch.branch.contains(q))
    comparisons = db.scalars(stmt).all()
    return {"total": len(comparisons), "items": [comparison_dto(c, db) for c in comparisons]}


@app.get("/api/comparisons/{comparison_id}/scenes")
def list_scenes(
    comparison_id: int,
    db: Session = Depends(get_db),
    status: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    if not db.get(Comparison, comparison_id):
        raise HTTPException(404, "comparison not found")
    base = select(ComparisonItem).where(ComparisonItem.comparison_id == comparison_id)
    if status:
        base = base.where(ComparisonItem.status == status)
    if q:
        base = base.where(ComparisonItem.scene_name.contains(q))

    counts = {
        st: db.scalar(
            select(func.count(ComparisonItem.id)).where(
                ComparisonItem.comparison_id == comparison_id,
                ComparisonItem.status == st,
            )
        )
        for st in ITEM_STATUSES
    }
    counts["all"] = sum(counts.values())

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(
        base.order_by(ComparisonItem.scene_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "counts": counts,
        "items": [item_dto(it) for it in items],
    }


@app.get("/api/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)):
    it = db.get(ComparisonItem, item_id)
    if not it:
        raise HTTPException(404, "item not found")
    siblings = db.scalars(
        select(ComparisonItem.id)
        .where(ComparisonItem.comparison_id == it.comparison_id)
        .order_by(ComparisonItem.scene_name)
    ).all()
    idx = siblings.index(it.id)
    d = item_dto(it, with_metrics=True)
    d["index"] = idx + 1
    d["sibling_total"] = len(siblings)
    d["prev_id"] = siblings[idx - 1] if idx > 0 else None
    d["next_id"] = siblings[idx + 1] if idx < len(siblings) - 1 else None
    return d


# ---------------------------------------------------------------- 基线 / 元数据

@app.get("/api/baselines")
def list_baselines(db: Session = Depends(get_db)):
    baselines = db.scalars(select(Baseline).order_by(Baseline.created_at.desc())).all()
    return {
        "items": [
            {
                "id": b.id,
                "version": b.version,
                "project": b.project,
                "platform": b.platform,
                "source_batch_id": b.source_batch_id,
                "status": b.status,
                "created_at": b.created_at.strftime("%Y-%m-%d %H:%M"),
                "scene_count": db.scalar(
                    select(func.count(Screenshot.id)).where(
                        Screenshot.batch_id == b.source_batch_id
                    )
                ),
            }
            for b in baselines
        ]
    }


@app.get("/api/meta")
def get_meta(db: Session = Depends(get_db)):
    """筛选器选项。"""
    return {
        "projects": db.scalars(select(Batch.project).distinct()).all(),
        "platforms": db.scalars(select(Batch.platform).distinct()).all(),
        "branches": db.scalars(select(Batch.branch).distinct()).all(),
        "baselines": db.scalars(select(Baseline.version).distinct()).all(),
    }
