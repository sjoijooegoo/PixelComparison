"""场景烘培数据的校验、存储与查询模块。

外部接口只暴露一次快照写入、元数据、当前概览和趋势查询；原始 registry
树的兼容处理与规范化索引全部收在本模块内，调用方不需要理解 UE 数据结构。
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Integer, cast, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .models import Batch, MapBuildRegistry, MapBuildSnapshot

FORMAT_VERSION = "map-build-data/v2"
MAX_REGISTRIES = 5000
MAX_TREND_POINTS = 2000
MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807
LEGACY_DEFAULT_SHADING_QUALITY = 4
QUALITY_LABELS = {5: "电影", 4: "极致", 3: "精美", 2: "均衡", 1: "流畅", 0: "节能"}

_WRITE_LOCK = threading.Lock()
_DETAIL_METRIC_KEYS = (
    "lightmap_all_mips_bytes",
    "hue_all_mips_bytes",
    "shadowmap_all_mips_bytes",
    "mesh_map_build_data_bytes",
    "precomputed_light_volume_bytes",
    "precomputed_reflection_volume_bytes",
    "volumetric_lightmap_bytes",
    "light_build_data_bytes",
    "reflection_capture_bytes",
    "precomputed_instanced_ilc_bytes",
    "precomputed_instanced_pr_bytes",
    "lightmap_resource_cluster_bytes",
)
_METRIC_KEYS = (
    "total_bytes",
    "lightmap_bytes",
    "hue_bytes",
    "shadowmap_bytes",
    "all_mips_bytes",
    "cook_estimate_bytes",
    "texture_count",
    *_DETAIL_METRIC_KEYS,
)


class _OpenModel(BaseModel):
    """接受未来版本追加字段，同时严格校验当前查询依赖的字段。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TextureMetricsIn(_OpenModel):
    resident_bytes: int = Field(alias="residentBytes", ge=0, le=MAX_SQLITE_INTEGER)
    all_mips_bytes: int = Field(alias="allMipsBytes", ge=0, le=MAX_SQLITE_INTEGER)
    cook_estimate_bytes: int = Field(alias="cookEstimateBytes", ge=0, le=MAX_SQLITE_INTEGER)


class RegistryBreakdownIn(_OpenModel):
    lightmap_textures: TextureMetricsIn = Field(alias="lightmapTextures")
    hue_textures: TextureMetricsIn = Field(alias="hueTextures")
    shadowmap_textures: TextureMetricsIn = Field(alias="shadowmapTextures")
    mesh_map_build_data_bytes: int = Field(
        default=0, alias="meshMapBuildDataBytes", ge=0, le=MAX_SQLITE_INTEGER
    )
    precomputed_light_volume_bytes: int = Field(
        default=0, alias="precomputedLightVolumeBytes", ge=0, le=MAX_SQLITE_INTEGER
    )
    precomputed_reflection_volume_bytes: int = Field(
        default=0,
        alias="precomputedReflectionVolumeBytes",
        ge=0,
        le=MAX_SQLITE_INTEGER,
    )
    volumetric_lightmap_bytes: int = Field(
        default=0, alias="volumetricLightmapBytes", ge=0, le=MAX_SQLITE_INTEGER
    )
    light_build_data_bytes: int = Field(
        default=0, alias="lightBuildDataBytes", ge=0, le=MAX_SQLITE_INTEGER
    )
    reflection_capture_bytes: int = Field(
        default=0, alias="reflectionCaptureBytes", ge=0, le=MAX_SQLITE_INTEGER
    )
    precomputed_instanced_ilc_bytes: int = Field(
        default=0,
        alias="precomputedInstancedILCBytes",
        ge=0,
        le=MAX_SQLITE_INTEGER,
    )
    precomputed_instanced_pr_bytes: int = Field(
        default=0,
        alias="precomputedInstancedPRBytes",
        ge=0,
        le=MAX_SQLITE_INTEGER,
    )
    lightmap_resource_cluster_bytes: int = Field(
        default=0,
        alias="lightmapResourceClusterBytes",
        ge=0,
        le=MAX_SQLITE_INTEGER,
    )


