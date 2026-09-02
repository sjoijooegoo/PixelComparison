# 测试与维护脚本

本目录包含数据清理、浏览器交互验证和并发界面冒烟脚本。日常回归应优先运行仓库内的 pytest 和 Vitest；浏览器脚本依赖运行中的服务和已有数据。

## 1. 标准验证命令

后端：

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
```

前端：

```powershell
cd frontend
npm test
npm run build
```

这些命令不需要连接正在运行的业务数据库。后端测试使用临时 SQLite 库，并禁用自动备份。

## 2. 按日期清理批次

脚本：`scripts/cleanup_batches.py`

默认后端是 `http://127.0.0.1:8020`。

预览将删除的批次：

```powershell
python scripts\cleanup_batches.py --before 2026-06-01
```

确认执行：

```powershell
python scripts\cleanup_batches.py --before 2026-06-01 --yes
```

远程后端：

```powershell
python scripts\cleanup_batches.py --before 2026-06-01 --base http://10.30.129.32:8020 --yes
```

删除条件是 `created_at < 指定日期`，不包含当天。执行会级联删除批次、截图、相关对比和派生图片，无法撤销。

## 3. 孤儿文件和缩略图清理

该命令位于后端模块中：

```powershell
cd backend
.\.venv\Scripts\python -m app.cleanup --dry-run
.\.venv\Scripts\python -m app.cleanup
```

不要在上传或对比任务运行时执行人工清理。

## 4. 上报前端场景目录

脚本：`scripts/report_scene_catalog.py`

准备 UTF-8 编码的 `scene-catalog.json`：

```json
{
  "scene_id_order": [
    "Village_Dimension_Main",
    "RottenVale_WP",
    "OtherScene"
  ]
}
```

数组顺序就是前端“场景 ID”下拉框顺序。该接口采用全量替换语义：未列入数组的数据库场景默认从下拉框隐藏，但不会删除批次；尚无批次的场景也会显示。

默认上报到 `http://21.130.229.92:5173/api/scene-catalog`：

```powershell
python scripts\report_scene_catalog.py .\scene-catalog.json --dry-run
python scripts\report_scene_catalog.py .\scene-catalog.json
```

查看内置格式说明或切换后端：

```powershell
python scripts\report_scene_catalog.py --help
python scripts\report_scene_catalog.py --print-example
python scripts\report_scene_catalog.py .\scene-catalog.json --url http://127.0.0.1:8020/api/scene-catalog
```

也可设置环境变量 `PIXELCOMP_SCENE_CATALOG_URL` 作为默认接口。脚本只依赖 Python 标准库，会在发送前检查空值、首尾空格、重复项、长度和数量，并在成功后核对后端返回顺序。

## 5. 浏览器交互 E2E

脚本：`scripts/e2e/run-all.mjs`

当前脚本从开发机固定位置加载 Playwright：

```text
C:/WorkSpace/jm/node_modules/playwright
```

因此它不是可移植的 CI 入口。运行前需要：

- 后端 8020 和前端 5173 已启动。
- 数据库中至少有一个场景包含两个批次。
- 上述 Playwright 安装存在且浏览器依赖可用。

运行：

```powershell
node scripts/e2e/run-all.mjs
node scripts/e2e/run-all.mjs http://localhost:5173
```

覆盖列表图角色选择、缓存/发起对比、拖拽、大图键盘导航、深链、历史切换、换向和日期筛选。

注意：该脚本在没有缓存时会发起真实对比，写入 Comparison、ComparisonItem 和热力图，并可能触发 14 天历史淘汰。不要直接指向生产数据。

## 6. 多用户界面冒烟

脚本：`scripts/ui-load-smoke.mjs`

```powershell
node scripts/ui-load-smoke.mjs http://localhost:5173 Lv_Starfall 6
```

它创建多个浏览器上下文，反复访问批次列表、列表图和对比页面，输出各页面 p50、p95、最大加载时间以及 console/page 错误。

该脚本本身只浏览页面，但同样依赖固定 Playwright 路径和已有业务数据。自动刷新等页面行为仍会产生 API 读取流量。

## 7. 热力图主界面并发压测

脚本：`scripts/gpm-heatmap-load.mjs`

```powershell
node scripts/gpm-heatmap-load.mjs --base http://127.0.0.1:5173 --users 10 --rounds 25
```

脚本只模拟热力图主界面的读取行为，不进入设置页，也不会上传、删除或修改配置。每个虚拟用户会持续切换已有的平台、地图和画质，读取最新地图帧、点位详情、整体/单点趋势、缩略图和地图图片；同时检查批次范围、点位序号与截图 ID、详情归属、趋势时间顺序以及最新批次是否倒退。

结果会按接口输出请求数、失败数、p50/p95/p99、最大耗时和平均响应体积；任意 HTTP、JSON、图片或数据一致性错误都会令进程以非零状态退出。可选参数包括 `--branch`、`--days`、`--timeout` 和 `--think`。

## 8. 后续工程化建议

- 把 Playwright 放入项目 devDependencies，移除绝对路径。
- 为浏览器测试启动临时数据目录和独立后端，运行后销毁。
- 把 `pytest`、`npm test` 和 `npm run build` 接入 CI。
- E2E 使用确定性的种子数据，不依赖共享业务库当前状态。
