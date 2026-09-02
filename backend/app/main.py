import json
import hashlib
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote

# Windows 上 .webp 可能未注册,确保静态文件返回正确 Content-Type
mimetypes.add_type("image/webp", ".webp")

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import Integer, and_, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .cleanup import prune_orphans
from .errors import ApiError
from .backup import backup_scheduler
from .db import IMAGES_DIR, THUMB_DIR, SessionLocal, get_db, initialize_database
from .logging_setup import client_log, log, setup_logging
from .gpm_heatmap import router as gpm_heatmap_router
from .gpm_retention import gpm_retention_scheduler
from .gpm_storage import GpmSchemaMismatchError, initialize_gpm_database
from .map_build import (
    FORMAT_VERSION as MAP_BUILD_FORMAT_VERSION,
    MapBuildDataIn,
    SnapshotContentConflict,
    get_overview as get_map_build_overview,
    get_trend as get_map_build_trend,
    list_meta as list_map_build_meta,
    store_snapshot as store_map_build_snapshot,
)
from .models import (
    Baseline,
    Batch,
    Comparison,
    ComparisonItem,
    MapBuildSnapshot,
    QualityRun,
    Screenshot,
)
from .quality_runs import (
    is_run_available,
    quality_run_dto,
    ready_counts,
    ready_scene_counts_by_batch,
    resolve_quality_run,
    runs_by_batch,
    runs_with_ready_counts_by_batch,
)
from .service import run_comparison
from .settings import get_settings, save_settings
from .task_executor import BoundedDaemonExecutor
from .thumbnails import ThumbnailService

setup_logging()
initialize_database()
try:
    initialize_gpm_database()
except GpmSchemaMismatchError:
    # 结构不匹配必须阻止进程启动，避免服务以半可用状态运行并掩盖部署错误。
    raise
except Exception:
    # GPMHeatmap 是独立数据域；其单独磁盘或配置异常不能阻断截图对比和烘培数据。
    # GPM API 首次访问时会再次尝试初始化，并返回该模块自己的错误。
    log.exception("GPMHeatmap 数据库初始化失败，其他模块继续启动")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    thumbnail_service.start()
    comparison_executor.start()
    backup_scheduler.start()
    gpm_retention_scheduler.start()
    try:
        yield
    finally:
        gpm_retention_scheduler.stop()
        thumbnail_service.stop()
        comparison_executor.stop()
        backup_scheduler.stop()


app = FastAPI(title="ShotDiff API", version="0.4.0", lifespan=lifespan)
app.include_router(gpm_heatmap_router)
app.add_middleware(
    CORSMiddleware,
    # 局域网/任意来源访问(内网工具,无凭证);如需收紧改回白名单
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)
class _CachedStatic(StaticFiles):
    """给静态图片加长缓存头(覆盖/重算时接口生成的 cache_version 会变化)。
    二次查看(放大/详情)直接命中浏览器缓存,不重复下载。"""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers.setdefault("Cache-Control", "public, max-age=86400")
        return resp


app.mount("/images", _CachedStatic(directory=IMAGES_DIR), name="images")

# ---- 缩略图:缓存命中直接返回；未命中立即回退原图并在有界守护线程中生成 ----
thumbnail_service = ThumbnailService(IMAGES_DIR, THUMB_DIR)
comparison_executor = BoundedDaemonExecutor(
    "pixelcomp-compare", "PIXELCOMP_COMPARE_WORKERS", default_workers=2
)


@app.exception_handler(ApiError)
async def _api_error_handler(_request: Request, error: ApiError):
    content = {
        "detail": error.message,  # 兼容现有前端与旧调用方
        "code": error.code,
        "message": error.message,
    }
    if error.details is not None:
        content["details"] = error.details
    return JSONResponse(status_code=error.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def _request_validation_handler(request: Request, error: RequestValidationError):
    # 新批次 manifest 在进入路由前由 Pydantic 拒绝；为它补稳定错误码。
    if request.method == "POST" and request.url.path == "/api/batches":
        details = error.errors()
        message = str(details[0].get("msg", "manifest 结构非法")) if details else "manifest 结构非法"
        message = message.removeprefix("Value error, ")
        if "shading_quality 不能重复" in message:
            code = "DUPLICATE_SHADING_QUALITY"
        elif "quality_run_index 不能重复" in message:
            code = "DUPLICATE_QUALITY_RUN_INDEX"
        else:
            code = "INVALID_MANIFEST"
        return JSONResponse(status_code=422, content={
            "detail": message,
            "code": code,
            "message": message,
            "details": jsonable_encoder(details),
        })
    return await request_validation_exception_handler(request, error)


def _thumb_relative_path(path: str) -> Path:
    """只接受普通 URL 相对路径，不触碰远程文件系统即可完成校验。"""
    if not path or "\\" in path or "\x00" in path:
        raise HTTPException(404, "not found")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(
        part in ("", ".", "..") or ":" in part for part in pure.parts
    ):
        raise HTTPException(404, "not found")
    if pure.parts[0] == "thumbs":
        raise HTTPException(404, "not found")
    return Path(*pure.parts)


@app.get("/thumb/{path:path}")
async def get_thumb(path: str, request: Request, strict: bool = Query(False)):
    """本地缓存命中返回 WebP；未命中异步生成。

    默认兼容旧调用方并 307 回退原图；strict=true 只返回 202，供批次画廊保证
    用户点击灯箱前绝不读取原图。两种模式都不会等待远程 I/O。
    """
    relative = _thumb_relative_path(path)
    cache = thumbnail_service.cache_path(relative)
    if cache.is_file():
        try:
            if time.time() - cache.stat().st_mtime > 86400:
                cache.touch()
        except OSError:
            pass
        return FileResponse(
            cache,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    thumbnail_service.submit(relative)
    if strict:
        return Response(
            status_code=202,
            headers={"Cache-Control": "no-store", "Retry-After": "1"},
        )
    encoded_path = "/".join(quote(part, safe="") for part in relative.parts)
    target = f"/images/{encoded_path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(
        target,
        status_code=307,
        headers={"Cache-Control": "no-store"},
    )


@app.middleware("http")
async def _log_requests(request, call_next):
    """记录 /api 请求:进入打 →,完成打 ← 状态 + 耗时(client-logs 自身不记,避免噪音)。"""
    path = request.url.path
    if not path.startswith("/api") or path == "/api/client-logs":
        return await call_next(request)
    t0 = time.perf_counter()
    log.info("→ %s %s", request.method, path)
    try:
        resp = await call_next(request)
    except Exception:
        log.exception("✗ %s %s 处理异常", request.method, path)
        raise
    ms = (time.perf_counter() - t0) * 1000
    log.info("← %s %s %s (%.0fms)", resp.status_code, request.method, path, ms)
    return resp

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


# 画质档位(UE shading_quality)→ 展示名;历史数据无此字段时按「极致」展示。
_SHADING_QUALITY_LABELS = {5: "电影", 4: "极致", 3: "精美", 2: "均衡", 1: "流畅", 0: "节能"}
_DEFAULT_SHADING_QUALITY = 4


def shading_quality_label(value: int | None) -> str:
    v = value if value is not None else _DEFAULT_SHADING_QUALITY
    return _SHADING_QUALITY_LABELS.get(v, str(v))


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


_BRANCH_TAG_PATTERN = re.compile(r"^[a-z0-9._/-]{1,128}$")


def normalize_branch_tag(raw: str | None) -> str:
    """把上报和筛选使用的分支标签收敛为稳定的小写标识。"""
    if raw is not None and not isinstance(raw, str):
        raise ValueError("branch_tag 必须是字符串")
    value = (raw or "main").strip().lower()
    if not _BRANCH_TAG_PATTERN.fullmatch(value):
        raise ValueError("branch_tag 只能包含字母、数字、.、_、-、/，长度 1-128")
    return value


def require_batch_branch(db: Session, batch_id: str, raw_branch_tag: str | None) -> Batch:
    """返回批次，并确保本次写入明确属于同一分支。"""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, "batch not found")
    try:
        branch_tag = normalize_branch_tag(raw_branch_tag)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if batch.branch_tag != branch_tag:
        raise HTTPException(
            409,
            f"batch {batch_id} belongs to branch {batch.branch_tag}, not {branch_tag}",
        )
    return batch


def safe_segment(value: str, field: str) -> str:
    """收口落盘用的路径段:禁止分隔符 / 上跳,防目录遍历。"""
    if not value or value in (".", "..") or "/" in value or "\\" in value or "\0" in value:
        raise HTTPException(400, f"非法的 {field}: {value!r}")
    return value


# ---------------------------------------------------------------- DTO

_UNSET = object()


