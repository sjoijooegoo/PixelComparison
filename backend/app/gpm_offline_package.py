"""SceneScope 热力图离线数据包。

一个 ``.ssheat`` 包对应一次 GPM 上传，只保存批次数据及缩略图。
地图资源与标尺由工作区唯一的配置包提供，不随批次重复导出。
"""

from __future__ import annotations

import io
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Query
from fastapi.responses import Response

from .gpm_common import http_error, require_identifier, safe_segment
from .gpm_offline_format import (
    IMAGE_MODE,
    MEDIA_TYPE,
    MIN_VIEWER_VERSION,
    PACKAGE_FORMAT,
    PACKAGE_VERSION,
)
from .gpm_storage import connect_gpm_database, gpm_assets_dir
from .gpm_workspace import get_map_frame, get_point_details


router = APIRouter()


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    return (
        json.dumps(value, ensure_ascii=False, indent=indent, separators=separators) + "\n"
    ).encode("utf-8")


def _asset_source(url: str | None) -> Path | None:
    if not url:
        return None
    prefix = "/gpm-assets/"
    if not url.startswith(prefix):
        raise RuntimeError(f"GPM 资源 URL 不受支持：{url}")
    relative = PurePosixPath(url[len(prefix):])
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimeError(f"GPM 资源 URL 不安全：{url}")
    root = gpm_assets_dir().resolve()
    target = root.joinpath(*relative.parts).resolve()
    if target == root or root not in target.parents or not target.is_file():
        raise RuntimeError(f"GPM 资源不存在：{url}")
    return target


def _offline_asset_url(pack_id: str, entry: str) -> str:
    return f"/gpm-assets/offline/{pack_id}/{entry}"


def _batch_row(batch_id: str, branch_tag: str):
    connection = connect_gpm_database()
    try:
        row = connection.execute(
            """
            SELECT id, batch_id, branch_tag, batch_url, captured_at, p4_version,
                   platform, shading_quality
            FROM gpm_uploads WHERE batch_id = ? AND branch_tag = ?
            """,
            (batch_id, branch_tag),
        ).fetchone()
        if not row:
            raise http_error(404, "GPM_BATCH_NOT_FOUND", "找不到要导出的热力图批次")
        maps = [
            item["map_name"]
            for item in connection.execute(
                "SELECT map_name FROM gpm_upload_maps WHERE upload_id = ? ORDER BY id",
                (row["id"],),
            )
        ]
        return dict(row), maps
    finally:
        connection.close()


def build_offline_package(batch_id: str, branch_tag: str = "main") -> tuple[bytes, dict]:
    """返回批次数据包及 manifest；查看时使用工作区共享配置。"""

    batch_id = require_identifier(batch_id, "batch_id", maximum=120)
    branch_tag = require_identifier(branch_tag.strip().lower(), "branch_tag", maximum=120)
    upload, map_names = _batch_row(batch_id, branch_tag)
    identity = f"{upload['branch_tag']}\0{upload['batch_id']}".encode("utf-8")
    pack_id = f"pack-{hashlib.sha256(identity).hexdigest()[:16]}"
    files: dict[str, bytes] = {}
    manifest_maps = []

    for map_name in map_names:
        map_segment = safe_segment(map_name, "map")
        frame_file = f"data/maps/{map_segment}/frame.json"
        points_dir = f"data/maps/{map_segment}/points"
        frame = get_map_frame(
            map_name,
            branch_tag,
            upload["platform"],
            upload["shading_quality"],
            batch_id,
            None,
            None,
        )
        # 配置来自工作区，批次元数据只在 manifest 保存一次，聚合字段读取时重建。
        for key in ("map_config", "batch", "available_batches", "latest_p4_version", "previous_batch"):
            frame.pop(key, None)
        for metric in frame["heat_map"]:
            metric.pop("scale", None)

        details_by_id = get_point_details([int(point["id"]) for point in frame["points"]])
        for point in frame["points"]:
            source_point_id = int(point["id"])
            screenshot_segment = safe_segment(str(point["screenshot_id"]), "point")
            thumbnail_entry = f"assets/maps/{map_segment}/thumbnails/{screenshot_segment}.webp"
            source = _asset_source(point["thumbnail_url"])
            if source is None:
                raise RuntimeError(f"点位 {point['index']} 缺少缩略图")
            files.setdefault(thumbnail_entry, source.read_bytes())
            thumbnail_url = _offline_asset_url(pack_id, thumbnail_entry)
            point["thumbnail_url"] = thumbnail_url
            point["image_url"] = thumbnail_url
            point.pop("metric_change_percent", None)

            detail = details_by_id[source_point_id]
            detail["thumbnail_url"] = thumbnail_url
            detail["image_url"] = thumbnail_url
            files[f"{points_dir}/{source_point_id}.json"] = _json_bytes(detail)

        files[frame_file] = _json_bytes(frame)
        manifest_maps.append({
            "map_name": map_name,
            "point_count": len(frame["points"]),
            "frame_file": frame_file,
            "points_dir": points_dir,
        })

    manifest = {
        "format": PACKAGE_FORMAT,
        "format_version": PACKAGE_VERSION,
        "min_viewer_version": MIN_VIEWER_VERSION,
        "image_mode": IMAGE_MODE,
        "pack_id": pack_id,
        "upload": {
            "id": upload["id"],
            "batch_id": upload["batch_id"],
            "branch_tag": upload["branch_tag"],
            "batch_url": upload["batch_url"],
            "captured_at": upload["captured_at"],
            "p4_version": upload["p4_version"],
            "platform": upload["platform"],
            "shading_quality": upload["shading_quality"],
        },
        "maps": manifest_maps,
    }

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        strict_timestamps=False,
    ) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest, pretty=True))
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return output.getvalue(), manifest


@router.get("/api/gpm-heatmaps/uploads/{batch_id}/offline-package")
def download_offline_package(
    batch_id: str,
    branch_tag: str = Query("main"),
):
    content, manifest = build_offline_package(batch_id, branch_tag)
    filename = (
        f"SceneScope-heatmap-{safe_segment(manifest['upload']['branch_tag'], 'main')}-"
        f"{safe_segment(batch_id, 'batch')}.ssheat"
    )
    return Response(
        content=content,
        media_type=MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
