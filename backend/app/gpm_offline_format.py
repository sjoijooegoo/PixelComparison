"""GPM 热力图领域常量与离线包格式版本；保持为纯标准库模块。"""

PACKAGE_FORMAT = "scenescope.heatmap-pack"
PACKAGE_VERSION = 2
MIN_VIEWER_VERSION = 2
IMAGE_MODE = "thumbnail"
MEDIA_TYPE = "application/vnd.scenescope.heatmap+zip"
CONFIGURATION_FILENAME = "heatmap.zip"

PLATFORMS = ("IOS", "Android", "Windows")
QUALITY_LABELS = {0: "节能", 1: "流畅", 2: "均衡", 3: "精美", 4: "极致", 5: "电影"}