class AggregateMetricsIn(_OpenModel):
    resident_bytes: int = Field(alias="residentBytes", ge=0, le=MAX_SQLITE_INTEGER)
    all_mips_bytes: int = Field(alias="allMipsBytes", ge=0, le=MAX_SQLITE_INTEGER)
    cook_estimate_bytes: int = Field(alias="cookEstimateBytes", ge=0, le=MAX_SQLITE_INTEGER)
    texture_count: int = Field(alias="textureCount", ge=0, le=2_147_483_647)


class RegistrySelfIn(AggregateMetricsIn):
    breakdown: RegistryBreakdownIn


class RegistryIn(_OpenModel):
    path: str = Field(min_length=1, max_length=4096)
    parent_path: str | None = Field(default=None, alias="parentPath", max_length=4096)
    block_index: int | None = Field(default=None, alias="blockIndex", ge=0, le=65535)
    sub_block_index: int | None = Field(
        default=None, alias="subBlockIndex", ge=0, le=65535
    )
    self_metrics: RegistrySelfIn = Field(alias="self")
    subtree_aggregate: AggregateMetricsIn = Field(alias="subtreeAggregate")


class MapBuildDataIn(_OpenModel):
    world_aggregate: AggregateMetricsIn = Field(alias="worldAggregate")
    registries: list[RegistryIn]

    @model_validator(mode="after")
    def validate_registry_topology(self):
        if not self.registries:
            raise ValueError("registries 不能为空")
        if len(self.registries) > MAX_REGISTRIES:
            raise ValueError(f"registries 不能超过 {MAX_REGISTRIES} 条")

        paths: set[str] = set()
        cells: set[tuple[int, int | None]] = set()
        for registry in self.registries:
            if registry.path in paths:
                raise ValueError(f"registry path 重复: {registry.path}")
            paths.add(registry.path)
            if registry.sub_block_index is not None and registry.block_index is None:
                raise ValueError("subBlockIndex 存在时必须同时提供 blockIndex")
            if registry.block_index is not None:
                cell = (registry.block_index, registry.sub_block_index)
                if cell in cells:
                    raise ValueError(
                        "blockIndex/subBlockIndex 重复: "
                        f"{registry.block_index}/{registry.sub_block_index}"
                    )
                cells.add(cell)
        return self


def _registry_row(batch_id: str, item: RegistryIn) -> MapBuildRegistry:
    own = item.self_metrics
    subtree = item.subtree_aggregate
    breakdown = own.breakdown
    return MapBuildRegistry(
        batch_id=batch_id,
        path=item.path,
        parent_path=item.parent_path,
        block_index=item.block_index,
        sub_block_index=item.sub_block_index,
        resident_bytes=own.resident_bytes,
        all_mips_bytes=own.all_mips_bytes,
        cook_estimate_bytes=own.cook_estimate_bytes,
        texture_count=own.texture_count,
        subtree_resident_bytes=subtree.resident_bytes,
        subtree_all_mips_bytes=subtree.all_mips_bytes,
        subtree_cook_estimate_bytes=subtree.cook_estimate_bytes,
        subtree_texture_count=subtree.texture_count,
        lightmap_bytes=breakdown.lightmap_textures.resident_bytes,
        hue_bytes=breakdown.hue_textures.resident_bytes,
        shadowmap_bytes=breakdown.shadowmap_textures.resident_bytes,
        **_detail_metrics(breakdown),
    )


