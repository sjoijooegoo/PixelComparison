"""GPMHeatmap 路由装配。

业务行为分别封装在上传、批次目录、工作区、地图配置和标尺配置模块中。
"""

from fastapi import APIRouter

from .gpm_batch_catalog import router as batch_catalog_router
from .gpm_configuration_routes import router as map_config_router
from .gpm_offline_package import router as offline_package_router
from .gpm_scale_config import router as scale_config_router
from .gpm_upload import router as upload_router
from .gpm_workspace import router as workspace_router


router = APIRouter()
router.include_router(upload_router)
router.include_router(batch_catalog_router)
router.include_router(workspace_router)
router.include_router(offline_package_router)
router.include_router(map_config_router)
router.include_router(scale_config_router)