def batch_dto(
    b: Batch,
    db: Session,
    *,
    scene_count: int | None = None,
    has_map_build_data: bool | object = _UNSET,
    quality_runs: list[QualityRun] | None = None,
    run_ready_counts: dict[int, int] | None = None,
) -> dict:
    if quality_runs is None:
        quality_runs = db.scalars(
            select(QualityRun)
            .where(QualityRun.batch_id == b.id)
            .order_by(QualityRun.shading_quality.desc())
        ).all()
    if run_ready_counts is None:
        run_ready_counts = ready_counts(db, [run.id for run in quality_runs])
    run_items = [
        quality_run_dto(run, run_ready_counts.get(run.id, 0))
        for run in quality_runs
    ]
    if scene_count is None:
        scene_count = ready_scene_counts_by_batch(db, [b.id]).get(b.id, 0)
    if has_map_build_data is _UNSET:
        has_map_build_data = db.get(MapBuildSnapshot, b.id) is not None
    qualities = [item["shading_quality"] for item in run_items]
    available_qualities = [
        item["shading_quality"] for item in run_items if item["is_complete"]
    ]
    single_quality = qualities[0] if len(qualities) == 1 else None
    return {
        "id": b.id,
        "branch_tag": b.branch_tag,
        "scene_id": b.scene_id,
        "p4_version": b.p4_version,
        "platform": b.platform,
        "creator": b.creator,
        "batch_url": b.batch_url,
        "resolution": b.resolution,
        "shading_quality": single_quality,
        "shading_quality_label": (
            shading_quality_label(single_quality) if single_quality is not None
            else "、".join(shading_quality_label(value) for value in qualities)
        ),
        "shading_qualities": qualities,
        "available_shading_qualities": available_qualities,
        "quality_runs": run_items,
        "created_at": b.created_at.strftime("%Y-%m-%d %H:%M"),
        "scene_count": scene_count,
        "has_screenshots": bool(available_qualities),
        "has_map_build_data": has_map_build_data,
    }


def _versioned_url(path: str, version: str | int | None) -> str:
    """用数据库版本生成强缓存 URL，热路径绝不访问可能位于共享盘的图片文件。"""
    return f"/images/{path}?v={version}" if version is not None else f"/images/{path}"


def _screenshot_url(shot: Screenshot) -> str:
    # 旧库新增列为空时用稳定行 id；新上传使用随机 cache_version，覆盖后必定变化。
    if not shot.path:
        raise ValueError(f"截图 {shot.id} 尚未就绪")
    return _versioned_url(shot.path, shot.cache_version or shot.id)


def _heatmap_url(item: ComparisonItem) -> str | None:
    if not item.heatmap_path:
        return None
    return _versioned_url(item.heatmap_path, item.cache_version or item.id)


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
    current_quality = (
        c.current_quality_run.shading_quality
        if c.current_quality_run is not None else
        (c.batch.shading_quality if c.batch.shading_quality is not None else _DEFAULT_SHADING_QUALITY)
    )
    reference_quality = (
        c.reference_quality_run.shading_quality
        if c.reference_quality_run is not None else
        (c.ref_batch.shading_quality if c.ref_batch.shading_quality is not None else _DEFAULT_SHADING_QUALITY)
    )
    return {
        "id": c.id,
        "batch_id": c.batch_id,
        "branch_tag": c.batch.branch_tag,
        "scene_id": c.batch.scene_id,
        "p4_version": c.batch.p4_version,
        "platform": c.batch.platform,
        "creator": c.batch.creator,
        "resolution": c.batch.resolution,
        "shading_quality": current_quality,
        "shading_quality_label": shading_quality_label(current_quality),
        "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
        "batch_created_at": c.batch.created_at.strftime("%Y-%m-%d %H:%M"),       # 对比批次的创建时间
        # 参照批次:有基线版本则显示版本号,否则显示批次号
        "ref_batch_id": c.ref_batch_id,
        "ref_label": c.baseline.version if c.baseline else f"#{c.ref_batch_id}",
        "ref_p4_version": c.ref_batch.p4_version,
        "ref_shading_quality": reference_quality,
        "ref_shading_quality_label": shading_quality_label(reference_quality),
        "ref_created_at": c.ref_batch.created_at.strftime("%Y-%m-%d %H:%M"),     # 参照批次的创建时间
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
        "current_url": _screenshot_url(it.current_shot) if it.current_shot else None,
        "baseline_url": _screenshot_url(it.baseline_shot) if it.baseline_shot else None,
        "heatmap_url": _heatmap_url(it),
    }
    d["thumb_url"] = d["current_url"] or d["baseline_url"]
    # 相机位姿:优先取当前批截图,缺则取参照批
    cam_shot = it.current_shot or it.baseline_shot
    d["camera"] = cam_shot.camera if cam_shot else None
    if with_metrics:
        d["metrics"] = it.metrics
    return d


# ---------------------------------------------------------------- 批次(上报 + 查询)

class ScreenshotPlanIn(BaseModel):
    scene_name: str
    source_relative_path: str
    frame_index: int | None = None
    camera: dict | None = None

    @model_validator(mode="after")
    def validate_plan(self):
        if (not self.scene_name or self.scene_name in (".", "..")
                or "/" in self.scene_name or "\\" in self.scene_name
                or "\0" in self.scene_name):
            raise ValueError("非法的 scene_name")
        path = PurePosixPath(self.source_relative_path)
        if (not self.source_relative_path or "\\" in self.source_relative_path
                or path.is_absolute() or any(
                    part in ("", ".", "..") or ":" in part for part in path.parts
                )):
            raise ValueError("source_relative_path 必须是安全相对路径")
        return self


class QualityRunPlanIn(BaseModel):
    quality_run_index: int
    shading_quality: int
    tex_quality: int | None = None
    capture_status: Literal["complete"] = "complete"
    screenshots: list[ScreenshotPlanIn]

    @model_validator(mode="after")
    def validate_run(self):
        if self.quality_run_index < 0:
            raise ValueError("quality_run_index 必须为非负整数")
        if self.shading_quality not in _SHADING_QUALITY_LABELS:
            raise ValueError("shading_quality 必须在 0..5")
        if not self.screenshots:
            raise ValueError("画质运行至少需要一张截图")
        names = [shot.scene_name for shot in self.screenshots]
        if len(names) != len(set(names)):
            raise ValueError("同一画质运行的 scene_name 不能重复")
        return self


class BatchIn(BaseModel):
    id: str | None = None
    scene_id: str
    branch_tag: str = "main"
    p4_version: int | None = None
    platform: str
    creator: str = "CI机器人"
    # 新版上报附带(均可选)
    batch_url: str | None = None
    resolution: str | None = None
    capture_type: str | None = None
    levelsequence_name: str | None = None
    levelsequence_path: str | None = None
    shading_quality: int | None = None
    manifest_format_version: int | None = None
    source_manifest_sha256: str | None = None
    quality_runs: list[QualityRunPlanIn] | None = None
    captured_at: str | None = None
    overwrite: bool = False        # 同号批次已存在时:True=删旧建新(级联清对比/热力图),False=409

    @field_validator("branch_tag", mode="before")
    @classmethod
    def validate_branch_tag(cls, value):
        return normalize_branch_tag(value)

    @model_validator(mode="after")
    def validate_quality_runs(self):
        if self.shading_quality is not None and self.shading_quality not in _SHADING_QUALITY_LABELS:
            raise ValueError("shading_quality 必须在 0..5")
        if self.source_manifest_sha256 is not None and not re.fullmatch(
            r"[0-9a-fA-F]{64}", self.source_manifest_sha256
        ):
            raise ValueError("source_manifest_sha256 必须是 64 位十六进制 SHA-256")
        if self.quality_runs is not None:
            qualities = [run.shading_quality for run in self.quality_runs]
            indexes = [run.quality_run_index for run in self.quality_runs]
            if len(qualities) != len(set(qualities)):
                raise ValueError("同一批次的 shading_quality 不能重复")
            if len(indexes) != len(set(indexes)):
                raise ValueError("同一批次的 quality_run_index 不能重复")
            if self.shading_quality is not None:
                raise ValueError("多画质请求不能同时设置批次级 shading_quality")
        return self