def store_snapshot(
    db: Session,
    batch: Batch,
    payload: MapBuildDataIn,
    format_version: str = FORMAT_VERSION,
) -> dict:
    """幂等替换一个批次的完整烘培快照，所有规范化行在同一事务提交。"""

    world = payload.world_aggregate
    with _WRITE_LOCK:
        snapshot = db.get(MapBuildSnapshot, batch.id)
        updated = snapshot is not None
        if snapshot is None:
            snapshot = MapBuildSnapshot(batch_id=batch.id)
            db.add(snapshot)

        snapshot.format_version = format_version
        snapshot.world_resident_bytes = world.resident_bytes
        snapshot.world_all_mips_bytes = world.all_mips_bytes
        snapshot.world_cook_estimate_bytes = world.cook_estimate_bytes
        snapshot.world_texture_count = world.texture_count
        snapshot.raw_payload = payload.model_dump(by_alias=True)
        snapshot.uploaded_at = datetime.now()
        # 先显式删除并 flush，再插入相同 path 的新行。只做 relationship 替换时，
        # SQLAlchemy 可能先 INSERT 后 DELETE，从而撞上 (batch_id, path) 唯一约束。
        if updated:
            db.execute(
                delete(MapBuildRegistry).where(MapBuildRegistry.batch_id == batch.id)
            )
            db.flush()
        db.add_all([_registry_row(batch.id, item) for item in payload.registries])
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "batch_id": batch.id,
        "scene_id": batch.scene_id,
        "format": format_version,
        "registry_count": len(payload.registries),
        "updated": updated,
    }


def _quality_value(batch: Batch) -> int:
    return (
        batch.shading_quality
        if batch.shading_quality is not None
        else LEGACY_DEFAULT_SHADING_QUALITY
    )


def _batch_dto(snapshot: MapBuildSnapshot) -> dict:
    batch = snapshot.batch
    quality = _quality_value(batch)
    return {
        "id": batch.id,
        "scene_id": batch.scene_id,
        "p4_version": batch.p4_version,
        "platform": batch.platform,
        "shading_quality": quality,
        "shading_quality_label": QUALITY_LABELS.get(quality, str(quality)),
        "created_at": batch.created_at.isoformat(timespec="minutes"),
    }


def list_meta(
    db: Session,
    *,
    scene_id_order: list[str] | None = None,
    show_unlisted_scene_ids: bool = False,
) -> dict:
    """仅返回确实拥有烘培快照的筛选项，不把无数据场景混入页面。"""

    rows = db.execute(
        select(
            Batch.scene_id,
            Batch.platform,
            Batch.shading_quality,
            func.count(MapBuildSnapshot.batch_id),
            func.max(Batch.created_at),
        )
        .join(MapBuildSnapshot, MapBuildSnapshot.batch_id == Batch.id)
        .group_by(Batch.scene_id, Batch.platform, Batch.shading_quality)
        .order_by(Batch.scene_id, Batch.platform)
    ).all()
    scenes: dict[str, dict] = {}
    for scene_id, platform, quality_value, count, latest in rows:
        quality = (
            quality_value
            if quality_value is not None
            else LEGACY_DEFAULT_SHADING_QUALITY
        )
        scene = scenes.setdefault(
            scene_id,
            {
                "value": scene_id,
                "batch_count": 0,
                "latest_at": latest,
                "platforms": set(),
                "qualities": set(),
            },
        )
        scene["batch_count"] += count
        scene["latest_at"] = max(scene["latest_at"], latest)
        scene["platforms"].add(platform)
        scene["qualities"].add(quality)
    platforms = list(
        db.scalars(
            select(Batch.platform)
            .join(MapBuildSnapshot, MapBuildSnapshot.batch_id == Batch.id)
            .distinct()
            .order_by(Batch.platform)
        )
    )
    qualities = sorted(
        {
            value if value is not None else LEGACY_DEFAULT_SHADING_QUALITY
            for value in db.scalars(
                select(Batch.shading_quality)
                .join(MapBuildSnapshot, MapBuildSnapshot.batch_id == Batch.id)
                .distinct()
            )
        },
        reverse=True,
    )
    scene_items = [
        {
            "value": scene["value"],
            "batch_count": scene["batch_count"],
            "latest_at": scene["latest_at"].isoformat(timespec="minutes"),
            "platforms": sorted(scene["platforms"]),
            "shading_qualities": [
                {
                    "value": value,
                    "label": QUALITY_LABELS.get(value, str(value)),
                }
                for value in sorted(scene["qualities"], reverse=True)
            ],
        }
        for scene in scenes.values()
    ]
    if scene_id_order is not None:
        by_id = {item["value"]: item for item in scene_items}
        configured = [by_id[scene_id] for scene_id in scene_id_order if scene_id in by_id]
        if show_unlisted_scene_ids:
            configured_set = set(scene_id_order)
            configured.extend(
                item for item in scene_items if item["value"] not in configured_set
            )
        scene_items = configured
    return {
        "scene_ids": scene_items,
        "platforms": platforms,
        "shading_qualities": [
            {"value": value, "label": QUALITY_LABELS.get(value, str(value))}
            for value in qualities
        ],
    }


