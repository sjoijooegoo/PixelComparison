# GPMHeatmap 使用与接入

GPMHeatmap 是与截图对比、截图/烘培批次完全隔离的点位热力模块。它使用独立 SQLite、资源目录和 API。`batch_id` 只在 GPM 数据域内唯一；删除 GPM 批次不会影响截图、烘培数据，也不会删除独立的地图和标尺配置。

## 1. 页面与筛选

工作区地址为 `/gpm-heatmap/<map_name>`，右上角分别进入独立批次管理 `/batch-management/gpm` 和统一设置 `/settings/gpm-heatmap`。

工作区按平台、地图名称、画质、采集批次筛选。地图选项来自地图配置并按只读数字 ID 升序排列；没有采集数据的地图仍保留，空数据作用域只展示普通空状态，不清空平台、地图或画质选项。切换平台、地图或画质时，以当前 P4 为锚点选择最接近的批次；刷新页面则选择当前范围内最新批次。

地图点位、详情树、横向截图和数据趋势共享当前点位。URL 的 `point` 是当前批次内的点位序号 `index`，不是数据库自增 ID。同一地图内切换平台、画质或批次时按该序号恢复逻辑点；目标作用域没有对应序号时回到首点，切换地图则不继承。趋势支持整体平均或同一 `index` 的单点趋势，时间范围固定为 7、14、30 天，默认整体平均和 14 天。地图点位悬停面板中的变化率，以同分支、地图、平台和画质范围内数据库上报 ID 紧邻的上一批为基准，并按相同 `index` 匹配点位；它表示上报顺序，不使用 `captured_at` 排序。上一批、对应指标缺失或上一批指标值为 0 时不计算百分比。

## 2. 存储与生命周期

默认目录：

```text
<PIXELCOMP_DATA_DIR>/gpm_heatmap/
  gpm_heatmap.db
  assets/
    maps/
    uploads/
```

| 环境变量 | 默认值 |
|---|---|
| `PIXELCOMP_GPM_DIR` | `<PIXELCOMP_DATA_DIR>/gpm_heatmap` |
| `PIXELCOMP_GPM_DB_PATH` | `<PIXELCOMP_GPM_DIR>/gpm_heatmap.db` |
| `PIXELCOMP_GPM_ASSETS_DIR` | `<PIXELCOMP_GPM_DIR>/assets` |

GPM 数据只保留最近 30×24 小时。后端启动、每小时以及成功上报后都会删除过期上传及其点位截图；地图、图片和标尺配置不随批次淘汰。

GPMHeatmap 仍处于 Demo 阶段，只存在一份最终 schema，不提供历史迁移或兼容表。后端检测到非当前版本的独立 GPM 数据库时，会清空 GPM 数据库和 GPM 资源目录后重建；主业务数据库及其图片不受影响。部署新版本前如需保留 Demo 文件，应先离线备份。

最终数据模型：

- `gpm_uploads`：流水线批次和平台/画质/P4/采集时间；
- `gpm_upload_maps`：一次上传内以 `map_name` 唯一标识的地图数据；
- `gpm_points`：结构化坐标、方向、指标、详情和截图路径；
- `gpm_map_definitions`：地图名称、排序 ID、坐标映射和当前图片；
- `gpm_metric_scales`：命名颜色表达式段；
- `gpm_metric_scale_sets` / `gpm_metric_scale_set_items`：上报 Key 到标尺的复用集合；
- `gpm_map_scale_set_bindings`：地图 + 平台 + 画质到标尺集的唯一绑定。

模块中没有 `scene_id`、旧阈值/方向列、图片修订表或 `gpm_schema_migrations`；对外和内部唯一地图身份都是 `map_name`。

## 3. 最终上报契约

`POST /api/gpm-heatmaps/uploads` 使用 `multipart/form-data`，只接受以下字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `report` | 是 | `GPMHeatmap.json` |
| `screenshots` | 是 | `GPMScreenshot.zip` |
| `pipeline_data` | 是 | 流水线元数据 JSON |
| `overwrite` | 否 | 同名批次覆盖必须显式为 `true` |