def _apply_batch_date_filters(
    stmt,
    created_from: str | None,
    created_to: str | None,
    created_dates: list[str] | None,
):
    """统一批次目录、截图网格和场景可用性的本地日期筛选语义。"""
    if created_from:
        try:
            stmt = stmt.where(Batch.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            pass
    if created_to:
        try:  # 含当天:截止日 +1 天的零点之前
            stmt = stmt.where(
                Batch.created_at < datetime.fromisoformat(created_to) + timedelta(days=1)
            )
        except ValueError:
            pass
    if created_dates:  # 指定多天(跳着选):按本地日期 IN 匹配
        stmt = stmt.where(func.date(Batch.created_at).in_(created_dates))
    return stmt


@app.get("/api/scene-availability")
def scene_availability(
    capability: Literal["batches", "screenshots"],
    created_from: str | None = None,
    created_to: str | None = None,
    created_dates: list[str] | None = Query(None),
    branch_tag: str = "main",
    shading_quality: int | None = None,
    db: Session = Depends(get_db),
):
    """返回除场景本身外、匹配当前筛选条件的场景 ID 集合。"""
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    if capability == "batches":
        stmt = select(Batch.scene_id).where(Batch.branch_tag == branch_tag)
        if shading_quality is not None:
            # 批次管理展示已声明画质；上传中的不完整运行也属于匹配批次。
            stmt = stmt.where(Batch.quality_runs.any(
                QualityRun.shading_quality == shading_quality
            ))
    else:
        ready = (
            select(
                Screenshot.quality_run_id.label("quality_run_id"),
                func.count(Screenshot.id).label("ready_count"),
            )
            .where(Screenshot.upload_status == "ready")
            .group_by(Screenshot.quality_run_id)
            .subquery()
        )
        ready_count = func.coalesce(ready.c.ready_count, 0)
        available_run = or_(
            and_(QualityRun.capture_status == "legacy", ready_count > 0),
            and_(
                QualityRun.capture_status == "complete",
                QualityRun.expected_screenshot_count > 0,
                ready_count == QualityRun.expected_screenshot_count,
            ),
        )
        stmt = (
            select(Batch.scene_id)
            .join(QualityRun, QualityRun.batch_id == Batch.id)
            .outerjoin(ready, ready.c.quality_run_id == QualityRun.id)
            .where(Batch.branch_tag == branch_tag, available_run)
        )
        if shading_quality is not None:
            stmt = stmt.where(QualityRun.shading_quality == shading_quality)

    stmt = _apply_batch_date_filters(stmt, created_from, created_to, created_dates)
    scene_ids = sorted(
        set(db.scalars(stmt.distinct()).all()),
        key=lambda scene_id: (scene_id.casefold(), scene_id),
    )
    return {"capability": capability, "scene_ids": scene_ids}


@app.get("/api/batches")
def list_batches(
    db: Session = Depends(get_db),
    scene_id: str | None = None,
    branch_tag: str = "main",
    platform: str | None = None,
    shading_quality: int | None = None,
    p4_min: int | None = None,
    p4_max: int | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    created_dates: list[str] | None = Query(None),
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
):
    # 批次号大的排前面(一眼看到最新);id 是字符串,按数值排序,非数字/相同回退按创建时间。
    # 末尾再按 id 本身兜底,保证是全序(created_at 因 --time 撞车时分页仍不重不漏)。
    stmt = select(Batch).order_by(
        cast(Batch.id, Integer).desc(), Batch.created_at.desc(), Batch.id.desc())
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    stmt = stmt.where(Batch.branch_tag == branch_tag)
    if scene_id:
        stmt = stmt.where(Batch.scene_id == scene_id)
    if platform:
        stmt = stmt.where(Batch.platform == platform)
    if shading_quality is not None:
        stmt = stmt.where(Batch.quality_runs.any(
            QualityRun.shading_quality == shading_quality
        ))
    if p4_min is not None:
        stmt = stmt.where(Batch.p4_version >= p4_min)
    if p4_max is not None:
        stmt = stmt.where(Batch.p4_version <= p4_max)
    stmt = _apply_batch_date_filters(stmt, created_from, created_to, created_dates)
    if q:
        stmt = stmt.where(Batch.id.contains(q))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if page_size is not None:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    batches = db.scalars(stmt).all()
    batch_ids = [batch.id for batch in batches]
    grouped_runs, all_ready_counts, scene_counts = runs_with_ready_counts_by_batch(
        db, batch_ids
    )
    map_build_batch_ids = set(
        db.scalars(
            select(MapBuildSnapshot.batch_id).where(
                MapBuildSnapshot.batch_id.in_(batch_ids)
            )
        ).all()
    ) if batch_ids else set()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            batch_dto(
                batch,
                db,
                scene_count=scene_counts.get(batch.id, 0),
                has_map_build_data=batch.id in map_build_batch_ids,
                quality_runs=grouped_runs.get(batch.id, []),
                run_ready_counts=all_ready_counts,
            )
            for batch in batches
        ],
    }


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    """按全局唯一批次号读取完整元数据，供前端深链恢复筛选和角色。"""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, "batch not found")
    return batch_dto(batch, db)


# 自动生成批次号时串行化,避免并发取到同一个序号
_BATCH_LOCK = threading.Lock()


def _next_batch_id(db: Session) -> str:
    """未指定批次号时:取已有纯数字批次号的最大值 +1(从 1 起),并避开已占用的号。"""
    mx = 0
    for i in db.scalars(select(Batch.id)):
        if i is not None and i.isdigit():
            mx = max(mx, int(i))
    nid = mx + 1
    while db.get(Batch, str(nid)):
        nid += 1
    return str(nid)


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, db: Session = Depends(get_db)):
    """原子创建批次、画质运行和截图计划；旧单画质请求保持兼容。

    未指定 id 时按已有数字批次号自增生成(1、2、3…)。
    """
    with _BATCH_LOCK:
        overwritten_ids: list[str] = []
        overwritten_comparison_ids: list[int] = []
        normalized_platform = normalize_platform(body.platform)
        if body.id:
            batch_id = safe_segment(body.id, "batch id")
            existing = db.get(Batch, batch_id)
            if existing:
                if existing.branch_tag != body.branch_tag:
                    raise ApiError(
                        409, "BATCH_BRANCH_IMMUTABLE",
                        f"batch {batch_id} belongs to branch {existing.branch_tag}; "
                        "branch_tag is immutable",
                    )
                if (existing.scene_id != body.scene_id
                        or existing.platform != normalized_platform):
                    raise ApiError(
                        409,
                        "BATCH_SCOPE_IMMUTABLE",
                        f"batch {batch_id} scope is immutable "
                        f"(scene_id={existing.scene_id}, platform={existing.platform})",
                    )
                if not body.overwrite:
                    raise ApiError(
                        409, "BATCH_ALREADY_EXISTS", f"batch {batch_id} already exists"
                    )
                overwritten_comparison_ids = list(db.scalars(
                    select(Comparison.id).where(or_(
                        Comparison.batch_id == batch_id,
                        Comparison.ref_batch_id == batch_id,
                    ))
                ))
                # 请求体已经由 Pydantic 完整校验。数据库删除与新计划创建放在同一事务；
                # 只有提交成功后才清旧文件和内存任务。
                _cascade_delete_batches(db, [existing], commit=False, cleanup_runtime=False)
                overwritten_ids.append(batch_id)
        else:
            batch_id = _next_batch_id(db)
        # v2 可以省略 quality_runs 表示纯烘培/诊断批次，但绝不能因此落入
        # “上传一张即完整”的 legacy 兼容分支。只有真正的旧协议才创建 legacy。
        declared_runs = (
            []
            if body.manifest_format_version is not None
            and body.manifest_format_version >= 2
            and body.quality_runs is None
            else body.quality_runs
        )
        single_quality = (
            declared_runs[0].shading_quality
            if declared_runs is not None and len(declared_runs) == 1
            else body.shading_quality if declared_runs is None else None
        )
        batch = Batch(
            id=batch_id, branch_tag=body.branch_tag,
            scene_id=body.scene_id, p4_version=body.p4_version,
            platform=normalized_platform, creator=body.creator,
            batch_url=body.batch_url, resolution=body.resolution,
            capture_type=body.capture_type,
            levelsequence_name=body.levelsequence_name,
            levelsequence_path=body.levelsequence_path,
            shading_quality=single_quality,
            manifest_format_version=body.manifest_format_version,
            source_manifest_sha256=(
                body.source_manifest_sha256.lower()
                if body.source_manifest_sha256 else None
            ),
        )
        if body.captured_at:
            try:
                batch.created_at = datetime.fromisoformat(body.captured_at)
            except ValueError:
                pass  # 解析失败则保留默认 now()
        db.add(batch)
        db.flush()
        if declared_runs is None:
            # 未升级客户端没有截图计划/finalize；保留“至少上传一张即可使用”的 legacy 语义。
            db.add(QualityRun(
                batch_id=batch_id,
                quality_run_index=0,
                shading_quality=body.shading_quality
                if body.shading_quality is not None else _DEFAULT_SHADING_QUALITY,
                tex_quality=None,
                capture_status="legacy",
                expected_screenshot_count=0,
            ))
        else:
            for run_plan in declared_runs:
                run = QualityRun(
                    batch_id=batch_id,
                    quality_run_index=run_plan.quality_run_index,
                    shading_quality=run_plan.shading_quality,
                    tex_quality=run_plan.tex_quality,
                    capture_status=run_plan.capture_status,
                    expected_screenshot_count=len(run_plan.screenshots),
                )
                db.add(run)
                db.flush()
                db.add_all([
                    Screenshot(
                        batch_id=batch_id,
                        quality_run_id=run.id,
                        scene_name=shot.scene_name,
                        path=None,
                        source_relative_path=shot.source_relative_path,
                        upload_status="pending",
                        frame_index=shot.frame_index,
                        camera=shot.camera,
                    )
                    for shot in run_plan.screenshots
                ])
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ApiError(
                409, "BATCH_PLAN_CONFLICT", "批次画质运行或截图计划与现有数据冲突"
            ) from exc
        if overwritten_ids:
            _cleanup_deleted_batch_runtime(overwritten_ids, overwritten_comparison_ids)
            prune_orphans(db)
            log.info("覆盖批次 #%s", batch_id)
        log.info("建批次 #%s 场景=%s 平台=%s", batch_id, batch.scene_id, batch.platform)
        return batch_dto(batch, db)