def _base_snapshot_query(
    scene_id: str,
    platform: str | None,
    shading_quality: int | None,
):
    stmt = (
        select(MapBuildSnapshot)
        .join(Batch, MapBuildSnapshot.batch_id == Batch.id)
        .options(selectinload(MapBuildSnapshot.batch))
        .where(Batch.scene_id == scene_id)
    )
    if platform:
        stmt = stmt.where(Batch.platform == platform)
    if shading_quality is not None:
        if shading_quality == LEGACY_DEFAULT_SHADING_QUALITY:
            stmt = stmt.where(
                or_(
                    Batch.shading_quality == shading_quality,
                    Batch.shading_quality.is_(None),
                )
            )
        else:
            stmt = stmt.where(Batch.shading_quality == shading_quality)
    return stmt


def _snapshot_order(stmt):
    return stmt.order_by(
        Batch.created_at.desc(), cast(Batch.id, Integer).desc(), Batch.id.desc()
    )


def _empty_metrics() -> dict[str, int]:
    return {key: 0 for key in _METRIC_KEYS}


def _detail_metrics(breakdown: RegistryBreakdownIn) -> dict[str, int]:
    """把当前概览需要的完整 breakdown 收敛为稳定的扁平响应。"""

    return {
        "lightmap_all_mips_bytes": breakdown.lightmap_textures.all_mips_bytes,
        "hue_all_mips_bytes": breakdown.hue_textures.all_mips_bytes,
        "shadowmap_all_mips_bytes": breakdown.shadowmap_textures.all_mips_bytes,
        "mesh_map_build_data_bytes": breakdown.mesh_map_build_data_bytes,
        "precomputed_light_volume_bytes": breakdown.precomputed_light_volume_bytes,
        "precomputed_reflection_volume_bytes": (
            breakdown.precomputed_reflection_volume_bytes
        ),
        "volumetric_lightmap_bytes": breakdown.volumetric_lightmap_bytes,
        "light_build_data_bytes": breakdown.light_build_data_bytes,
        "reflection_capture_bytes": breakdown.reflection_capture_bytes,
        "precomputed_instanced_ilc_bytes": (
            breakdown.precomputed_instanced_ilc_bytes
        ),
        "precomputed_instanced_pr_bytes": breakdown.precomputed_instanced_pr_bytes,
        "lightmap_resource_cluster_bytes": (
            breakdown.lightmap_resource_cluster_bytes
        ),
    }


def _row_metrics(row: MapBuildRegistry) -> dict[str, int]:
    metrics = {
        "total_bytes": row.resident_bytes,
        "lightmap_bytes": row.lightmap_bytes,
        "hue_bytes": row.hue_bytes,
        "shadowmap_bytes": row.shadowmap_bytes,
        "all_mips_bytes": row.all_mips_bytes,
        "cook_estimate_bytes": row.cook_estimate_bytes,
        "texture_count": row.texture_count,
    }
    metrics.update(
        {key: int(getattr(row, key, 0) or 0) for key in _DETAIL_METRIC_KEYS}
    )
    return metrics


def _sum_breakdown(rows: list[MapBuildRegistry]) -> dict[str, int]:
    result = _empty_metrics()
    for row in rows:
        metrics = _row_metrics(row)
        for key in _METRIC_KEYS:
            result[key] += metrics[key]
    return result


def _aggregate_metrics(
    rows: list[MapBuildRegistry],
    header: MapBuildRegistry | None = None,
) -> dict[str, int]:
    metrics = _sum_breakdown(rows)
    if header is not None:
        metrics.update(
            total_bytes=header.subtree_resident_bytes,
            all_mips_bytes=header.subtree_all_mips_bytes,
            cook_estimate_bytes=header.subtree_cook_estimate_bytes,
            texture_count=header.subtree_texture_count,
        )
    return metrics


