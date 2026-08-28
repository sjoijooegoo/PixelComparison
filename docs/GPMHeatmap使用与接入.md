# GPMHeatmap 使用与接入

GPMHeatmap 是与截图批次、截图对比和烘培数据相互隔离的点位热力模块。它使用独立 SQLite、独立文件目录和独立 API；相同的 `batch_id` 可以分别存在于截图批次与 GPMHeatmap 中，删除任一模块的数据不会连带删除另一模块。

## 1. 页面

打开 `/gpm-heatmap`，或用 `/gpm-heatmap/<场景ID>` 直接进入指定场景。右上角“批次管理”图标进入 `/batch-management/gpm`；该目录与截图/烘培批次完全独立。页面按以下顺序筛选：

1. 平台；
2. 场景 ID；
3. 画质；
4. 采集批次（显示为 `P4 <版本> · <采集时间>`）。

首屏左侧是地图与热力点，右侧是当前点位的 `detail_data` 列表，下方是横向点位截图。点击地图方块或截图会同步点位、详情和地址栏。地图点位使用纯色方块，短箭头表示采集方向。

数据趋势默认使用“整体平均”和最近 14 天，可切换为 7、14、30 天。整体平均直接读取每次场景上报的趋势汇总；切换到“单个点位”时，只有上报数据提供稳定 `point_key`（也接受 `teleport_point_id`）才会跨批次关联同一物理点位。缺少稳定键时只保留当前批次值，不用易变化的数组序号拼接历史数据，也不额外打断用户操作。

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
| `report` | 是 | `GPMHeatmap.json`；每个场景携带 `p4_version`、`platform`、`shading_quality`，并可携带 `map_name` |
| `screenshots` | 是 | `GPMScreenshot.zip` |
| `pipeline_data` | 是 | JSON 对象，见下方结构 |
| `overwrite` | 否 | 默认 `false`；同批次覆盖时必须显式为 `true` |

`pipeline_data` 的规范结构如下。`batch_id` 和 `captured_at` 必填，`branch_tag` 缺省为 `main`，`batch_url` 可省略：

```json
{
  "batch_id": "gpm-demo-20260826",
  "batch_url": "https://example/pipeline/gpm-demo-20260826",
  "captured_at": "2026-08-26T15:00:00+08:00",
  "branch_tag": "main"
}
```

`batch_id` 在 GPMHeatmap 数据域内跨分支全局唯一；覆盖不能把已有批次移动到其他分支。同一报告内每个场景必须同时携带且保持一致的 `platform`、`shading_quality` 和 `p4_version`，`shading_quality` 范围为 0～5。`map_name` 是独立地图配置的匹配键；省略时兼容回退为 `pic_name`。地图尚未配置不会阻止上报，后续上传同名地图后，当前批次和历史批次都会动态使用最新激活版本。为兼容已经接入的旧调用，后端暂时仍接受“所有场景都不携带这三个字段、统一由同名顶层表单字段补充”的早期格式；部分场景携带、部分场景缺失，以及两套入口值冲突，都会使整次上报失败。

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

## 4. 导入地图清单和上传地图图片

推荐从热力图右上角进入“热力图设置”，导入项目生成的 `DataForInstance.json`。后端读取根对象中的 `GpmConfig`，以 `pic_name` 作为 `map_name`，并使用 `start_pos` 和 `map_size` 作为左下角起点与 X/Y 坐标范围。地图名称和地图 ID 在同一份配置中都必须唯一，范围必须为正数。导入是一次事务性的权威清单替换；校验失败不会改变当前配置。每次导入的原始 JSON、文件哈希、文件名和导入时间都会保存在 `gpm_config_imports`，当前地图定义保存在 `gpm_map_definitions`。

| 接口 | 请求 | 用途 |
|---|---|---|
| `GET /api/gpm-heatmaps/project-config` | — | 读取当前地图清单、图片版本和匹配摘要 |
| `POST /api/gpm-heatmaps/project-config/import` | multipart 字段 `config` | 导入 JSON，最大 4 MiB、最多 5000 张地图 |
| `POST /api/gpm-heatmaps/project-config/maps/{map_name}/image` | multipart 字段 `image` | 给当前清单中的地图上传 PNG/JPEG/WebP，最大 32 MiB |
| `GET /api/gpm-heatmaps/project-config/maps/{map_name}/preview` | — | 读取最近一次同名地图上报的点位，供坐标预览 |

