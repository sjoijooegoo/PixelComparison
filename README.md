# PixelComparison

PixelComparison 是面向游戏截图与场景烘培数据的回归平台。采集端按批次上报同一 UE Level 的截图、烘培数据或两者，平台按分支隔离浏览、像素级比较、差异热力图和烘培趋势。

当前项目定位是可信局域网内的小团队工具：单进程 FastAPI 后端、SQLite 元数据、文件系统图片存储，以及 Vue 3 前端。

## 主要能力

- 管理批次及其场景、平台、多个画质运行、P4 版本、采集时间和截图数据；同一批次可一次上报电影、精美、流畅等多档截图。
- 在批次管理表格中维护全部批次，并在独立“截图对比”工作区浏览同一场景的多个版本。
- 任意选择两个同场景批次进行异步比较，并复用已有结果。
- 输出差异率、SSIM、PSNR、通道差异、RGB 直方图和 WebP 热力图。
- 识别新增、缺失、通过、警告和失败检查点。
- 支持浏览器拖入数据包手动上报，以及 HTTP API 接入 CI/采集端。
- 支持外部模块全量同步前端场景目录，统一控制场景筛选项的顺序和可见性。
- 接收批次随附的 `map_build_data`，以分块热力网格和跨批次折线展示烘培体积回归。
- 使用 `pipeline_data.branch_tag` 隔离 `main`、`engine-ue5` 等分支；旧数据与缺省上报自动归入 `main`。
- 支持不带截图的纯烘培批次；批次列表展示数据能力，截图对比只使用确有截图的批次。
- 自动生成缩略图并按访问时间淘汰缓存；批次画廊先显示缩略图，点击后才加载原图。
- 每天在线备份 SQLite 数据库，默认保留 30 天。

## 文档导航

- [完整使用文档](docs/使用文档.md)：安装、启动、界面操作、项目设置、数据目录、备份恢复和故障排查。
- [数据上报接入指南](docs/上报接入指南.md)：manifest 格式、接口字段、异步对比和错误处理。
- [示例数据包说明](mock_uploads/README.md)：生成和上传演示批次。
- [测试与维护脚本](scripts/README.md)：单元测试、构建、清理和可选浏览器脚本。
- [后续工作](TODO.md)：当前明确保留的技术和产品待办。

## 技术栈

| 层 | 实现 |
|---|---|
| 前端 | Vue 3、Vite、Pinia、Arco Design Vue |
| 后端 | FastAPI、SQLAlchemy 2、Uvicorn |
| 数据库 | SQLite，WAL 模式 |
| 图片处理 | Pillow、NumPy |
| 测试 | pytest、Vitest；另有可选 Playwright 脚本 |

## 快速开始

### 环境要求

- Python 3.10 或更高版本，建议 3.11。
- Node.js 20 或更高版本。
- Windows PowerShell；Linux/macOS 也可分别启动前后端。

### 首次安装

后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
cd ..
```

前端：

```powershell
cd frontend
npm ci
cd ..
```

`requirements-dev.txt` 包含运行依赖和 pytest。仅部署后端时也可以安装 `requirements.txt`。

### Windows 一键开发启动

```powershell
.\run-dev.ps1
```

默认启动：

- 前端：http://127.0.0.1:5173
- 后端：http://127.0.0.1:8020
- API 文档：http://127.0.0.1:8020/docs
- 数据目录：`<项目目录>\backend\data`

指定数据目录或后端端口：

```powershell
.\run-dev.ps1 -DataDir "D:\PixelComparisonData" -BackendPort 8020
```

启动脚本不会因为存在 `Y:` 等盘符而自动切换数据目录。只有显式传入 `-DataDir` 或设置 `PIXELCOMP_DATA_DIR` 才会改变默认位置。

### 分别启动

终端一：

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

终端二：

```powershell
cd frontend
npm run dev
```

Vite 默认把 `/api`、`/images` 和 `/thumb` 代理到 `http://127.0.0.1:8020`。如需使用其他后端地址：

```powershell
$env:PIXELCOMP_BACKEND_URL = "http://127.0.0.1:9000"
npm run dev
```

### 生产式单端口启动

Windows：

```powershell
.\run-prod.ps1
```

脚本先执行前端构建，再由 FastAPI 在 `8800` 端口同时提供页面、API 和图片。生产模式必须使用单 worker，因为对比任务进度保存在进程内存中。

Linux 示例：

```bash
cd frontend
npm ci
npm run build

cd ../backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PIXELCOMP_DATA_DIR=/data/pixelcomparison
python -m uvicorn app.main:app --host 0.0.0.0 --port 8800
```