`pipeline_data`：

```json
{
  "batch_id": "gpm-20260826-4634",
  "batch_url": "https://example/pipeline/4634",
  "captured_at": "2026-08-26T15:00:00+08:00",
  "branch_tag": "main"
}
```

`captured_at` 必须包含时区。`batch_id` 在 GPM 数据域内跨分支全局唯一，覆盖不能改变分支。

报告中每个 `data[]` 必须直接提供且保持一致的 `p4_version`、`platform` 和 `shading_quality`，必须提供唯一地图名称和 `detail[]`。地图名称优先读取 `map_name`；仅缺少 `map_name` 时允许用 `pic_name` 作为字段别名，两者同时存在则值必须一致。仍不接受顶层同名表单字段或 `teleport_point_id` 点位回退。平台只支持 `IOS`、`Android`、`Windows`，画质为 0～5，P4 为非负整数。

上报中的未知 `map_name` 会在同一数据库事务内自动登记为待配置地图，按现有最大地图 ID 继续分配；上报失败时登记也会回滚。自动登记不猜测图片、坐标或标尺，需在设置页补充后才会产生地图投影。

每个点位必须包含非负整数 `index`、`screenshot_id`、二维以上 `position` 和 `direction`。`index` 在单张地图内唯一，并且同一地图各批次应保持相同序号的业务含义稳定；`screenshot_id` 必须是对应 `index` 的数字文本（允许前导零），并用于精确匹配截图文件。`heat_map_data`、`trend_data` 为对象，`detail_data` 为数组。报告 JSON 最多嵌套 32 层，单次上报最多 5,000 个点位。

ZIP 图片主文件名必须与 `screenshot_id` 精确对应，例如 `screenshot_id=8` 对应 `8.png`。压缩包最大 1 GiB、解压后最大 4 GiB，单张图片最多 4,000 万像素。少图、多图、重复图、不安全路径或不可解码图片都会让整次上报失败，不产生部分数据。

示例：

```powershell
curl.exe -X POST "http://127.0.0.1:8020/api/gpm-heatmaps/uploads" `
  -F "report=@D:/data/GPMHeatmap.json;type=application/json" `
  -F "screenshots=@D:/data/GPMScreenshot.zip;type=application/zip" `
  -F 'pipeline_data={"batch_id":"gpm-20260826-4634","batch_url":"https://example/pipeline/4634","captured_at":"2026-08-26T15:00:00+08:00","branch_tag":"main"}' `
  -F "overwrite=true"
```

## 4. 地图与标尺配置

设置页分为地图配置、指标标尺集、指标标尺库三个组件。地图和两类标尺分别从 ID 0 开始按 ID 排序，引用关系使用数据库外键 ID；修改名称不会断开关系。

地图名称必须与上报 `map_name` 完全一致。地图编辑器一次提交描述、坐标起点、X/Y 范围、轴反转、全部平台/画质标尺绑定和可选新图片。定义、绑定和图片切换由一个后端命令处理，不存在前端分三次保存的半完成状态；替换图片成功后会清理旧图片文件。

地图列表可以删除独立配置。删除使用 revision 防止旧页面覆盖新配置，并清理当前底图和全部标尺绑定；同名历史 GPM 批次、点位和截图不随配置删除，后续再次上报同名地图会重新生成待配置项。

指标标尺只保存名称和 2～10 个 `{color, expression}` 段。表达式支持 `<`、`<=`、`>`、`>=` 和 `&`，必须无重叠、无断档地覆盖完整数轴。标尺集由用户自行维护任意“上报 Key → 标尺”映射，不从历史数据推断固定指标。

运行时按 `map_name + platform + shading_quality` 选择标尺集，再按大小写敏感的原始指标 Key 精确匹配。没有绑定或 Key 未匹配时，以当前批次该指标最小值到最大值动态作绿色到红色线性着色。

原子地图配置接口：