图片每次上传都会创建新版本并自动激活，旧版本和文件保留。重新导入清单会停用被移除的地图定义，但不会删除它的图片；以后重新加入同名 `map_name` 时会自动复用已有激活图片。运行时若已经导入过项目清单，地图必须同时满足“定义仍有效”和“已有激活图片”；尚未导入清单的旧环境继续兼容原有 `POST /api/gpm-heatmaps/maps/{map_name}` 表单接口。

设置页把图片拉伸到完整坐标范围并叠加最近点位，同时用图片原始宽高比轮廓辅助检查。地图清单只区分“未上传”和“已上传”，不生成需要人工处理的确认状态；底部单行显示坐标起点、坐标范围、图片尺寸和最近点位。实际热力图仍按 X/Y 各自的坐标范围映射。

“颜色标尺”页在同一工作区以三栏表格提供三个配置层级：左侧指标标尺库维护不绑定具体指标的命名分段标尺；中间指标标尺集维护用户手工定义的“上报 Key → 指标标尺”映射；右侧地图应用列出全部地图和配置状态。点击地图的“配置”后，可以按“平台多选 × 画质多选 → 指标标尺集”新增一个或多个配置项，保存时展开为具体作用域；同一平台和画质不能重复配置。配置页不从历史上报提取或推荐 Key。同一标尺可以被标尺集中的不同 Key 复用，同一标尺集也可以被多个地图作用域复用。指标标尺以 2–10 个“颜色 + 区间表达式”定义分段，支持 `<`、`<=`、`>`、`>=` 以及连接上下界的 `&`，例如 `<365`、`>=365 & <390`、`>=390`。保存前会校验语法、空区间、区间重叠和断档，所有分段必须无缝覆盖完整数轴。

运行时先按 `map_name + platform + shading_quality` 选择指标标尺集，再用上报数据中的原始指标 Key 作大小写敏感的精确匹配。例如标尺集配置了 `Character_DC`，只有当前上报同时包含 `Character_DC` 时才使用对应分段标尺。系统不预设角色 DC、场景面数或全部 DC 等固定指标，也不提供地图局部覆盖。作用域没有关联标尺集或 Key 没有命中时，按当前批次该指标最小值到最大值作动态绿色→红色线性映射；动态颜色只代表批次内相对高低，不表示是否符合预期。

| 标尺配置接口 | 用途 |
|---|---|
| `GET /api/gpm-heatmaps/project-config/scales` | 指标标尺、指标标尺集、地图作用域绑定与默认五色调色板 |
| `POST/PUT/DELETE /api/gpm-heatmaps/project-config/metric-scales[/{id}]` | 创建、修改或删除可复用指标标尺 |
| `POST/PUT/DELETE /api/gpm-heatmaps/project-config/metric-scale-sets[/{id}]` | 创建、修改或删除“上报 Key → 指标标尺”集合 |
| `PUT /api/gpm-heatmaps/project-config/maps/{map_name}/scale-bindings` | 原子替换地图的平台、画质作用域与指标标尺集绑定 |

## 5. 主要读取接口

| 接口 | 用途 |
|---|---|
| `GET /api/gpm-heatmaps/meta` | 平台、画质、场景筛选项 |
| `GET /api/gpm-heatmaps/uploads/meta` | GPM 批次管理的分支、平台、场景和画质选项 |
| `GET /api/gpm-heatmaps/uploads` | 按分支、平台、场景、画质和采集日期分页查询完整上报 |
| `GET /api/gpm-heatmaps/project-config` | 当前地图清单、图片状态和比例检查结果 |
| `GET /api/gpm-heatmaps/project-config/scales` | 标尺配置目录与复用关系 |
| `GET /api/gpm-heatmaps/scenes/{scene_id}/frame` | 地图配置、热力指标、批次列表和紧凑点位数据 |
| `GET /api/gpm-heatmaps/scenes/{scene_id}/trends?days=14` | 当前场景的整体平均趋势 |
| `GET /api/gpm-heatmaps/points/{point_id}` | 单点完整 `detail_data` 与原图 |
| `GET /api/gpm-heatmaps/points/{point_id}/trends?days=14` | 单点跨批次趋势；范围仅支持 7、14、30 天 |
| `DELETE /api/gpm-heatmaps/uploads/{batch_id}?branch_tag=main` | 删除 GPM 批次下全部场景、点位、指标和截图；不删除地图配置 |

列表接口只返回点位热字段和缩略图；体积较大的 `detail_data` 在用户选中点位后单独加载。快速切换场景、批次和点位时，前端会取消旧请求并通过请求序号阻止过期响应覆盖当前状态。删除操作先提交独立数据库，再清理该批次资源；极端文件系统故障只可能留下不可达的孤儿文件，不会让仍可查询的记录失去图片。