## 数据目录与配置

未设置环境变量时，路径均相对当前仓库动态计算，不写死盘符：

```text
backend/data/
  shotdiff.db
  images/
    batches/
    heatmaps/
  thumbs/
  backup/
    YYYY-MM-DD/
      db/
        shotdiff.db
  logs/
```

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `PIXELCOMP_DATA_DIR` | `<项目目录>/backend/data` | 日志、备份及默认数据库/图片根目录 |
| `PIXELCOMP_DB_PATH` | `<DATA_DIR>/shotdiff.db` | SQLite 文件；应放本地磁盘 |
| `PIXELCOMP_IMAGES_DIR` | `<DATA_DIR>/images` | 原图和热力图，可单独放大容量磁盘或共享盘 |
| `PIXELCOMP_THUMB_DIR` | `<PIXELCOMP_DB_PATH 所在目录>/thumbs` | 可重建的 WebP 缩略图缓存；建议放本地磁盘 |
| `PIXELCOMP_THUMB_WORKERS` | `2` | 后台生成缩略图的守护线程数，范围 1～8 |
| `PIXELCOMP_THUMB_QUEUE_SIZE` | `64` | 等待生成的缩略图任务上限；队列满时不阻塞请求 |
| `PIXELCOMP_MAX_SCREENSHOT_BYTES` | `104857600` | 单张截图上传上限（字节），默认 100 MiB |
| `PIXELCOMP_COMPARE_WORKERS` | `2` | 后台图片对比工作线程数，范围 1～4 |
| `PIXELCOMP_COMPARE_WORKERS_QUEUE` | `COMPARE_WORKERS × 8` | 等待执行的对比任务上限，范围为工作线程数～128 |
| `PIXELCOMP_BACKUP_ENABLED` | `1` | 设为 `0`、`false`、`no` 或 `off` 时禁用自动备份 |
| `PIXELCOMP_BACKUP_RETENTION_DAYS` | `30` | 数据库备份保留天数；`0` 表示永久保留 |
| `PIXELCOMP_BACKUP_CHECK_INTERVAL_SECONDS` | `3600` | 自动备份检查间隔，最小 60 秒 |

不要把正在写入的 SQLite 主库放在 SMB/NFS 网络共享目录。若需要共享存储，建议只把 `PIXELCOMP_IMAGES_DIR` 指向共享盘，数据库和 `PIXELCOMP_THUMB_DIR` 仍保留在本地磁盘。截图上报成功后会立即把缩略图预热任务放入有界守护线程，但不会等待编码完成；历史图片或队列遗漏的缓存未命中请求仍会立即回退原图并异步补生成。后台线程不会阻止 Uvicorn 退出。批次和截图网格 API 使用数据库缓存版本生成图片 URL，不会为了组装响应逐张访问远程原图；用户真正打开原图或后台生成缩略图时仍受共享存储速度影响。

Linux 上将数据库和缩略图放本地、原图等大文件放远端的完整示例：

```bash
export PIXELCOMP_DATA_DIR=/agentdrive/v_sycisong/PixelComparison
export PIXELCOMP_DB_PATH=/data/workspace/PixelComparison/backend/data/shotdiff.db
export PIXELCOMP_IMAGES_DIR=/agentdrive/v_sycisong/PixelComparison/images
export PIXELCOMP_THUMB_DIR=/data/workspace/PixelComparison/backend/data/thumbs

mkdir -p "$(dirname "$PIXELCOMP_DB_PATH")" "$PIXELCOMP_IMAGES_DIR" "$PIXELCOMP_THUMB_DIR"

cd /data/workspace/PixelComparison/backend
python -c "from app.db import DATA_DIR, DB_PATH, IMAGES_DIR, THUMB_DIR; print('DATA_DIR =', DATA_DIR); print('DB_PATH =', DB_PATH); print('IMAGES_DIR =', IMAGES_DIR); print('THUMB_DIR =', THUMB_DIR)"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8020
```