```text
PUT /api/gpm-heatmaps/configuration/maps/{map_name}
Content-Type: multipart/form-data

configuration=<完整地图配置 JSON>
image=<可选 PNG/JPEG/WebP，最大 32 MiB>
```

设置页顶栏“返回热力图”右侧的导入、导出图标用于迁移“热力图配置包”。导出时可以选择全部配置、地图与图片或标尺配置。完整包是可人工阅读和编辑的 ZIP，包含：

```text
manifest.json
maps.json
metric-scales.json
scale-sets.json
map-bindings.json
images/
```

`maps.json + images/` 是独立的地图资源模块，只描述地图排序、图片、坐标范围和轴向；`metric-scales.json + scale-sets.json + map-bindings.json` 是独立的标尺模块。地图资源包导入到已有地图时只更新图片与坐标信息，不修改其平台/画质标尺关联；标尺包则不修改地图图片和坐标范围。包内不生成 README，也不包含批次、点位、截图或趋势数据。

`maps.json` 中每张地图始终保留 `"image": { "file": null }`；配置图片时只需把 `file` 改为 ZIP 内 `images/` 下的相对路径。图片宽高由导入检查直接读取图片得到，不写入配置文件。

导入分为两个明确步骤：先检查包内 JSON、图片、表达式、ID、引用、名称和 revision，并展示新增/更新差异；检查通过后再“应用配置”。应用在一个数据库事务内安全合并，包中没有出现的线上配置继续保留，不执行隐式删除；检查完成后配置若被其他用户修改，应用会因 revision 冲突而中止，要求重新检查。

## 5. 最终 API

| 接口 | 用途 |
|---|---|
| `GET /api/gpm-heatmaps/catalog` | 分支、平台、画质和按 ID 排序的地图筛选目录 |
| `GET /api/gpm-heatmaps/uploads?map_name=...` | 分页查询独立 GPM 批次 |
| `POST /api/gpm-heatmaps/uploads` | 原子上报报告和截图 |
| `DELETE /api/gpm-heatmaps/uploads/{batch_id}?branch_tag=main` | 删除上传、地图数据、点位和截图 |
| `GET /api/gpm-heatmaps/maps/{map_name}/frame` | 当前地图帧、批次、点位和标尺 |
| `GET /api/gpm-heatmaps/maps/{map_name}/trends?days=14` | 地图整体平均趋势 |
| `GET /api/gpm-heatmaps/points/{point_id}` | 点位完整详情 |
| `GET /api/gpm-heatmaps/points/{point_id}/trends?days=14` | 稳定点位趋势 |
| `GET /api/gpm-heatmaps/configuration` | 地图、标尺集和标尺目录 |
| `GET /api/gpm-heatmaps/configuration/export?scope=all\|maps\|scales` | 按范围导出可读 ZIP 配置包 |
| `POST /api/gpm-heatmaps/configuration/imports/inspect` | 只读检查并暂存候选配置包 |
| `POST /api/gpm-heatmaps/configuration/imports/{import_id}/apply` | 原子安全合并已检查的配置包 |
| `PUT /api/gpm-heatmaps/configuration/maps/{map_name}` | 原子保存完整地图配置 |
| `DELETE /api/gpm-heatmaps/configuration/maps/{map_name}?expected_revision=...` | 删除地图图片、坐标配置和绑定，保留历史上报数据 |
| `GET /api/gpm-heatmaps/configuration/maps/{map_name}/preview` | 最近点位坐标预览 |
| `POST/PUT/DELETE /api/gpm-heatmaps/configuration/scales[/{id}]` | 指标标尺命令 |
| `POST/PUT/DELETE /api/gpm-heatmaps/configuration/scale-sets[/{id}]` | 指标标尺集命令 |
| `GET /gpm-assets/{asset_path}` | 读取地图、原图和缩略图 |

所有旧上报、旧项目清单导入、旧地图、旧标尺和兼容重定向接口均已删除。新的配置包接口只承载当前最终 schema 的配置迁移，不兼容旧 Demo 包。前端快速切换作用域时会取消过期请求；地图编辑仍只调用最终原子地图保存命令。
