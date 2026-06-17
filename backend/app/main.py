import json
import threading
import time
import uuid
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import IMAGES_DIR, Base, SessionLocal, engine, get_db, migrate_columns
from .models import Baseline, Batch, Comparison, ComparisonItem, Screenshot
from .service import run_comparison
from .settings import get_settings, save_settings

Base.metadata.create_all(engine)
migrate_columns()

app = FastAPI(title="ShotDiff API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    # 局域网/任意来源访问(内网工具,无凭证);如需收紧改回白名单
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

ITEM_STATUSES = ("fail", "warn", "pass", "added", "missing")

# UE 上报的平台名(可能带 Editor 后缀)归一化为平台展示值
_PLATFORM_ALIASES = {
    "windowseditor": "Windows",
    "windows": "Windows",
    "win64": "Windows",
    "win": "Windows",
    "ioseditor": "iOS",
    "ios": "iOS",
    "androideditor": "Android",
    "android": "Android",
}


def normalize_platform(raw: str) -> str:
    """WindowsEditor→Windows 等;未知值去掉 Editor 后缀,否则原样返回。"""
    if not raw:
        return raw
    raw = raw.strip()
    key = raw.lower()
    if key in _PLATFORM_ALIASES:
        return _PLATFORM_ALIASES[key]
    if key.endswith("editor"):
        return raw[: -len("Editor")]
    return raw


def safe_segment(value: str, field: str) -> str:
    """收口落盘用的路径段:禁止分隔符 / 上跳,防目录遍历。"""
    if not value or value in (".", "..") or "/" in value or "\\" in value or "\0" in value:
        raise HTTPException(400, f"非法的 {field}: {value!r}")
    return value


# ---------------------------------------------------------------- DTO

def batch_dto(b: Batch, db: Session) -> dict:
    return {
        "id": b.id,
        "scene_id": b.scene_id,
        "p4_version": b.p4_version,
        "platform": b.platform,
        "creator": b.creator,
        "batch_url": b.batch_url,
        "resolution": b.resolution,
        "created_at": b.created_at.strftime("%Y-%m-%d %H:%M"),
        "scene_count": db.scalar(
            select(func.count(Screenshot.id)).where(Screenshot.batch_id == b.id)
        ) or 0,
    }


def comparison_dto(c: Comparison, db: Session) -> dict:
    # 检查点数 = 本次对比的全部检查点(两批并集),与 SceneList 列表总数一致
    scene_count = db.scalar(
        select(func.count(ComparisonItem.id)).where(ComparisonItem.comparison_id == c.id)
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
        "scene_id": c.batch.scene_id,
        "p4_version": c.batch.p4_version,
        "platform": c.batch.platform,
        "creator": c.batch.creator,
        "resolution": c.batch.resolution,
        "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
        # 参照批次:有基线版本则显示版本号,否则显示批次号
        "ref_batch_id": c.ref_batch_id,
        "ref_label": c.baseline.version if c.baseline else f"#{c.ref_batch_id}",
        "ref_p4_version": c.ref_batch.p4_version,
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
    # 相机位姿:优先取当前批截图,缺则取参照批
    cam_shot = it.current_shot or it.baseline_shot
    d["camera"] = cam_shot.camera if cam_shot else None
    if with_metrics:
        d["metrics"] = it.metrics
    return d


# ---------------------------------------------------------------- 批次(上报 + 查询)

class BatchIn(BaseModel):
    id: str | None = None
    scene_id: str
    p4_version: int
    platform: str
    creator: str = "CI机器人"
    # 新版上报附带(均可选)
    batch_url: str | None = None
    resolution: str | None = None
    capture_type: str | None = None
    levelsequence_name: str | None = None
    levelsequence_path: str | None = None
    captured_at: str | None = None


@app.get("/api/batches")
def list_batches(
    db: Session = Depends(get_db),
    scene_id: str | None = None,
    platform: str | None = None,
    p4_min: int | None = None,
    p4_max: int | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    q: str | None = None,
):
    stmt = select(Batch).order_by(Batch.created_at.desc())
    if scene_id:
        stmt = stmt.where(Batch.scene_id == scene_id)
    if platform:
        stmt = stmt.where(Batch.platform == platform)
    if p4_min is not None:
        stmt = stmt.where(Batch.p4_version >= p4_min)
    if p4_max is not None:
        stmt = stmt.where(Batch.p4_version <= p4_max)
    if created_from:
        try:
            stmt = stmt.where(Batch.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            pass
    if created_to:
        try:  # 含当天:截止日 +1 天的零点之前
            stmt = stmt.where(Batch.created_at < datetime.fromisoformat(created_to) + timedelta(days=1))
        except ValueError:
            pass
    if q:
        stmt = stmt.where(Batch.id.contains(q))
    batches = db.scalars(stmt).all()
    return {"total": len(batches), "items": [batch_dto(b, db) for b in batches]}


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, db: Session = Depends(get_db)):
    """其他模块上报批次:先建批次,再逐张上传截图。"""
    batch_id = safe_segment(body.id, "batch id") if body.id else datetime.now().strftime("%Y%m%d_%H%M%S")
    if db.get(Batch, batch_id):
        raise HTTPException(409, f"batch {batch_id} already exists")
    batch = Batch(
        id=batch_id, scene_id=body.scene_id, p4_version=body.p4_version,
        platform=normalize_platform(body.platform), creator=body.creator,
        batch_url=body.batch_url, resolution=body.resolution,
        capture_type=body.capture_type,
        levelsequence_name=body.levelsequence_name,
        levelsequence_path=body.levelsequence_path,
    )
    if body.captured_at:
        try:
            batch.created_at = datetime.fromisoformat(body.captured_at)
        except ValueError:
            pass  # 解析失败则保留默认 now()
    db.add(batch)
    db.commit()
    return batch_dto(batch, db)


@app.post("/api/batches/{batch_id}/screenshots", status_code=201)
def upload_screenshot(
    batch_id: str,
    scene_name: str = Form(...),
    file: UploadFile = File(...),
    camera: str | None = Form(None),       # JSON 字符串:{location, rotation}
    frame_index: int | None = Form(None),
    db: Session = Depends(get_db),
):
    if not db.get(Batch, batch_id):
        raise HTTPException(404, "batch not found")
    scene_name = safe_segment(scene_name, "scene name")
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
    cam = None
    if camera:
        try:
            cam = json.loads(camera)
        except json.JSONDecodeError:
            cam = None
    shot = Screenshot(
        batch_id=batch_id, scene_name=scene_name, path=path,
        camera=cam, frame_index=frame_index,
    )
    db.add(shot)
    db.commit()
    return {"id": shot.id, "scene_name": scene_name, "url": shot.url}


@app.get("/api/batches/{batch_id}/screenshots")
def list_screenshots(batch_id: str, db: Session = Depends(get_db)):
    """列出某批次的全部截图(用于批次预览画廊),按帧序/名称排序。"""
    if not db.get(Batch, batch_id):
        raise HTTPException(404, "batch not found")
    shots = db.scalars(
        select(Screenshot)
        .where(Screenshot.batch_id == batch_id)
        .order_by(Screenshot.frame_index, Screenshot.scene_name)
    ).all()
    return {
        "total": len(shots),
        "items": [
            {"scene_name": s.scene_name, "url": s.url, "frame_index": s.frame_index}
            for s in shots
        ],
    }


# ---------------------------------------------------------------- 对比

class ComparisonIn(BaseModel):
    batch_id: str       # 当前批次
    ref_batch_id: str   # 参照批次
    force: bool = False  # 已对比过时是否强制重新计算


# 对比后台任务:task_id -> 进度/结果(内存,单进程)
_TASKS: dict = {}
# 并发护栏:串行化"查重/建行/起任务"这段;同一对比同时只跑一个计算任务
_COMPARE_LOCK = threading.Lock()
_RUNNING: dict[int, str] = {}   # comparison_id -> 正在计算它的 task_id

# 完成/失败的任务保留时长;超时后清理,避免 _TASKS 无限增长。
_TASK_TTL_SECONDS = 3600


def _prune_tasks(now: float | None = None) -> None:
    """删除已结束(done/error)且超过 TTL 的任务条目;running 的一律保留。

    调用方应已持有 _COMPARE_LOCK(在临界区内调用)。
    """
    now = now if now is not None else time.monotonic()
    stale = [
        tid for tid, t in _TASKS.items()
        if t["status"] in ("done", "error")
        and now - t.get("finished_at", now) > _TASK_TTL_SECONDS
    ]
    for tid in stale:
        _TASKS.pop(tid, None)


def _run_compare_task(task_id, comparison_id, batch_id, ref_id, baseline_id, settings):
    """后台线程:用独立 session 把结果填进已存在的 comparison 行,过程中更新进度。"""
    db = SessionLocal()
    try:
        comparison = db.get(Comparison, comparison_id)
        batch = db.get(Batch, batch_id)
        ref = db.get(Batch, ref_id)
        baseline = db.get(Baseline, baseline_id) if baseline_id else None

        def on_progress(done, total):
            _TASKS[task_id]["done"] = done
            _TASKS[task_id]["total"] = total

        run_comparison(db, comparison, batch, ref, baseline, settings, on_progress=on_progress)
        db.commit()
        _TASKS[task_id].update(status="done", comparison_id=comparison_id, finished_at=time.monotonic())
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _TASKS[task_id].update(status="error", error=str(e), finished_at=time.monotonic())
    finally:
        with _COMPARE_LOCK:
            _RUNNING.pop(comparison_id, None)
        db.close()


@app.post("/api/comparisons", status_code=202)
def create_comparison(body: ComparisonIn, db: Session = Depends(get_db)):
    """发起对比:已对比过直接复用(立即返回);否则起后台任务,前端轮询进度。

    同一对批次(batch × ref)至多一条对比记录,重算复用同一行(id 不变,
    不会把正在查看该结果的其他人弄成 404);并发触发同一对比只跑一次。
    """
    batch = db.get(Batch, body.batch_id)
    ref = db.get(Batch, body.ref_batch_id)
    if not batch or not ref:
        raise HTTPException(404, "batch not found")
    if batch.id == ref.id:
        raise HTTPException(400, "不能与自身对比")
    if batch.scene_id != ref.scene_id:
        raise HTTPException(400, "两个批次的场景ID不同,无法对比")

    baseline = db.scalar(
        select(Baseline).where(
            Baseline.source_batch_id == ref.id, Baseline.status == "active"
        )
    )

    # 临界区:查重 / 建行 / 起任务,避免并发产生重复对比或重复计算
    with _COMPARE_LOCK:
        comparison = db.scalars(
            select(Comparison)
            .where(Comparison.batch_id == batch.id, Comparison.ref_batch_id == ref.id)
            .order_by(Comparison.created_at.desc())
        ).first()
        if comparison and not body.force:
            return {"status": "done", "comparison": comparison_dto(comparison, db)}
        if comparison is None:
            # 先建空行拿到稳定 id;唯一索引兜底防重复
            comparison = Comparison(
                batch_id=batch.id, ref_batch_id=ref.id,
                baseline_id=baseline.id if baseline else None,
            )
            db.add(comparison)
            db.commit()
        cid = comparison.id

        # 已有任务在算这条对比 -> 直接复用其进度,不重复起线程
        if cid in _RUNNING:
            t = _TASKS.get(_RUNNING[cid], {})
            return {"task_id": _RUNNING[cid], "status": t.get("status", "running"),
                    "done": t.get("done", 0), "total": t.get("total", 0)}

        _prune_tasks()
        task_id = uuid.uuid4().hex
        _TASKS[task_id] = {"status": "running", "done": 0, "total": 0, "comparison_id": cid, "error": None}
        _RUNNING[cid] = task_id
        threading.Thread(
            target=_run_compare_task,
            args=(task_id, cid, batch.id, ref.id, baseline.id if baseline else None, get_settings(db)),
            daemon=True,
        ).start()
    return {"task_id": task_id, "status": "running", "done": 0, "total": 0}


@app.get("/api/comparisons/tasks/{task_id}")
def get_comparison_task(task_id: str, db: Session = Depends(get_db)):
    """轮询对比任务进度;完成后带上结果 comparison。"""
    t = _TASKS.get(task_id)
    if not t:
        raise HTTPException(404, "task not found")
    resp = {"status": t["status"], "done": t["done"], "total": t["total"]}
    if t["status"] == "done" and t["comparison_id"]:
        resp["comparison"] = comparison_dto(db.get(Comparison, t["comparison_id"]), db)
    elif t["status"] == "error":
        resp["error"] = t["error"]
    return resp


@app.get("/api/comparisons")
def list_comparisons(
    db: Session = Depends(get_db),
    scene_id: str | None = None,
    platform: str | None = None,
    baseline: str | None = None,
    status: str | None = None,
    q: str | None = None,
):
    stmt = (
        select(Comparison)
        .join(Batch, Comparison.batch_id == Batch.id)
        .order_by(Comparison.created_at.desc())
    )
    if scene_id:
        stmt = stmt.where(Batch.scene_id == scene_id)
    if platform:
        stmt = stmt.where(Batch.platform == platform)
    if baseline:
        stmt = stmt.join(Baseline, Comparison.baseline_id == Baseline.id).where(
            Baseline.version == baseline
        )
    if status:
        stmt = stmt.where(Comparison.status == status)
    if q:
        stmt = stmt.where(Batch.id.contains(q))
    comparisons = db.scalars(stmt).all()
    return {"total": len(comparisons), "items": [comparison_dto(c, db) for c in comparisons]}


@app.get("/api/comparisons/{comparison_id}/scenes")
def list_scenes(
    comparison_id: int,
    db: Session = Depends(get_db),
    status: str | None = None,
    q: str | None = None,
    sort: str = "name",  # name(场景名升序) | diff(差异率降序)
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

    if sort == "diff":
        # 差异率降序,无差异率(新增/缺失)排最后
        order = (ComparisonItem.diff_pct.is_(None), ComparisonItem.diff_pct.desc())
    else:
        order = (ComparisonItem.scene_name,)

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
        base.order_by(*order)
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
                "scene_id": b.scene_id,
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


class SettingsIn(BaseModel):
    pixel_diff_threshold: int | None = None
    fail_threshold: float | None = None
    warn_threshold: float | None = None
    heatmap_blur: int | None = None
    heatmap_sensitivity: float | None = None


@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@app.put("/api/settings")
def update_settings(body: SettingsIn, db: Session = Depends(get_db)):
    return save_settings(db, body.model_dump(exclude_none=True))


@app.get("/api/meta")
def get_meta(db: Session = Depends(get_db)):
    """筛选器选项。"""
    return {
        "scene_ids": db.scalars(select(Batch.scene_id).distinct()).all(),
        "platforms": db.scalars(select(Batch.platform).distinct()).all(),
        "baselines": db.scalars(select(Baseline.version).distinct()).all(),
    }


# ---------------------------------------------------------------- 生产:托管前端构建产物
# 单端口同源部署:FastAPI 直接伺服 vite build 出的静态页面(/),
# /api、/images 在上面已注册,优先匹配;此挂载放最后兜底其余路径。
# 仅当存在 frontend/dist 时挂载;开发模式(vite dev)下不存在,跳过即可。
from pathlib import Path  # noqa: E402

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