`echo "$PIXELCOMP_THUMB_DIR"` 为空只表示没有显式设置；此时实际默认值仍是 `PIXELCOMP_DB_PATH` 所在目录下的 `thumbs`。完整的 Linux 更新、持久化环境变量、端口排查和缩略图维护命令见[使用文档](docs/使用文档.md#14-linux-部署与更新)。

## 每日数据库备份

后端启动时会检查当天是否已有备份，之后按检查间隔重复检查。当天没有快照时，使用 SQLite 在线备份 API 创建：

```text
backend/data/backup/YYYY-MM-DD/db/shotdiff.db
```

备份先写入唯一临时文件，通过 `PRAGMA quick_check` 后再原子发布；运行中的 WAL 数据也会进入一致快照。同一自然日只保留一个日快照。如果通过 `PIXELCOMP_DB_PATH` 使用自定义数据库文件名，日快照会在当天的 `db/` 目录中保留该文件名。

自动备份只包含 SQLite 数据库，不包含 `PIXELCOMP_IMAGES_DIR` 中的原始截图、热力图，也不包含 `PIXELCOMP_THUMB_DIR` 中的缩略图。数据库只保存图片的相对路径；完整恢复时必须同时保留与快照匹配的 `images/batches` 原图。`images/heatmaps` 可以备份以便立即查看历史对比，`thumbs` 是可重建缓存，无需备份。

校验快照时应使用 SQLite URI `mode=ro&immutable=1`，避免校验过程创建 `-wal`、`-shm` 等辅助文件。日期目录是保留和删除的完整单元，不要在其中存放人工维护的无关文件；若其他工具产生辅助文件，它们也只会位于对应日期的 `db/` 目录内。

默认备份和主库位于同一数据目录，可以防误删和数据库逻辑损坏，但不能防整块磁盘故障。需要灾备时，应把完整的 `backup/` 目录树和原始图片增量备份同步到异盘或对象存储。恢复时先停止后端，再把选定日期的 `db/shotdiff.db` 复制到活动数据库路径，并配合对应的图片目录使用；详细步骤见[使用文档](docs/使用文档.md#10-数据库备份与恢复)。

## 界面入口

| 路径 | 功能 |
|---|---|
| `/batches?branch_tag=main&quality=all&date_mode=range&from=2026-08-14&to=2026-08-20` | 筛选、预览和维护全部批次；场景可用 `scene_id`、分页可用 `page` 恢复 |
| `/screenshot?branch_tag=main` | 打开截图对比空工作区，等待选择场景 |
| `/screenshot/:sceneId?branch_tag=main&quality=4&date_mode=range&from=2026-08-06&to=2026-08-19` | 打开指定场景并恢复画质与日期筛选；可追加 `baseline`、`current` 恢复对比角色 |
| `/batches/:sceneId` | 兼容旧链接，自动重定向到 `/screenshot/:sceneId` |
| `/map-build?branch_tag=main` | 所选分支的烘培数据分块网格、选中项细则和按天历史趋势 |
| `/settings` | 对比算法与默认筛选设置 |

批次管理的分支、场景、画质、日期和页码会同步到 URL；无参数 `/batches` 默认使用 `main`、全部场景、全部画质和项目默认日期范围。截图对比按照“左旧右新”排列批次，其场景、画质和日期筛选也会同步到 URL；指定日期使用 `date_mode=days&dates=2026-08-01,2026-08-03`。选择基线和对比批次后，已有结果会直接显示热力图；没有缓存时可在当前工作区发起计算，不会跳页。旧 `/comparison` 地址不再提供历史或详情页面，会返回批次管理；对比记录及热力图仍在后端保留 14 天，重新选择同一批次对即可恢复。

## 比较规则

- 两个批次必须具有相同 `branch_tag`、相同 `scene_id` 和相同 `shading_quality`，且该画质在两侧都已完整上传；平台可以不同。
- 批次内的 `scene_name` 是检查点唯一键，两个版本按该字段配对。
- 两侧都有截图时计算像素差异；只有当前侧时为 `added`，只有参照侧时为 `missing`。
- 任一 `fail` 或 `missing` 使整体状态为失败；否则任一 `warn` 或 `added` 使整体状态为警告；其余为通过。
- 同一批次对忽略方向只保存一条结果，前端可以交换显示方向。
- 对比记录默认保留 14 天；过期记录在后续对比创建或完成时淘汰。

默认阈值：

| 参数 | 默认值 |
|---|---:|
| 像素通道差阈值 | 8 |
| 警告差异率 | 0.3% |
| 失败差异率 | 2.0% |
| 热力图方法 | `enhanced` |

全部算法参数可在项目设置页修改，新设置只影响之后发起或重新计算的对比。

## 上报方式

当前支持：

1. 前端顶栏“手动上报”，拖入包含 `manifest.json`，以及截图、烘培数据或两者的目录。
2. 直接调用批次、截图、`map-build-data` 和自动对比 API。
3. 使用 `mock_uploads/upload.py` 上传仓库内演示数据。

推荐使用 `format_version: 2` 的 manifest：顶层 `quality_runs` 为每个画质声明唯一的 `quality_run_index`、`shading_quality`、仅作采集参数保存的 `tex_quality`、`status: "complete"` 和完整截图计划。后端先在一个事务中创建批次、画质运行与所有待上传槽位，再通过带画质的截图接口写入；截图网格把一个批次的每档完整画质展开成独立列，对比不会跨画质。旧单画质 manifest 和旧截图接口继续兼容。

同名批次默认返回 `409 BATCH_ALREADY_EXISTS`，不会合并或补传；只有显式使用上报脚本的 `--overwrite`（或浏览器勾选“覆盖”）才会整批替换。详细 v2 示例、幂等规则和错误码见[上报接入指南](docs/上报接入指南.md)。

分支写在 manifest 的 `pipeline_data` 中：

```json
{
  "pipeline_data": {
    "id": "engine-ue5-20260818-001",
    "branch_tag": "engine-ue5"
  }
}
```

`branch_tag` 省略时为 `main`。批次 ID 在所有分支间仍必须全局唯一；已有批次不能通过覆盖改到另一分支。

仓库当前不提供独立的根目录 `report.py` 客户端。生产采集端请依据[上报接入指南](docs/上报接入指南.md)实现 API 调用，或从 `mock_uploads/upload.py` 提取参考逻辑。

外部模块可通过幂等接口全量替换场景筛选目录；列表中的未知场景也会显示，数据库中存在但未列出的场景默认隐藏：

```bash
curl -X PUT http://127.0.0.1:8020/api/scene-catalog \
  -H 'Content-Type: application/json' \
  -d '{"scene_id_order":["Village_Dimension_Main","RottenVale_WP","OtherScene"]}'
```

项目设置中的“目录外场景”开关可以临时把未列入目录但已有批次的场景追加到下拉框。详细语义见[上报接入指南](docs/上报接入指南.md#12-同步前端场景目录)。

仓库还提供了零第三方依赖的上报脚本，默认目标是 `http://21.130.229.92:5173/api/scene-catalog`；不传 JSON 文件或使用 `--help` 会展示完整数据格式：

```powershell
python scripts\report_scene_catalog.py .\scene-catalog.json --dry-run
python scripts\report_scene_catalog.py .\scene-catalog.json
```

脚本参数、格式约束和自定义接口地址见[脚本说明](scripts/README.md#4-上报前端场景目录)。

## 测试

后端完整测试：

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
```

前端单元测试和构建：

```powershell
cd frontend
npm test
npm run build
```

测试不应指向生产数据目录。pytest fixture 会为每个用例创建独立临时数据库，并禁用自动备份。

## 常用维护命令

只检查孤儿截图、热力图和缩略图：

```powershell
cd backend
.\.venv\Scripts\python -m app.cleanup --dry-run
```

执行清理：

```powershell
.\.venv\Scripts\python -m app.cleanup
```

按日期批量删除批次前，先使用维护脚本的预览模式：

```powershell
python scripts\cleanup_batches.py --before 2026-06-01
python scripts\cleanup_batches.py --before 2026-06-01 --yes
```

## 架构概览

```text
采集端 / 浏览器
       │
       ▼
FastAPI API ── SQLAlchemy ── SQLite
       │
       ├── 文件系统：原图 / 缩略图 / 热力图
       ├── Pillow + NumPy 比较线程
       └── SQLite 在线日备份
       │
       ▼
Vue 3 + Pinia + Arco Design
```

关键文件：

| 文件 | 职责 |
|---|---|
| `backend/app/main.py` | API、静态文件、任务编排和前端构建产物托管 |
| `backend/app/compare.py` | 差异率、SSIM、PSNR、直方图和热力图 |
| `backend/app/service.py` | 检查点配对与对比结果生成 |
| `backend/app/backup.py` | SQLite 每日在线备份和保留策略 |
| `backend/app/models.py` | SQLAlchemy 数据模型 |
| `frontend/src/stores/projectStore.js` | 项目设置、场景目录和上报弹窗状态 |
| `frontend/src/stores/batchCatalogStore.js` | 批次管理筛选、分页和目录请求 |
| `frontend/src/stores/screenshotComparisonStore.js` | 截图网格、URL 角色、热力图和对比轮询 |
| `frontend/src/components/BatchGrid.vue` | 截图对比的多批次二维网格 |

## 当前边界

- 没有登录、权限和租户隔离，只适合可信内网。
- 对比任务和进度在单进程内存中，服务重启会中断正在执行的任务。
- SQLite 适合当前小团队规模；更大并发应迁移 PostgreSQL 和独立任务队列。
- 当前 SSIM 是全局简化算法，不是滑窗 SSIM。
- 截图网格尚未实现二维虚拟化，大规模行列会产生较多 DOM 和图片请求。
