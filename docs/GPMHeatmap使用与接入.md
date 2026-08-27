# GPMHeatmap 使用与接入

GPMHeatmap 是与截图批次、截图对比和烘培数据相互隔离的点位热力模块。它使用独立 SQLite、独立文件目录和独立 API；相同的 `batch_id` 可以分别存在于截图批次与 GPMHeatmap 中，删除任一模块的数据不会连带删除另一模块。

## 1. 页面

打开 `/gpm-heatmap`，或用 `/gpm-heatmap/<场景ID>` 直接进入指定场景。页面按以下顺序筛选：

1. 平台；
2. 场景 ID；
3. 画质；
4. 采集批次（显示为 `P4 <版本> · <采集时间>`）。

首屏左侧是地图与热力点，右侧是当前点位的 `detail_data` 列表，下方是横向点位截图。点击地图方块或截图会同步点位、详情和地址栏。地图点位使用纯色方块，短箭头表示采集方向。

版本趋势默认查询最近 30 天。只有上报数据提供稳定 `point_key`（也接受 `teleport_point_id`）时，后端才会跨批次关联同一物理点位。缺少稳定键时只展示当前批次值，并明确提示无法安全形成趋势；不会用易变化的数组序号拼接历史数据。

## 2. 数据与环境变量

默认目录：

```text
<PIXELCOMP_DATA_DIR>/gpm_heatmap/
  gpm_heatmap.db
  assets/
    maps/
    uploads/
```

可分别覆盖：

| 环境变量 | 默认值 |
|---|---|
| `PIXELCOMP_GPM_DIR` | `<PIXELCOMP_DATA_DIR>/gpm_heatmap` |
| `PIXELCOMP_GPM_DB_PATH` | `<PIXELCOMP_GPM_DIR>/gpm_heatmap.db` |
| `PIXELCOMP_GPM_ASSETS_DIR` | `<PIXELCOMP_GPM_DIR>/assets` |

`gpm_heatmap.db` 应放本地可靠磁盘；地图和点位图片可以通过 `PIXELCOMP_GPM_ASSETS_DIR` 放到容量盘。开启现有数据库自动备份时，调度器会把 `shotdiff.db` 和 `gpm_heatmap.db` 一并在线备份到当天的 `backup/YYYY-MM-DD/db/`。

## 3. 上报点位数据

接口：`POST /api/gpm-heatmaps/uploads`，请求类型为 `multipart/form-data`。

| 字段 | 必填 | 说明 |
|---|---|---|
| `report` | 是 | `GPMHeatmap.json`；每个场景携带 `p4_version`、`platform`、`shading_quality` |
| `screenshots` | 是 | `GPMScreenshot.zip` |
| `pipeline_data` | 是 | JSON 对象，见下方结构 |
| `overwrite` | 否 | 默认 `false`；同分支、同批次覆盖时必须显式为 `true` |

`pipeline_data` 的规范结构如下。`batch_id` 和 `captured_at` 必填，`branch_tag` 缺省为 `main`，`batch_url` 可省略：

```json
{
  "batch_id": "gpm-demo-20260826",
  "batch_url": "https://example/pipeline/gpm-demo-20260826",
  "captured_at": "2026-08-26T15:00:00+08:00",
  "branch_tag": "main"
}
```

同一报告内所有场景的 `platform`、`shading_quality` 和 `p4_version` 必须一致；`shading_quality` 范围为 0～5。为兼容已经接入的旧调用，后端暂时仍接受同名顶层表单字段，但新调用不得重复发送；两套字段同时存在且值冲突时整次上报失败。

ZIP 中图片文件名的主文件名必须与每个点位的 `screenshot_id` 一致，例如 `screenshot_id=8` 对应 `8.jpg`。少图、多图、重复图、不安全路径、不可解码图片，以及同一场景内重复的稳定 `point_key`，都会使整次上报失败，不会写入部分场景。

本仓库演示数据可这样上报：

```powershell
curl.exe -X POST "http://127.0.0.1:8020/api/gpm-heatmaps/uploads" `
  -F "report=@D:/PixelComparison/temp/GPM/1/GPMHeatmap.json;type=application/json" `
  -F "screenshots=@D:/PixelComparison/temp/GPM/1/GPMScreenshot.zip;type=application/zip" `
  -F 'pipeline_data={"batch_id":"gpm-demo-20260826","batch_url":"https://example/pipeline/gpm-demo-20260826","captured_at":"2026-08-26T15:00:00+08:00","branch_tag":"main"}' `
  -F "p4_version=2960783" `
  -F "platform=Android" `
  -F "shading_quality=5" `
  -F "overwrite=true"
```

仓库中的早期演示报告没有内嵌 `p4_version`、`platform` 和 `shading_quality`。直接使用该旧样本时，可通过兼容表单字段补充这三项；生产采集端应生成包含这些字段的新报告。

## 4. 上传地图和坐标配置

接口：`POST /api/gpm-heatmaps/maps/<场景ID>`，请求类型为 `multipart/form-data`。每次上传创建新版本并自动激活，历史版本及图片保留。

| 字段 | 说明 |
|---|---|
| `image` | PNG、JPEG 或 WebP 地图，最大 32 MiB |
| `origin_x` / `origin_y` | 世界坐标左下角起点 |
| `range_x` / `range_y` | X/Y 世界坐标范围，必须大于 0 |
| `x_reverse` / `y_reverse` | 坐标轴是否反转 |
| `color_ranges` | 指标到三个分段阈值的 JSON 对象 |

Village 演示地图配置：

```powershell
curl.exe -X POST "http://127.0.0.1:8020/api/gpm-heatmaps/maps/Village_Dimension_Main" `
  -F "image=@D:/PixelComparison/temp/GPM/1/Village_Dimension_Main.png;type=image/png" `
  -F "origin_x=-251954" -F "origin_y=201148" `
  -F "range_x=76000" -F "range_y=72000" `
  -F "x_reverse=false" -F "y_reverse=true" `
  --form-string 'color_ranges={"Scene_DC":[150,300,450]}'
```

前端对地图图片使用 `contain`，Canvas 只在图片真实渲染矩形内绘点。X/Y 分别按各自世界范围映射，因此地图图片无需强制裁成世界坐标范围的相同比例，但必须完整包含配置范围。

## 5. 主要读取接口

| 接口 | 用途 |
|---|---|
| `GET /api/gpm-heatmaps/meta` | 平台、画质、场景筛选项 |
| `GET /api/gpm-heatmaps/scenes/{scene_id}/frame` | 地图配置、热力指标、批次列表和紧凑点位数据 |
| `GET /api/gpm-heatmaps/points/{point_id}` | 单点完整 `detail_data` 与原图 |
| `GET /api/gpm-heatmaps/points/{point_id}/trends?days=30` | 单点跨批次趋势或不可关联原因 |
| `DELETE /api/gpm-heatmaps/uploads/{batch_id}?branch_tag=main` | 删除 GPM 批次、点位和独立截图资源 |

列表接口只返回点位热字段和缩略图；体积较大的 `detail_data` 在用户选中点位后单独加载。快速切换场景、批次和点位时，前端会取消旧请求并通过请求序号阻止过期响应覆盖当前状态。