_SCREENSHOT_COMMIT_LOCK = threading.Lock()
_UPLOAD_MAX_BYTES = max(1, int(os.environ.get("PIXELCOMP_MAX_SCREENSHOT_BYTES", 100 * 1024 * 1024)))


def _camera_form(value: str | None) -> dict | None:
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "camera 必须是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(422, "camera 必须是 JSON object")
    return parsed


def _stream_upload(file: UploadFile, directory: Path, scene_name: str) -> tuple[Path, str, int]:
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f".{scene_name}.{uuid.uuid4().hex}.upload"
    digest = hashlib.sha256()
    size = 0
    try:
        with temp.open("xb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > _UPLOAD_MAX_BYTES:
                    raise ApiError(413, "SCREENSHOT_TOO_LARGE", "截图文件超过大小限制")
                digest.update(chunk)
                output.write(chunk)
        with temp.open("rb") as source:
            if source.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ApiError(422, "INVALID_SCREENSHOT", "截图必须是有效 PNG 文件")
        return temp, digest.hexdigest(), size
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _store_screenshot(
    *,
    batch: Batch,
    run: QualityRun,
    scene_name: str,
    file: UploadFile,
    camera: str | None,
    frame_index: int | None,
    db: Session,
    idempotent_retry: bool = True,
):
    scene_name = safe_segment(scene_name, "scene name")
    cam = _camera_form(camera)
    quality_path = None if run.capture_status == "legacy" else str(run.shading_quality)
    out_dir = IMAGES_DIR / "batches" / batch.id
    if quality_path is not None:
        out_dir /= quality_path
    temp, sha256, byte_size = _stream_upload(file, out_dir, scene_name)
    relative_path = (
        f"batches/{batch.id}/{scene_name}.png"
        if quality_path is None
        else f"batches/{batch.id}/{quality_path}/{scene_name}.png"
    )
    final_path = IMAGES_DIR / relative_path
    try:
        with _SCREENSHOT_COMMIT_LOCK:
            db.expire_all()
            shot = db.scalar(select(Screenshot).where(
                Screenshot.quality_run_id == run.id,
                Screenshot.scene_name == scene_name,
            ))
            if run.capture_status != "legacy" and shot is None:
                raise ApiError(
                    422, "SCREENSHOT_NOT_IN_PLAN",
                    f"scene {scene_name} 不在已注册截图计划中",
                )
            if shot is not None and shot.upload_status == "ready":
                if idempotent_retry and shot.sha256 and shot.sha256 == sha256:
                    temp.unlink(missing_ok=True)
                    return JSONResponse(status_code=200, content={
                        "id": shot.id,
                        "scene_name": scene_name,
                        "shading_quality": run.shading_quality,
                        "url": _screenshot_url(shot),
                        "idempotent": True,
                    })
                raise ApiError(
                    409, "SCREENSHOT_CONTENT_CONFLICT",
                    f"scene {scene_name} 已存在且内容不同",
                )

            if shot is None:
                shot = Screenshot(
                    batch_id=batch.id,
                    quality_run_id=run.id,
                    scene_name=scene_name,
                    upload_status="pending",
                )
                db.add(shot)
                db.flush()
            elif run.capture_status != "legacy":
                if frame_index is not None and shot.frame_index != frame_index:
                    raise ApiError(
                        409, "SCREENSHOT_METADATA_CONFLICT",
                        "截图 frame_index 与 manifest 计划不一致",
                    )
                if cam is not None and shot.camera != cam:
                    raise ApiError(
                        409, "SCREENSHOT_METADATA_CONFLICT",
                        "截图 camera 与 manifest 计划不一致",
                    )

            os.replace(temp, final_path)
            shot.path = relative_path
            shot.upload_status = "ready"
            shot.sha256 = sha256
            shot.byte_size = byte_size
            shot.cache_version = uuid.uuid4().hex[:16]
            if run.capture_status == "legacy":
                shot.frame_index = frame_index
                shot.camera = cam
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                final_path.unlink(missing_ok=True)
                raise ApiError(
                    409, "SCREENSHOT_UPLOAD_CONFLICT",
                    f"scene {scene_name} 并发上传冲突",
                ) from exc
        thumbnail_service.submit(Path(relative_path))
        log.info(
            "截图上报成功 batch=%s quality=%s scene=%s bytes=%s sha256=%s",
            batch.id, run.shading_quality, scene_name, byte_size, sha256[:12],
        )
        return {
            "id": shot.id,
            "scene_name": scene_name,
            "shading_quality": run.shading_quality,
            "url": _screenshot_url(shot),
            "idempotent": False,
        }
    finally:
        temp.unlink(missing_ok=True)


@app.post("/api/batches/{batch_id}/quality-runs/{shading_quality}/screenshots", status_code=201)
def upload_quality_screenshot(
    batch_id: str,
    shading_quality: int,
    branch_tag: str = Query("main"),
    scene_name: str = Form(...),
    file: UploadFile = File(...),
    camera: str | None = Form(None),
    frame_index: int | None = Form(None),
    db: Session = Depends(get_db),
):
    batch = require_batch_branch(db, batch_id, branch_tag)
    run, _ = resolve_quality_run(db, batch_id, shading_quality)
    if run is None:
        raise ApiError(404, "QUALITY_RUN_NOT_FOUND", "quality run not found")
    return _store_screenshot(
        batch=batch, run=run, scene_name=scene_name, file=file,
        camera=camera, frame_index=frame_index, db=db, idempotent_retry=True,
    )


@app.post("/api/batches/{batch_id}/screenshots", status_code=201)
def upload_screenshot(
    batch_id: str,
    branch_tag: str = Query("main"),
    scene_name: str = Form(...),
    file: UploadFile = File(...),
    camera: str | None = Form(None),
    frame_index: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """旧单画质上传接口；多画质批次必须使用显式画质路径。"""
    batch = require_batch_branch(db, batch_id, branch_tag)
    run, _ = resolve_quality_run(db, batch_id, None, infer_available=False)
    if run is None:
        raise ApiError(
            422, "AMBIGUOUS_QUALITY_RUN",
            "批次包含多个或没有画质运行，请使用带画质的截图接口",
        )
    return _store_screenshot(
        batch=batch, run=run, scene_name=scene_name, file=file,
        camera=camera, frame_index=frame_index, db=db, idempotent_retry=False,
    )


def _list_run_screenshots(batch_id: str, shading_quality: int | None, db: Session):
    if not db.get(Batch, batch_id):
        raise HTTPException(404, "batch not found")
    run, count = resolve_quality_run(db, batch_id, shading_quality)
    if run is None:
        raise ApiError(422, "AMBIGUOUS_QUALITY_RUN", "无法唯一确定画质运行")
    if run.capture_status != "legacy" and not is_run_available(run, count):
        raise ApiError(409, "QUALITY_RUN_INCOMPLETE", "画质运行尚未完整上传")
    shots = db.scalars(
        select(Screenshot)
        .where(
            Screenshot.quality_run_id == run.id,
            Screenshot.upload_status == "ready",
        )
        .order_by(Screenshot.frame_index, Screenshot.scene_name)
    ).all()
    return {
        "total": len(shots),
        "shading_quality": run.shading_quality,
        "shading_quality_label": shading_quality_label(run.shading_quality),
        "items": [
            {"scene_name": shot.scene_name, "url": _screenshot_url(shot),
             "frame_index": shot.frame_index}
            for shot in shots
        ],
    }


@app.get("/api/batches/{batch_id}/quality-runs/{shading_quality}/screenshots")
def list_quality_screenshots(
    batch_id: str,
    shading_quality: int,
    db: Session = Depends(get_db),
):
    return _list_run_screenshots(batch_id, shading_quality, db)


@app.get("/api/batches/{batch_id}/screenshots")
def list_screenshots(batch_id: str, db: Session = Depends(get_db)):
    return _list_run_screenshots(batch_id, None, db)


# ---------------------------------------------------------------- 场景烘培数据

@app.post("/api/batches/{batch_id}/map-build-data", status_code=201)
def upload_map_build_data(
    batch_id: str,
    body: MapBuildDataIn,
    format: str = Query(MAP_BUILD_FORMAT_VERSION, min_length=1, max_length=64),
    branch_tag: str = Query("main"),
    db: Session = Depends(get_db),
):
    """上报批次随附的 map_build_data；同内容幂等，不同内容要求整批覆盖。"""
    batch = require_batch_branch(db, batch_id, branch_tag)
    try:
        result = store_map_build_snapshot(db, batch, body, format)
    except SnapshotContentConflict as exc:
        raise ApiError(409, "MAP_BUILD_CONTENT_CONFLICT", str(exc)) from exc
    log.info(
        "烘培数据上报成功 batch=%s scene=%s registries=%d updated=%s",
        batch_id,
        batch.scene_id,
        result["registry_count"],
        result["updated"],
    )
    return result


@app.get("/api/map-build/meta")
def map_build_meta(
    branch_tag: str = "main",
    db: Session = Depends(get_db),
):
    """烘培页面可用的场景元数据。"""
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    settings = get_settings(db)
    return list_map_build_meta(
        db,
        branch_tag=branch_tag,
        scene_id_order=settings["scene_id_order"],
        show_unlisted_scene_ids=settings["show_unlisted_scene_ids"],
    )


@app.get("/api/map-build/scenes/{scene_id}/overview")
def map_build_overview(
    scene_id: str,
    branch_tag: str = "main",
    platform: str | None = None,
    shading_quality: int | None = None,
    batch_id: str | None = None,
    db: Session = Depends(get_db),
):
    """最新或指定批次的独立分块网格。"""
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = get_map_build_overview(
        db,
        scene_id,
        branch_tag=branch_tag,
        platform=platform,
        shading_quality=shading_quality,
        batch_id=batch_id,
    )
    if result is None:
        raise HTTPException(404, "当前筛选没有烘培数据")
    return result


@app.get("/api/map-build/scenes/{scene_id}/trend")
def map_build_trend(
    scene_id: str,
    branch_tag: str = "main",
    platform: str | None = None,
    shading_quality: int | None = None,
    block_index: int | None = Query(None, ge=0, le=65535),
    sub_block_index: int | None = Query(None, ge=0, le=65535),
    registry_path: str | None = Query(None, min_length=1, max_length=4096),
    metric_scope: Literal["self", "subtree"] = "self",
    days: int = Query(30, ge=1, le=365),
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    """所选节点最近 N 日或指定日期范围的体积趋势。"""
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    try:
        return get_map_build_trend(
            db,
            scene_id,
            branch_tag=branch_tag,
            platform=platform,
            shading_quality=shading_quality,
            block_index=block_index,
            sub_block_index=sub_block_index,
            registry_path=registry_path,
            metric_scope=metric_scope,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/scenes/{scene_id}/grid")
def scene_grid(
    scene_id: str,
    branch_tag: str = "main",
    platform: str | None = None,
    shading_quality: str | None = None,
    p4_min: int | None = None,
    p4_max: int | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    created_dates: list[str] | None = Query(None),
    q: str | None = None,
    db: Session = Depends(get_db),
):
    """批次列表图:同场景所有批次排成矩阵——列=批次(批次号升序,左旧右新;前端默认滚到最右看最新),
    行=检查点(按 scene_name 对齐、frame_index 排序),cells 与 batches 同序,缺图为 null。

    支持与批次列表一致的筛选(平台/画质/P4范围/创建时间/批次号)。"""
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    selected_quality: int | None = None
    if shading_quality not in (None, "", "all"):
        try:
            selected_quality = int(shading_quality)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "shading_quality 必须为 0..5 或 all") from exc
        if selected_quality not in _SHADING_QUALITY_LABELS:
            raise HTTPException(422, "shading_quality 必须为 0..5 或 all")

    bstmt = select(Batch).where(
        Batch.scene_id == scene_id,
        Batch.branch_tag == branch_tag,
    )
    if platform:
        bstmt = bstmt.where(Batch.platform == platform)
    if selected_quality is not None:
        bstmt = bstmt.where(Batch.quality_runs.any(
            QualityRun.shading_quality == selected_quality
        ))
    if p4_min is not None:
        bstmt = bstmt.where(Batch.p4_version >= p4_min)
    if p4_max is not None:
        bstmt = bstmt.where(Batch.p4_version <= p4_max)
    bstmt = _apply_batch_date_filters(bstmt, created_from, created_to, created_dates)
    if q:
        bstmt = bstmt.where(Batch.id.contains(q))
    # 批次号升序:左旧右新(与列表视图的降序相反),前端进入时默认滚到最右看最新;
    # 按数值排、末尾 id 兜底全序,免疫 --time 撞车。
    batches = db.scalars(bstmt.order_by(
        cast(Batch.id, Integer).asc(), Batch.created_at.asc(), Batch.id.asc())).all()
    batch_map = {batch.id: batch for batch in batches}
    grouped_runs = runs_by_batch(db, list(batch_map))
    candidate_runs = [
        run
        for batch in batches
        for run in grouped_runs.get(batch.id, [])
        if selected_quality is None or run.shading_quality == selected_quality
    ]
    candidate_counts = ready_counts(db, [run.id for run in candidate_runs])
    columns = [
        (batch_map[run.batch_id], run)
        for run in candidate_runs
        if is_run_available(run, candidate_counts.get(run.id, 0))
    ]
    rowmap: dict = {}
    run_ids = [run.id for _, run in columns]
    if run_ids:
        for s in db.scalars(select(Screenshot).where(
            Screenshot.quality_run_id.in_(run_ids),
            Screenshot.upload_status == "ready",
        )):
            r = rowmap.setdefault(
                s.scene_name,
                {"scene_name": s.scene_name, "frame_index": s.frame_index, "by_run": {}},
            )
            r["by_run"][s.quality_run_id] = _screenshot_url(s)
            if s.frame_index is not None and (r["frame_index"] is None or s.frame_index < r["frame_index"]):
                r["frame_index"] = s.frame_index
    rows = sorted(
        rowmap.values(),
        key=lambda r: (r["frame_index"] is None, r["frame_index"] or 0, r["scene_name"]),
    )
    return {
        "scene_id": scene_id,
        "branch_tag": branch_tag,
        "total": len(columns),
        "batches": [
            {"id": batch.id,
             "column_id": f"{batch.id}:{run.shading_quality}",
             "quality_run_id": run.id,
             "scene_id": batch.scene_id, "branch_tag": batch.branch_tag,
             "p4_version": batch.p4_version,
             "created_at": batch.created_at.strftime("%Y-%m-%d %H:%M"),
             "platform": batch.platform,
             "has_screenshots": True,
             "shading_quality": run.shading_quality,
             "shading_quality_label": shading_quality_label(run.shading_quality)}
            for batch, run in columns
        ],
        "rows": [
            {"scene_name": r["scene_name"], "frame_index": r["frame_index"],
             "cells": [r["by_run"].get(run.id) for _, run in columns]}
            for r in rows
        ],
    }


def _cleanup_deleted_batch_runtime(bids: list[str], comp_ids: list[int]) -> None:
    for tid in [
        task_id for task_id, info in _TASKS.items()
        if info.get("comparison_id") in comp_ids
    ]:
        _TASKS.pop(tid, None)
    for bid in bids:
        thumbnail_service.invalidate_prefix(Path("batches") / bid)
        shutil.rmtree(THUMB_DIR / "batches" / bid, ignore_errors=True)


def _cascade_delete_batches(
    db: Session,
    batches: list[Batch],
    *,
    commit: bool = True,
    cleanup_runtime: bool = True,
) -> int:
    """级联删除一组批次:连带它们参与的对比(作 batch/ref)及对比项、由其晋升的基线、截图。

    返回删除的对比数;调用方随后用 prune_orphans 清磁盘文件。
    任一受影响对比正在后台计算中则抛 409(整批不删)。
    """
    bids = [b.id for b in batches]
    comp_ids = list(db.scalars(
        select(Comparison.id).where(
            or_(Comparison.batch_id.in_(bids), Comparison.ref_batch_id.in_(bids))
        )
    ))
    # 临界区:与"建对比/起任务"互斥;正在计算的对比不允许删
    with _COMPARE_LOCK:
        if any(cid in _RUNNING for cid in comp_ids):
            raise HTTPException(409, "批次正在对比计算中,请稍后再删")
        for cid in comp_ids:                       # 删对比(级联对比项)
            comp = db.get(Comparison, cid)
            if comp is not None:
                db.delete(comp)
        if bids:                                   # 删由其晋升的基线
            db.execute(delete(Baseline).where(Baseline.source_batch_id.in_(bids)))
        for b in batches:                          # 删批次(级联截图)
            db.delete(b)
        if commit:
            db.commit()
        else:
            db.flush()
    if cleanup_runtime:
        # 先使同批次已排队/运行的任务失效。invalidate 与缩略图最终发布共用锁，
        # 因而 rmtree 之后旧任务不会重新写回。
        _cleanup_deleted_batch_runtime(bids, comp_ids)
    return len(comp_ids)


@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str, db: Session = Depends(get_db)):
    """级联删除单个批次(对比/对比项/基线/图片);正在计算的对比拦 409。"""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "batch not found")
    comps = _cascade_delete_batches(db, [batch])
    pruned = prune_orphans(db)
    log.info("删批次 #%s,连带对比 %d 条", batch_id, comps)
    return {
        "deleted": True,
        "batch_id": batch_id,
        "comparisons_removed": comps,
        "files_removed": pruned["dirs"] + pruned["files"],
    }


@app.delete("/api/batches")
def delete_batches_before(created_before: str = Query(...), db: Session = Depends(get_db)):
    """批量删除创建时间早于 created_before(ISO 日期/时间,如 2024-06-01)的全部批次(级联)。

    删除条件为 created_at < created_before:传 2024-06-01 即删 5-31 及更早,不含当天。
    谨慎:不可恢复。
    """
    try:
        cutoff = datetime.fromisoformat(created_before)
    except ValueError:
        raise HTTPException(400, "created_before 需为 ISO 日期,如 2024-06-01")
    batches = list(db.scalars(select(Batch).where(Batch.created_at < cutoff)))
    if not batches:
        return {"deleted_batches": 0, "comparisons_removed": 0, "files_removed": 0}
    comps = _cascade_delete_batches(db, batches)
    pruned = prune_orphans(db)
    log.info("按日期删批次:删 %d 个(早于 %s),连带对比 %d 条", len(batches), created_before, comps)
    return {
        "deleted_batches": len(batches),
        "comparisons_removed": comps,
        "files_removed": pruned["dirs"] + pruned["files"],
    }


# ---------------------------------------------------------------- 对比

class ComparisonIn(BaseModel):
    batch_id: str       # 当前批次
    ref_batch_id: str   # 参照批次
    shading_quality: int | None = None
    force: bool = False  # 已对比过时是否强制重新计算


# 对比后台任务:task_id -> 进度/结果(内存,单进程)
_TASKS: dict = {}
# 并发护栏:串行化"查重/建行/起任务"这段;同一对比同时只跑一个计算任务
_COMPARE_LOCK = threading.Lock()
_RUNNING: dict[int, str] = {}   # comparison_id -> 正在计算它的 task_id

# 完成/失败的任务保留时长;超时后清理,避免 _TASKS 无限增长。
_TASK_TTL_SECONDS = 3600

# 对比历史全局上限;新建对比超过它就淘汰创建时间最早的(环形历史)。
# 对比是「短期可重跑产物」:保留最近 N 天,过期整条删除(记录 + 本地热力图)。
# 需要看更老的对比时,用仍在的批次重跑即可。替代了旧的「最新 100 条」计数上限。
COMPARISON_RETENTION_DAYS = 14


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


def _evict_old_comparisons(db: Session, keep_id: int | None = None) -> list[int]:
    """删除创建时间早于保留期(COMPARISON_RETENTION_DAYS 天)的对比(级联对比项)。

    对比是短期可重跑产物,过期整条删除;本地热力图由调用方 prune_orphans 清理。
    跳过刚建的(keep_id)与正在计算的(_RUNNING);调用方应已持有 _COMPARE_LOCK。
    返回被淘汰的 comparison id 列表(供调用方清理其热力图文件)。
    """
    cutoff = datetime.now() - timedelta(days=COMPARISON_RETENTION_DAYS)
    evicted: list[int] = []
    for c in db.scalars(select(Comparison).where(Comparison.created_at < cutoff)):
        if c.id == keep_id or c.id in _RUNNING:
            continue
        db.delete(c)            # 经 Comparison.items 关系级联删对比项
        evicted.append(c.id)
    if evicted:
        db.commit()
        for tid in [t for t, i in _TASKS.items() if i.get("comparison_id") in evicted]:
            _TASKS.pop(tid, None)
        log.info("对比保留 %d 天,淘汰过期 %s", COMPARISON_RETENTION_DAYS, evicted)
    return evicted


_COMPARE_MAX_ATTEMPTS = 3   # 计算失败(多为共享盘瞬时 IO 抖动)自动重试次数


def _set_task(task_id, **fields):
    """安全更新任务状态(任务可能已被 _prune_tasks 清理,避免 KeyError)。"""
    info = _TASKS.get(task_id)
    if info is not None:
        info.update(fields)


def _run_compare_task(
    task_id, comparison_id, batch_id, ref_id,
    current_run_id, reference_run_id, baseline_id, settings, start_gate=None,
):
    """后台线程:把结果填进已存在的 comparison 行,过程中更新进度。

    计算失败(常见于共享盘瞬时 IO 抖动/读原图/写热力图)自动重试至多
    _COMPARE_MAX_ATTEMPTS 次;重试用尽仍失败,则**删除这条空壳对比**(残留热力图
    随后由 prune_orphans 清),避免留下前端"有对比却没图"的残行。
    """
    # 多画质自动对比会一次登记多条 comparison。先等所有记录提交完成，
    # 避免首个后台任务抢占 SQLite 写锁，令同一 HTTP 请求的后续建行失败。
    if start_gate is not None:
        start_gate.wait()
    db = SessionLocal()

    def on_progress(done, total):
        _set_task(task_id, done=done, total=total)

    ok = False
    last_err = None
    try:
        for attempt in range(1, _COMPARE_MAX_ATTEMPTS + 1):
            try:
                comparison = db.get(Comparison, comparison_id)
                batch = db.get(Batch, batch_id)
                ref = db.get(Batch, ref_id)
                current_run = db.get(QualityRun, current_run_id)
                reference_run = db.get(QualityRun, reference_run_id)
                baseline = db.get(Baseline, baseline_id) if baseline_id else None
                if current_run is None or reference_run is None:
                    raise RuntimeError("对比画质运行已不存在")
                run_comparison(
                    db, comparison, batch, ref, current_run, reference_run,
                    baseline, settings, on_progress=on_progress,
                )
                db.commit()
                ok = True
                _set_task(task_id, status="done", comparison_id=comparison_id, finished_at=time.monotonic())
                log.info("对比 #%s 完成,整体差异 %.2f%%", comparison_id, comparison.diff_avg)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                db.rollback()   # 撤掉本次已写入的部分对比项,下次重试从头算(幂等覆盖)
                if attempt < _COMPARE_MAX_ATTEMPTS:
                    log.warning("对比 #%s 第 %d 次计算失败,%.1fs 后重试: %s",
                                comparison_id, attempt, 0.5 * attempt, e)
                    time.sleep(0.5 * attempt)

        if not ok:
            # 重试用尽:删掉空壳对比行,别留"有对比没图"的残行
            log.warning("对比 #%s 重试 %d 次仍失败,删除空壳对比: %s",
                        comparison_id, _COMPARE_MAX_ATTEMPTS, last_err)
            try:
                c = db.get(Comparison, comparison_id)
                if c is not None:
                    db.delete(c)   # 级联删对比项
                    db.commit()
            except Exception as e2:  # noqa: BLE001
                db.rollback()
                log.warning("删除空壳对比 #%s 失败: %s", comparison_id, e2)
            _set_task(task_id, status="error", error=str(last_err), finished_at=time.monotonic())
            for tid in [t for t, i in _TASKS.items() if i.get("comparison_id") == comparison_id and t != task_id]:
                _TASKS.pop(tid, None)
    finally:
        # 离开 _RUNNING;成功则 keep_id=自己(不淘汰刚算完、最可能正被查看的这条),
        # 失败已删则无需保护;再补一次过期淘汰,并清理孤儿热力图(含刚删空壳的残留)。
        evicted: list[int] = []
        with _COMPARE_LOCK:
            _RUNNING.pop(comparison_id, None)
            try:
                evicted = _evict_old_comparisons(db, keep_id=comparison_id if ok else None)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                log.warning("完成后淘汰对比失败(忽略): %s", e)
        if evicted or not ok:   # 失败删了空壳,或淘汰了旧对比 → 清理孤儿热力图文件
            try:
                prune_orphans(db)
            except Exception:  # noqa: BLE001
                pass
        db.close()


def _create_comparison(
    body: ComparisonIn,
    db: Session,
    start_gate: threading.Event | None = None,
):
    """发起对比:已对比过直接复用(立即返回);否则起后台任务,前端轮询进度。

    同一对批次(batch × ref)至多一条对比记录,重算复用同一行(id 不变,
    不会把正在查看该结果的其他人弄成 404);并发触发同一对比只跑一次。
    """
    batch = db.get(Batch, body.batch_id)
    ref = db.get(Batch, body.ref_batch_id)
    if not batch or not ref:
        raise HTTPException(404, "batch not found")
    if batch.id == ref.id:
        raise ApiError(400, "SELF_COMPARISON", "不能与自身对比")
    if batch.branch_tag != ref.branch_tag:
        raise ApiError(400, "CROSS_BRANCH_COMPARISON", "两个批次的分支不同,无法对比")
    if batch.scene_id != ref.scene_id:
        raise ApiError(400, "CROSS_SCENE_COMPARISON", "两个批次的场景ID不同,无法对比")
    if batch.platform != ref.platform:
        raise ApiError(400, "CROSS_PLATFORM_COMPARISON", "两个批次的平台不同,无法对比")

    current_run, current_count = resolve_quality_run(db, batch.id, body.shading_quality)
    reference_run, reference_count = resolve_quality_run(db, ref.id, body.shading_quality)
    if current_run is None or reference_run is None:
        if body.shading_quality is None:
            raise ApiError(
                422, "SHADING_QUALITY_REQUIRED",
                "多画质批次对比必须指定 shading_quality",
            )
        raise ApiError(
            409, "QUALITY_RUN_INCOMPLETE",
            f"画质 {body.shading_quality} 不存在或未完整上传 "
            f"(current={current_count}, reference={reference_count})",
        )
    if not is_run_available(current_run, current_count) or not is_run_available(
        reference_run, reference_count
    ):
        if body.shading_quality is None:
            raise ApiError(
                400, "QUALITY_RUN_INCOMPLETE",
                "两个批次都必须包含完整截图才能对比",
            )
        raise ApiError(409, "QUALITY_RUN_INCOMPLETE", "指定画质运行尚未完整上传")
    if current_run.shading_quality != reference_run.shading_quality:
        raise ApiError(400, "CROSS_QUALITY_COMPARISON", "禁止跨画质对比")

    baseline = db.scalar(
        select(Baseline).where(
            Baseline.source_quality_run_id == reference_run.id,
            Baseline.status == "active",
        )
    )

    # 临界区:查重 / 建行 / 起任务,避免并发产生重复对比或重复计算
    evicted: list[int] = []
    with _COMPARE_LOCK:
        # 无方向查重:同一对批次正反向只存一行;反向请求命中后由前端翻转展示
        existing = db.scalars(
            select(Comparison)
            .where(or_(
                and_(
                    Comparison.current_quality_run_id == current_run.id,
                    Comparison.reference_quality_run_id == reference_run.id,
                ),
                and_(
                    Comparison.current_quality_run_id == reference_run.id,
                    Comparison.reference_quality_run_id == current_run.id,
                ),
            ))
            .order_by(Comparison.created_at.desc())
        ).first()
        # flip:库内方向与本次请求相反(请求的 batch 实际是库里的参照)
        flip = bool(existing) and existing.current_quality_run_id != current_run.id

        if existing:
            # 空行会在后台任务真正完成前就存在。必须先识别运行任务，再判断
            # 是否已有可复用结果，否则刷新或重复点击会把空行误报为 done。
            running_task_id = _RUNNING.get(existing.id)
            if running_task_id:
                task = _TASKS.get(running_task_id, {})
                return {
                    "task_id": running_task_id,
                    "status": task.get("status", "running"),
                    "done": task.get("done", 0),
                    "total": task.get("total", 0),
                    "flip": flip,
                }
            item_count = db.scalar(
                select(func.count(ComparisonItem.id)).where(
                    ComparisonItem.comparison_id == existing.id
                )
            ) or 0
            if item_count > 0 and not body.force:
                return {
                    "status": "done",
                    "comparison": comparison_dto(existing, db),
                    "flip": flip,
                }

        if existing is None:
            # 先建空行拿到稳定 id(按请求方向为规范方向)
            comparison = Comparison(
                batch_id=batch.id, ref_batch_id=ref.id,
                current_quality_run_id=current_run.id,
                reference_quality_run_id=reference_run.id,
                scope_status="valid",
                baseline_id=baseline.id if baseline else None,
            )
            db.add(comparison)
            db.commit()
            # 顺带淘汰过期对比(超保留期),返回的 id 供下面清热力图
            evicted = _evict_old_comparisons(db, keep_id=comparison.id)
            comp_batch_id, comp_ref_id, comp_baseline = batch.id, ref.id, baseline
            comp_current_run_id, comp_reference_run_id = current_run.id, reference_run.id
        else:
            # force 重算:复用该行,按其库内方向重算(基线取库内参照的 active 基线)
            comparison = existing
            comp_batch_id, comp_ref_id = existing.batch_id, existing.ref_batch_id
            comp_current_run_id = existing.current_quality_run_id
            comp_reference_run_id = existing.reference_quality_run_id
            comp_baseline = db.scalar(
                select(Baseline).where(
                    Baseline.source_quality_run_id == comp_reference_run_id,
                    Baseline.status == "active",
                )
            )
        cid = comparison.id

        _prune_tasks()
        task_id = uuid.uuid4().hex
        _TASKS[task_id] = {"status": "running", "done": 0, "total": 0, "comparison_id": cid, "error": None}
        _RUNNING[cid] = task_id
        log.info("发起对比 #%s: #%s vs #%s%s", cid, comp_batch_id, comp_ref_id, "(强制重算)" if body.force else "")
        submitted = comparison_executor.submit(
            _run_compare_task,
            task_id, cid, comp_batch_id, comp_ref_id,
            comp_current_run_id, comp_reference_run_id,
            comp_baseline.id if comp_baseline else None, get_settings(db), start_gate,
        )
        if not submitted:
            _RUNNING.pop(cid, None)
            _TASKS.pop(task_id, None)
            if existing is None:
                db.delete(comparison)
                db.commit()
            raise HTTPException(503, "对比任务队列已满，请稍后重试")
    # 锁外清理被淘汰对比的热力图目录(已无 DB 记录,成孤儿)
    if evicted:
        prune_orphans(db)
    return {"task_id": task_id, "status": "running", "done": 0, "total": 0, "flip": flip}


@app.post("/api/comparisons", status_code=202)
def create_comparison(body: ComparisonIn, db: Session = Depends(get_db)):
    """发起单个画质对比；后台任务会立即开始。"""
    return _create_comparison(body, db)


@app.get("/api/comparisons/lookup")
def lookup_comparison(
    batch_id: str,
    ref_batch_id: str,
    shading_quality: int | None = None,
    db: Session = Depends(get_db),
):
    """只读:给定一对批次(忽略方向)返回已存在的对比及各检查点热力图;
    不存在则 exists=false,绝不触发计算。供列表图热力图列命中缓存直接展示。"""
    current_run, _ = resolve_quality_run(
        db, batch_id, shading_quality, require_available=True
    )
    reference_run, _ = resolve_quality_run(
        db, ref_batch_id, shading_quality, require_available=True
    )
    if current_run is None or reference_run is None:
        if shading_quality is None:
            raise ApiError(
                422, "SHADING_QUALITY_REQUIRED",
                "多画质批次查询对比必须指定 shading_quality",
            )
        return {
            "exists": False, "status": "missing", "ready": False,
            "task_id": None, "done": 0, "total": 0,
        }
    existing = db.scalars(
        select(Comparison).where(or_(
            and_(
                Comparison.current_quality_run_id == current_run.id,
                Comparison.reference_quality_run_id == reference_run.id,
            ),
            and_(
                Comparison.current_quality_run_id == reference_run.id,
                Comparison.reference_quality_run_id == current_run.id,
            ),
        )).order_by(Comparison.created_at.desc())
    ).first()
    if not existing:
        return {
            "exists": False,
            "status": "missing",
            "ready": False,
            "task_id": None,
            "done": 0,
            "total": 0,
        }
    items = db.scalars(
        select(ComparisonItem).where(ComparisonItem.comparison_id == existing.id)
    ).all()
    heatmaps = {it.scene_name: _heatmap_url(it)
                for it in items if it.heatmap_path}
    running_task_id = _RUNNING.get(existing.id)
    if running_task_id:
        task = _TASKS.get(running_task_id, {})
        return {
            "exists": True,
            "status": "running",
            "ready": False,
            "task_id": running_task_id,
            "done": task.get("done", 0),
            "total": task.get("total", 0),
            "comparison": comparison_dto(existing, db),
            "heatmaps": heatmaps,
        }
    if not items:
        # 服务异常退出可能留下没有任何对比项的空壳行。对调用方表现为
        # 可重新发起的 missing，create_comparison 会复用同一行重新计算。
        return {
            "exists": False,
            "status": "missing",
            "ready": False,
            "task_id": None,
            "done": 0,
            "total": 0,
        }
    total = len(items)
    return {
        "exists": True,
        "status": "done",
        "ready": True,
        "task_id": None,
        "done": total,
        "total": total,
        "comparison": comparison_dto(existing, db),
        "heatmaps": heatmaps,
    }


@app.post("/api/batches/{batch_id}/auto-compare", status_code=202)
def auto_compare_batch(batch_id: str, db: Session = Depends(get_db)):
    """为批次中的每个完整画质分别选择同画质历史参照并发起对比。"""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "batch not found")
    runs = db.scalars(
        select(QualityRun)
        .where(QualityRun.batch_id == batch.id)
        .order_by(QualityRun.shading_quality.desc())
    ).all()
    counts = ready_counts(db, [run.id for run in runs])
    runs = [run for run in runs if is_run_available(run, counts.get(run.id, 0))]
    if not runs:
        raise HTTPException(400, "当前批次没有截图,无法自动对比")

    results = []
    start_gate = threading.Event()
    try:
        for run in runs:
            base = select(Batch).where(
                Batch.id != batch.id,
                Batch.branch_tag == batch.branch_tag,
                Batch.scene_id == batch.scene_id,
                Batch.platform == batch.platform,
                Batch.quality_runs.any(QualityRun.shading_quality == run.shading_quality),
            )
            if batch.p4_version is not None:
                candidates = db.scalars(
                    base.where(or_(
                        and_(Batch.p4_version.is_not(None), Batch.p4_version < batch.p4_version),
                        and_(Batch.p4_version == batch.p4_version,
                             Batch.created_at < batch.created_at),
                    )).order_by(Batch.p4_version.desc(), Batch.created_at.desc())
                ).all()
            else:
                candidates = db.scalars(
                    base.where(Batch.created_at < batch.created_at)
                    .order_by(Batch.created_at.desc())
                ).all()
            ref = next((candidate for candidate in candidates if resolve_quality_run(
                db, candidate.id, run.shading_quality, require_available=True
            )[0] is not None), None)
            if ref is None:
                results.append({"matched": False, "shading_quality": run.shading_quality})
                continue
            try:
                result = _create_comparison(ComparisonIn(
                    batch_id=batch.id,
                    ref_batch_id=ref.id,
                    shading_quality=run.shading_quality,
                ), db, start_gate)
            except HTTPException as error:
                if error.status_code != 503:
                    raise
                # 各画质自动对比彼此独立。队列容量不足时必须把该档失败
                # 明确写进 202 响应，不能令客户端收到整次失败、同时已登记
                # 的其他档位却在后台继续执行。
                log.warning(
                    "自动对比队列已满 batch=%s quality=%s",
                    batch.id, run.shading_quality,
                )
                results.append({
                    "matched": False,
                    "shading_quality": run.shading_quality,
                    "error": "queue_full",
                })
                continue
            results.append({
                "matched": True,
                "shading_quality": run.shading_quality,
                "ref_batch_id": ref.id,
                **result,
            })
    finally:
        # 成功、异常或队列满都必须放行已经登记的任务，避免工作线程永久等待。
        start_gate.set()
    if len(results) == 1:
        return results[0]
    return {"matched": any(item["matched"] for item in results), "results": results}


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
    branch_tag: str = "main",
    scene_id: str | None = None,
    platform: str | None = None,
    baseline: str | None = None,
    status: str | None = None,
    q: str | None = None,
):
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    stmt = (
        select(Comparison)
        .join(Batch, Comparison.batch_id == Batch.id)
        .order_by(Comparison.created_at.desc())
        .where(Batch.branch_tag == branch_tag)
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
def list_baselines(
    branch_tag: str = "main",
    db: Session = Depends(get_db),
):
    try:
        branch_tag = normalize_branch_tag(branch_tag)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    baselines = db.scalars(
        select(Baseline)
        .where(Baseline.branch_tag == branch_tag)
        .order_by(Baseline.created_at.desc())
    ).all()
    return {
        "items": [
            {
                "id": b.id,
                "version": b.version,
                "branch_tag": b.branch_tag,
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


# ---------------------------------------------------------------- 前端日志上报

_LEVELS = {"info": 20, "warn": 30, "warning": 30, "error": 40, "debug": 10}


class ClientLogEntry(BaseModel):
    level: str = "info"
    msg: str = ""
    ts: str | None = None


class ClientLogsIn(BaseModel):
    logs: list[ClientLogEntry] = []


@app.post("/api/client-logs", status_code=204)
def client_logs(body: ClientLogsIn):
    """前端把日志上报到此,写入 data/logs/frontend.log;尽量宽松,不影响前端。"""
    for e in body.logs:
        try:
            client_log.log(_LEVELS.get((e.level or "info").lower(), 20), "%s", e.msg)
        except Exception:  # noqa: BLE001
            pass
    return None


class SettingsIn(BaseModel):
    pixel_diff_threshold: int | None = None
    fail_threshold: float | None = None
    warn_threshold: float | None = None
    heatmap_blur: int | None = None
    heatmap_sensitivity: float | None = None
    heatmap_method: str | None = None
    heatmap_norm_scale: float | None = None
    heatmap_gamma: float | None = None
    heatmap_density_radius: float | None = None
    heatmap_density_floor: float | None = None
    default_shading_quality: int | None = None
    default_date_range_days: int | None = None
    filter_shading_qualities: list[int] | None = None
    show_unlisted_scene_ids: bool | None = None


class SceneCatalogIn(BaseModel):
    """外部模块全量下发的权威场景目录；顺序即筛选框顺序。"""

    scene_id_order: list[str]

    @field_validator("scene_id_order")
    @classmethod
    def validate_scene_ids(cls, value: list[str]) -> list[str]:
        if len(value) > 5000:
            raise ValueError("场景ID数量不能超过5000")
        seen: set[str] = set()
        for scene_id in value:
            if not scene_id or scene_id != scene_id.strip():
                raise ValueError("场景ID不能为空或包含首尾空格")
            if len(scene_id) > 255:
                raise ValueError("场景ID长度不能超过255")
            if scene_id in seen:
                raise ValueError(f"场景ID重复: {scene_id}")
            seen.add(scene_id)
        return value


@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@app.put("/api/settings")
def update_settings(body: SettingsIn, db: Session = Depends(get_db)):
    return save_settings(db, body.model_dump(exclude_none=True))


@app.get("/api/scene-catalog")
def read_scene_catalog(db: Session = Depends(get_db)):
    settings = get_settings(db)
    order = settings["scene_id_order"]
    return {
        "configured": order is not None,
        "scene_id_order": order,
    }


@app.put("/api/scene-catalog")
def update_scene_catalog(body: SceneCatalogIn, db: Session = Depends(get_db)):
    settings = save_settings(db, {"scene_id_order": body.scene_id_order})
    log.info("场景目录已更新:场景数=%d", len(body.scene_id_order))
    return {
        "configured": True,
        "scene_id_order": settings["scene_id_order"],
    }


@app.get("/api/meta")
def get_meta(db: Session = Depends(get_db)):
    """筛选器选项。"""
    settings = get_settings(db)
    discovered = sorted(
        set(db.scalars(select(Batch.scene_id).distinct()).all()),
        key=lambda scene_id: (scene_id.casefold(), scene_id),
    )
    configured = settings["scene_id_order"]
    if configured is None:
        scene_ids = discovered
        unlisted: list[str] = []
    else:
        configured_set = set(configured)
        unlisted = [scene_id for scene_id in discovered if scene_id not in configured_set]
        scene_ids = list(configured)
        if settings["show_unlisted_scene_ids"]:
            scene_ids.extend(unlisted)
    discovered_branches = set(
        db.scalars(select(Batch.branch_tag).distinct()).all()
    )
    discovered_branches.discard("main")
    branch_tags = ["main", *sorted(discovered_branches)]
    # 下拉菜单需要区分“目录中存在”与“当前分支确实有对应数据”。这里按
    # 分支 + 场景一次聚合，避免前端为每个场景分别请求；目录中但未入库的
    # 场景不会出现在映射中，前端按 false 处理。
    scene_data_flags: dict[str, dict[str, dict[str, bool]]] = {
        branch_tag: {} for branch_tag in branch_tags
    }
    for branch_tag, scene_id in db.execute(
        select(Batch.branch_tag, Batch.scene_id).distinct()
    ):
        scene_data_flags[branch_tag][scene_id] = {
            "has_screenshots": False,
            "has_map_build_data": False,
            "screenshot_qualities": [],
        }
    all_runs = db.scalars(select(QualityRun)).all()
    # 这里需要所有运行的计数；直接聚合，不能把所有 ID 展开为 SQLite IN 参数。
    all_counts = ready_counts(db)
    batches_by_id = {
        batch.id: batch for batch in db.scalars(select(Batch)).all()
    }
    for run in all_runs:
        if not is_run_available(run, all_counts.get(run.id, 0)):
            continue
        batch = batches_by_id.get(run.batch_id)
        if batch is None:
            continue
        flags = scene_data_flags[batch.branch_tag][batch.scene_id]
        flags["has_screenshots"] = True
        flags["screenshot_qualities"].append(run.shading_quality)
    for branch_flags in scene_data_flags.values():
        for flags in branch_flags.values():
            flags["screenshot_qualities"] = sorted(
                set(flags["screenshot_qualities"]), reverse=True
            )
    for branch_tag, scene_id in db.execute(
        select(Batch.branch_tag, Batch.scene_id)
        .join(MapBuildSnapshot, MapBuildSnapshot.batch_id == Batch.id)
        .distinct()
    ):
        scene_data_flags[branch_tag][scene_id]["has_map_build_data"] = True
    return {
        "branch_tags": branch_tags,
        "scene_ids": scene_ids,
        "scene_data_flags": scene_data_flags,
        "unlisted_scene_ids": unlisted,
        "scene_catalog_configured": configured is not None,
        "show_unlisted_scene_ids": settings["show_unlisted_scene_ids"],
        "platforms": db.scalars(select(Batch.platform).distinct()).all(),
        "baselines": db.scalars(select(Baseline.version).distinct()).all(),
    }


# ---------------------------------------------------------------- 生产:托管前端构建产物
# 单端口同源部署:FastAPI 直接伺服 vite build 出的静态页面。
# /api、/images 与 FastAPI 的 /docs、/openapi.json 都在此兜底路由之前注册,优先匹配;
# 其余路径:命中静态文件则返回；未知 API 返回 JSON 404，页面路径才回退
# index.html（支持前端 history 路由深链）。
# 仅当存在 frontend/dist 时启用;开发模式(vite dev)下不存在,跳过即可。
from pathlib import Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    _DIST = _FRONTEND_DIST.resolve()

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise ApiError(404, "API_NOT_FOUND", "API 接口不存在")
        target = (_DIST / full_path).resolve()
        # 命中真实静态文件才返回(并防目录遍历);否则一律回 index.html
        if full_path and target.is_file() and _DIST in target.parents:
            return FileResponse(target)
        return FileResponse(_DIST / "index.html")
