from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Batch(Base):
    """一次截图采集运行:项目 + 分支 + 平台,产出一组截图。"""
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # 例 20240524_1530
    scene_id: Mapped[str] = mapped_column(String)  # UE Level / 场景标识,同场景才能对比
    p4_version: Mapped[int] = mapped_column(Integer)  # P4 changelist,越大越新
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


class Screenshot(Base):
    """截图只属于批次;基线图即基线批次里的截图。"""
    __tablename__ = "screenshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    scene_name: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String)  # 相对 IMAGES_DIR
    # 新版上报:帧序与相机位姿(location/rotation)
    frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    batch: Mapped[Batch] = relationship(back_populates="screenshots")

    @property
    def url(self) -> str:
        return f"/images/{self.path}"


class Baseline(Base):
    """把某个被认可的批次晋升为基线版本(按平台隔离)。"""
    __tablename__ = "baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String, index=True)  # 例 v1.1.5
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

    comparison: Mapped[Comparison] = relationship(back_populates="items")
    current_shot: Mapped[Screenshot | None] = relationship(foreign_keys=[current_shot_id])
    baseline_shot: Mapped[Screenshot | None] = relationship(foreign_keys=[baseline_shot_id])