def _world_metrics(
    snapshot: MapBuildSnapshot,
    rows: list[MapBuildRegistry],
) -> dict[str, int]:
    metrics = _sum_breakdown(rows)
    metrics.update(
        total_bytes=snapshot.world_resident_bytes,
        all_mips_bytes=snapshot.world_all_mips_bytes,
        cook_estimate_bytes=snapshot.world_cook_estimate_bytes,
        texture_count=snapshot.world_texture_count,
    )
    return metrics


def _rows_by_batch(
    db: Session,
    batch_ids: list[str],
) -> dict[str, list[MapBuildRegistry]]:
    grouped = {batch_id: [] for batch_id in batch_ids}
    if not batch_ids:
        return grouped
    for row in db.scalars(
        select(MapBuildRegistry).where(MapBuildRegistry.batch_id.in_(batch_ids))
    ):
        grouped.setdefault(row.batch_id, []).append(row)
    return grouped


def _world_registry(rows: list[MapBuildRegistry]) -> MapBuildRegistry | None:
    return next(
        (
            row
            for row in rows
            if row.block_index is None
            and row.sub_block_index is None
            and row.parent_path is None
        ),
        None,
    )


def _world_registry_path(rows: list[MapBuildRegistry]) -> str | None:
    root = _world_registry(rows)
    if root is not None:
        return root.path

    header_parent_paths = {
        row.parent_path
        for row in rows
        if row.block_index is not None
        and row.sub_block_index is None
        and row.parent_path
    }
    return next(iter(header_parent_paths)) if len(header_parent_paths) == 1 else None


def _block_registry_path(
    rows: list[MapBuildRegistry],
    header: MapBuildRegistry | None,
) -> str | None:
    if header is not None:
        return header.path
    cell_parent_paths = {
        row.parent_path
        for row in rows
        if row.sub_block_index is not None and row.parent_path
    }
    return next(iter(cell_parent_paths)) if len(cell_parent_paths) == 1 else None


def _registry_display_label(path: str) -> str:
    """把 Registry 对象路径转换为面向用户的分块名称。"""

    object_name = path.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    if object_name.lower().endswith("_blockrefl"):
        return "反射分块"
    return object_name


def _registry_subtree_rows(
    rows: list[MapBuildRegistry],
    root: MapBuildRegistry,
) -> list[MapBuildRegistry]:
    """按 parent_path 收集一个 Registry 节点及其全部后代。"""

    by_parent: dict[str, list[MapBuildRegistry]] = {}
    for row in rows:
        if row.parent_path:
            by_parent.setdefault(row.parent_path, []).append(row)

    result = []
    pending = [root]
    seen: set[str] = set()
    while pending:
        row = pending.pop()
        if row.path in seen:
            continue
        seen.add(row.path)
        result.append(row)
        pending.extend(by_parent.get(row.path, ()))
    return result


