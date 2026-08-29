"""GPMHeatmap 配置命令的 HTTP 适配层。"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .gpm_common import http_error
from .gpm_configuration_package import (
    ConfigurationPackageError,
    apply_configuration_import,
    export_configuration_package,
    inspect_configuration_package,
    remove_transfer,
)
from .gpm_map_config import map_preview, save_map_configuration


router = APIRouter()


@router.get("/api/gpm-heatmaps/configuration/export")
def export_configuration(scope: str = Query(default="all")):
    try:
        path, filename = export_configuration_package(scope)
    except ConfigurationPackageError as exc:
        issue = exc.issues[0]
        raise http_error(409, issue["code"], issue["message"]) from exc
    return FileResponse(
        path,
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(remove_transfer, path),
    )


@router.post("/api/gpm-heatmaps/configuration/imports/inspect")
def inspect_configuration(
    package: Annotated[UploadFile, File(description="GPMHeatmap ZIP 配置包")],
):
    return inspect_configuration_package(package)


@router.post("/api/gpm-heatmaps/configuration/imports/{import_id}/apply")
def apply_configuration(import_id: str):
    try:
        return apply_configuration_import(import_id)
    except FileNotFoundError as exc:
        raise http_error(404, "GPM_CONFIG_IMPORT_NOT_FOUND", "导入检查记录不存在或已过期") from exc
    except ConfigurationPackageError as exc:
        issue = exc.issues[0]
        raise http_error(409, issue["code"], issue["message"]) from exc


@router.put("/api/gpm-heatmaps/configuration/maps/{map_name}")
def put_map_configuration(
    map_name: str,
    configuration: Annotated[str, Form(description="完整地图配置 JSON")],
    image: Annotated[UploadFile | None, File(description="可选地图图片")] = None,
):
    try:
        payload = json.loads(configuration)
    except (TypeError, json.JSONDecodeError) as exc:
        raise http_error(422, "INVALID_GPM_MAP_CONFIGURATION", "地图配置必须是 JSON 对象") from exc
    return save_map_configuration(map_name, payload, image)


@router.get("/api/gpm-heatmaps/configuration/maps/{map_name}/preview")
def get_map_preview(map_name: str):
    return map_preview(map_name)
