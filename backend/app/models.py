from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _new_cache_version() -> str:
    """短随机版本号：文件内容重建后 URL 必须变化，但无需读取文件 mtime。"""
    return uuid.uuid4().hex[:16]


class Batch(Base):
    """一次截图采集运行:项目 + 分支 + 平台,产出一组截图。"""
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # 例 20240524_1530
    branch_tag: Mapped[str] = mapped_column(
        String, default="main", server_default="main", index=True
    )
    scene_id: Mapped[str] = mapped_column(String)  # UE Level / 场景标识,同场景才能对比
    p4_version: Mapped[int | None] = mapped_column(Integer, nullable=True)  # P4 changelist,越大越新;可空(未上报)
    platform: Mapped[str] = mapped_column(String)
    creator: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 新版上报 manifest 附带的元信息
    batch_url: Mapped[str | None] = mapped_column(String, nullable=True)  # 真实流水线链接
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)  # 例 1920x1080
    capture_type: Mapped[str | None] = mapped_column(String, nullable=True)  # 例 levelsequence
    levelsequence_name: Mapped[str | None] = mapped_column(String, nullable=True)
    levelsequence_path: Mapped[str | None] = mapped_column(String, nullable=True)
    shading_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 画质档位 0-5,旧数据为空

    screenshots: Mapped[list["Screenshot"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    map_build_snapshot: Mapped[MapBuildSnapshot | None] = relationship(
        back_populates="batch", cascade="all, delete-orphan", uselist=False
    )


class Screenshot(Base):
    """截图只属于批次;基线图即基线批次里的截图。"""
    __tablename__ = "screenshots"
    # 同一批次内检查点名唯一:防并发同名上传产生重复行(应用层 409 兜底)
    __table_args__ = (UniqueConstraint("batch_id", "scene_name", name="uq_screenshot_batch_scene"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    scene_name: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String)  # 相对 IMAGES_DIR
    # 图片 URL 的缓存破坏标记。旧库迁移后为空时由接口回退到行 id；新上传使用随机值，
    # 因而覆盖同号批次即使复用了相同路径和 SQLite id，URL 仍会变化。
    cache_version: Mapped[str | None] = mapped_column(
        String, nullable=True, default=_new_cache_version,
    )
    # 新版上报:帧序与相机位姿(location/rotation)
    frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    batch: Mapped[Batch] = relationship(back_populates="screenshots")
    # 图片 URL 统一由数据库 cache_version 生成缓存版本；不读取远程文件 mtime。
    # 不在模型上提供裸 /images/<path> 属性, 防覆盖后浏览器/CDN 服务旧图。


class MapBuildSnapshot(Base):
    """一个批次的场景烘培数据快照；完整 JSON 与查询热字段同时保留。"""

    __tablename__ = "map_build_snapshots"

    batch_id: Mapped[str] = mapped_column(
        ForeignKey("batches.id"), primary_key=True
    )
    format_version: Mapped[str] = mapped_column(
        String, default="map-build-data/v2"
    )
    world_resident_bytes: Mapped[int] = mapped_column(BigInteger)
    world_all_mips_bytes: Mapped[int] = mapped_column(BigInteger)
    world_cook_estimate_bytes: Mapped[int] = mapped_column(BigInteger)
    world_texture_count: Mapped[int] = mapped_column(Integer)
    # 趋势可能跨数百天读取许多快照；原始 JSON 只在显式访问时加载，避免每个点附带约百 KB。
    raw_payload: Mapped[dict] = mapped_column(JSON, deferred=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    batch: Mapped[Batch] = relationship(back_populates="map_build_snapshot")
    registries: Mapped[list[MapBuildRegistry]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class MapBuildRegistry(Base):
    """烘培 registry 的规范化指标行，供网格与跨批次趋势直接查询。"""

    __tablename__ = "map_build_registries"
    __table_args__ = (
        UniqueConstraint("batch_id", "path", name="uq_map_build_registry_path"),
        Index(
            "ix_map_build_registry_cell",
            "batch_id",
            "block_index",
            "sub_block_index",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("map_build_snapshots.batch_id"), index=True
    )
    path: Mapped[str] = mapped_column(String)
    parent_path: Mapped[str | None] = mapped_column(String, nullable=True)
    block_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sub_block_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    resident_bytes: Mapped[int] = mapped_column(BigInteger)
    all_mips_bytes: Mapped[int] = mapped_column(BigInteger)
    cook_estimate_bytes: Mapped[int] = mapped_column(BigInteger)
    texture_count: Mapped[int] = mapped_column(Integer)
    subtree_resident_bytes: Mapped[int] = mapped_column(BigInteger)
    subtree_all_mips_bytes: Mapped[int] = mapped_column(BigInteger)
    subtree_cook_estimate_bytes: Mapped[int] = mapped_column(BigInteger)
    subtree_texture_count: Mapped[int] = mapped_column(Integer)
    lightmap_bytes: Mapped[int] = mapped_column(BigInteger)
    hue_bytes: Mapped[int] = mapped_column(BigInteger)
    shadowmap_bytes: Mapped[int] = mapped_column(BigInteger)
    lightmap_all_mips_bytes: Mapped[int] = mapped_column(BigInteger)
    hue_all_mips_bytes: Mapped[int] = mapped_column(BigInteger)
    shadowmap_all_mips_bytes: Mapped[int] = mapped_column(BigInteger)
    mesh_map_build_data_bytes: Mapped[int] = mapped_column(BigInteger)
    precomputed_light_volume_bytes: Mapped[int] = mapped_column(BigInteger)
    precomputed_reflection_volume_bytes: Mapped[int] = mapped_column(BigInteger)
    volumetric_lightmap_bytes: Mapped[int] = mapped_column(BigInteger)
    light_build_data_bytes: Mapped[int] = mapped_column(BigInteger)
    reflection_capture_bytes: Mapped[int] = mapped_column(BigInteger)
    precomputed_instanced_ilc_bytes: Mapped[int] = mapped_column(BigInteger)
    precomputed_instanced_pr_bytes: Mapped[int] = mapped_column(BigInteger)
    lightmap_resource_cluster_bytes: Mapped[int] = mapped_column(BigInteger)

    snapshot: Mapped[MapBuildSnapshot] = relationship(back_populates="registries")


class Baseline(Base):
    """把某个被认可的批次晋升为基线版本(按分支和平台隔离)。"""
    __tablename__ = "baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String, index=True)  # 例 v1.1.5
    branch_tag: Mapped[str] = mapped_column(
        String, default="main", server_default="main", index=True
    )
    scene_id: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    source_batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"))
    status: Mapped[str] = mapped_column(String, default="active")  # active/retired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    source_batch: Mapped[Batch] = relationship()


class Comparison(Base):
    """一次对比 = 当前批次 × 参照批次。

    参照批次任选;若它恰好是已晋升的基线,记录 baseline_id 以便显示版本号。
    同一批次可与多个参照批次各比一次。
    """
    __tablename__ = "comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    ref_batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    baseline_id: Mapped[int | None] = mapped_column(
        ForeignKey("baselines.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default="pass")  # pass/warn/fail
    diff_avg: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    batch: Mapped[Batch] = relationship(foreign_keys=[batch_id])
    ref_batch: Mapped[Batch] = relationship(foreign_keys=[ref_batch_id])
    baseline: Mapped[Baseline | None] = relationship()
    items: Mapped[list["ComparisonItem"]] = relationship(
        back_populates="comparison", cascade="all, delete-orphan"
    )


class Setting(Base):
    """对比算法配置(单行,id=1,JSON 存全部参数)。"""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ComparisonItem(Base):
    """按场景名配对的单场景对比结果;单边缺图时状态为 added/missing。"""
    __tablename__ = "comparison_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey("comparisons.id"), index=True)
    scene_name: Mapped[str] = mapped_column(String, index=True)
    current_shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("screenshots.id"), nullable=True
    )
    baseline_shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("screenshots.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String)  # pass/warn/fail/added/missing
    diff_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    heatmap_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # 强制重算会删除并重建明细；随机版本确保同一路径的热力图不会命中旧缓存。
    cache_version: Mapped[str | None] = mapped_column(
        String, nullable=True, default=_new_cache_version,
    )

    comparison: Mapped[Comparison] = relationship(back_populates="items")
    current_shot: Mapped[Screenshot | None] = relationship(foreign_keys=[current_shot_id])
    baseline_shot: Mapped[Screenshot | None] = relationship(foreign_keys=[baseline_shot_id])