def get_overview(
    db: Session,
    scene_id: str,
    *,
    platform: str | None = None,
    shading_quality: int | None = None,
    batch_id: str | None = None,
) -> dict | None:
    """返回一个批次的世界/分块/子分块指标，不做批次间对照。"""

    base = _base_snapshot_query(scene_id, platform, shading_quality)
    recent = list(db.scalars(_snapshot_order(base).limit(100)))
    if not recent:
        return None

    current = next((item for item in recent if item.batch_id == batch_id), None)
    if batch_id and current is None:
        current = db.scalars(base.where(MapBuildSnapshot.batch_id == batch_id)).first()
        if current is None:
            return None
    if current is None:
        current = recent[0]

    rows_by_batch = _rows_by_batch(db, [current.batch_id])
    current_rows = rows_by_batch[current.batch_id]

    current_by_cell = {
        (row.block_index, row.sub_block_index): row
        for row in current_rows
        if row.block_index is not None
    }
    blocks = []
    block_indexes = sorted({key[0] for key in current_by_cell})
    for block_index in block_indexes:
        current_block_rows = [
            row for row in current_rows if row.block_index == block_index
        ]
        current_header = current_by_cell.get((block_index, None))
        current_block = _aggregate_metrics(
            current_block_rows,
            current_header,
        )
        sub_blocks = []
        for key, row in sorted(
            current_by_cell.items(),
            key=lambda item: (
                item[0][0],
                item[0][1] is None,
                item[0][1] if item[0][1] is not None else -1,
            ),
        ):
            if key[0] != block_index or key[1] is None:
                continue
            cell_metrics = _row_metrics(row)
            sub_blocks.append(
                {
                    "index": key[1],
                    "label": f"0x{key[1]:02X}",
                    "path": row.path,
                    # metrics 保留为聚合口径兼容旧客户端；叶子节点
                    # 没有下级，因此三者相同。
                    "metrics": cell_metrics,
                    "self_metrics": cell_metrics,
                    "subtree_metrics": cell_metrics,
                    "has_children": False,
                }
            )
        block_self = (
            _row_metrics(current_header)
            if current_header is not None
            else None
        )
        blocks.append(
            {
                "index": block_index,
                "label": f"分块 {block_index}",
                "path": _block_registry_path(current_block_rows, current_header),
                # metrics 是已发布接口的聚合别名，新界面使用明确字段。
                "metrics": current_block,
                "self_metrics": block_self,
                "subtree_metrics": current_block,
                "has_children": bool(sub_blocks),
                "sub_blocks": sub_blocks,
            }
        )

    world_root = _world_registry(current_rows)
    world_self = (
        _row_metrics(world_root)
        if world_root is not None
        else None
    )
    auxiliary_blocks = []
    if world_root is not None:
        auxiliary_rows = sorted(
            (
                row
                for row in current_rows
                if row.parent_path == world_root.path
                and row.block_index is None
                and row.sub_block_index is None
            ),
            key=lambda row: row.path,
        )
        for row in auxiliary_rows:
            subtree_rows = _registry_subtree_rows(current_rows, row)
            self_metrics = _row_metrics(row)
            subtree_metrics = _aggregate_metrics(subtree_rows, row)
            auxiliary_blocks.append(
                {
                    "key": row.path,
                    "label": _registry_display_label(row.path),
                    "path": row.path,
                    "metrics": subtree_metrics,
                    "self_metrics": self_metrics,
                    "subtree_metrics": subtree_metrics,
                    "has_children": len(subtree_rows) > 1,
                }
            )
    world_subtree = _world_metrics(current, current_rows)
    return {
        "batch": _batch_dto(current),
        "available_batches": [_batch_dto(snapshot) for snapshot in recent],
        "world": {
            "label": "主分块",
            "path": _world_registry_path(current_rows),
            "metrics": world_subtree,
            "self_metrics": world_self,
            "subtree_metrics": world_subtree,
            "has_children": bool(blocks or auxiliary_blocks),
        },
        "blocks": blocks,
        "auxiliary_blocks": auxiliary_blocks,
    }


def get_trend(
    db: Session,
    scene_id: str,
    *,
    platform: str | None = None,
    shading_quality: int | None = None,
    block_index: int | None = None,
    sub_block_index: int | None = None,
    registry_path: str | None = None,
    metric_scope: str = "self",
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """按最近 N 个日历日或指定的闭区间日期返回趋势。"""

    if sub_block_index is not None and block_index is None:
        raise ValueError("查询子分块时必须提供 block_index")
    if registry_path is not None and (
        block_index is not None or sub_block_index is not None
    ):
        raise ValueError("registry_path 不能与 block_index/sub_block_index 同时使用")
    if metric_scope not in {"self", "subtree"}:
        raise ValueError("metric_scope 必须是 self 或 subtree")
    if not 1 <= days <= 365:
        raise ValueError("days 必须在 1 到 365 之间")
    if (start_date is None) != (end_date is None):
        raise ValueError("自定义日期范围必须同时提供 start_date 和 end_date")
    if start_date is not None and end_date is not None:
        if end_date < start_date:
            raise ValueError("end_date 不能早于 start_date")
        if (end_date - start_date).days + 1 > 90:
            raise ValueError("自定义日期范围最多 90 天")

    base = _base_snapshot_query(scene_id, platform, shading_quality)
    snapshots = []
    window_start = start_date
    window_end = end_date
    truncated = False
    if window_start is not None and window_end is not None:
        cutoff = datetime.combine(window_start, datetime.min.time())
        cutoff_end = datetime.combine(window_end + timedelta(days=1), datetime.min.time())
        descending = list(
            db.scalars(
                _snapshot_order(base.where(
                    Batch.created_at >= cutoff,
                    Batch.created_at < cutoff_end,
                )).limit(MAX_TREND_POINTS + 1)
            )
        )
        truncated = len(descending) > MAX_TREND_POINTS
        snapshots = descending[:MAX_TREND_POINTS]
        snapshots.reverse()
    else:
        latest = db.scalars(_snapshot_order(base).limit(1)).first()
        if latest is not None:
            window_end = latest.batch.created_at.date()
            window_start = window_end - timedelta(days=days - 1)
            cutoff = datetime.combine(window_start, datetime.min.time())
            descending = list(
                db.scalars(
                    _snapshot_order(base.where(Batch.created_at >= cutoff)).limit(
                        MAX_TREND_POINTS + 1
                    )
                )
            )
            truncated = len(descending) > MAX_TREND_POINTS
            snapshots = descending[:MAX_TREND_POINTS]
            snapshots.reverse()
    rows_by_batch = _rows_by_batch(db, [snapshot.batch_id for snapshot in snapshots])

    points = []
    for snapshot in snapshots:
        rows = rows_by_batch[snapshot.batch_id]
        metrics = None
        if registry_path is not None:
            row = next((row for row in rows if row.path == registry_path), None)
            if row is not None:
                metrics = (
                    _row_metrics(row)
                    if metric_scope == "self"
                    else _aggregate_metrics(_registry_subtree_rows(rows, row), row)
                )
        elif block_index is None:
            if metric_scope == "self":
                root = _world_registry(rows)
                if root is not None:
                    metrics = _row_metrics(root)
            else:
                metrics = _world_metrics(snapshot, rows)
        elif sub_block_index is None:
            block_rows = [row for row in rows if row.block_index == block_index]
            if block_rows:
                header = next(
                    (row for row in block_rows if row.sub_block_index is None), None
                )
                if metric_scope == "self":
                    if header is not None:
                        metrics = _row_metrics(header)
                else:
                    metrics = _aggregate_metrics(block_rows, header)
        else:
            row = next(
                (
                    row
                    for row in rows
                    if row.block_index == block_index
                    and row.sub_block_index == sub_block_index
                ),
                None,
            )
            if row is not None:
                metrics = (
                    _row_metrics(row)
                    if metric_scope == "self"
                    else _aggregate_metrics([row], row)
                )
        points.append({"batch": _batch_dto(snapshot), "metrics": metrics})

    if registry_path is not None:
        base_label = _registry_display_label(registry_path)
        selection = {
            "scope": "auxiliary_block",
            "registry_path": registry_path,
        }
    elif block_index is None:
        base_label = "主分块"
        selection = {"scope": "main_block"}
    elif sub_block_index is None:
        base_label = f"分块 {block_index}"
        selection = {
            "scope": "block",
            "block_index": block_index,
        }
    else:
        base_label = f"分块 {block_index} / 子分块 0x{sub_block_index:02X}"
        selection = {
            "scope": "sub_block",
            "block_index": block_index,
            "sub_block_index": sub_block_index,
        }
    selection["metric_scope"] = metric_scope
    selection["label"] = (
        base_label
        if sub_block_index is not None and registry_path is None
        else f"{base_label} · {'自身数据' if metric_scope == 'self' else '含子级汇总'}"
    )
    return {
        "selection": selection,
        "points": points,
        "window": {
            "days": (
                (window_end - window_start).days + 1
                if window_start is not None and window_end is not None
                else days
            ),
            "start_date": window_start.isoformat() if window_start else None,
            "end_date": window_end.isoformat() if window_end else None,
            "truncated": truncated,
        },
    }
