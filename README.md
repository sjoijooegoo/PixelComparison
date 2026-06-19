# PixelComparison — 游戏截图对比平台

前后端分离的视觉回归对比工具:采集模块上报批次截图,平台对**同一场景(UE Level)** 的任意两个批次做像素级对比。

📖 完整使用文档见 [docs/使用文档.md](docs/使用文档.md)(界面操作、采集接入、指标含义、API 一览)

- **backend/** — FastAPI + SQLite + Pillow/numpy 对比引擎(差异率、SSIM、PSNR、热力图、RGB 直方图;算法阈值可在「项目设置」里配置)
- **frontend/** — Vue 3 + Vite + Pinia + Arco Design Vue

## 快速开始

### 1. 后端

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app.seed        # 生成演示截图并真实跑一遍对比入库
.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
```

API 文档:http://127.0.0.1:8000/docs

### 2. 前端

```powershell
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 (dev server 已配置代理,`/api` 与 `/images` 转发到 8000 端口)。

## 日志

- 开发可用 `.\run-dev.ps1` 一键开**两个控制台**(后端 / 前端),实时看日志。
- 后端请求(`→/←` + 耗时)与关键业务事件(建/删批次、发起对比、对比完成/失败、自动对比)用中文 INFO 打印,并写入 `backend/data/logs/backend.log`(滚动 5MB×5)。
- 前端 console / 报错经 `POST /api/client-logs` 落到 `backend/data/logs/frontend.log`,便于事后排查。

## 三个界面(各自独立 URL)

路由:`/batches`(批次管理)、`/comparison`(对比结果)、`/settings`(项目设置);
`/batches/<场景ID>` 可直达该场景的「列表图」,链接可分享。

- **批次管理** — 顶部横向筛选条(**场景ID**〔可输入搜索〕/ **画质** / **创建时间**〔默认近七天〕)+ 批次列表,两种视图:
  - **列表** — 批次表格;选「基线批次」「对比批次」(须同场景ID)后「发起对比」(**异步执行 + 前端轮询进度**,完成跳到对比结果页)。
  - **列表图** — 选定场景后,把该场景所有批次排成图片矩阵(列=批次按时间新→旧、可临时折叠,行=检查点),一屏对比多版本的同一张图;点图放大可在同一检查点的各批次间左右翻看。也能在表头直接选基线/对比并发起对比。
  - 顶栏图标:**刷新**、**手动上报**(网页直接拖入 `PixelComparison` 数据包文件夹上报,无需脚本)。
- **对比结果** — 顶部对比对(下拉切换历史,**最多保留 25 条**,超出淘汰最旧)+ 检查点列表(按可用高度动态分页)+ 详情区(当前/参照/差异热力图三视图,均可放大;另有滑动对比)+ 右侧指标面板(差异率、SSIM、PSNR、通道差异、RGB 直方图)。同一对批次的结果持久化复用,不重复计算。
- **项目设置** — 配置对比算法参数:像素差异阈值、差异率红/橙着色阈值、热力图模糊半径与灵敏度(对新发起的对比生效)。

## 结构说明

```
backend/app/
  compare.py    # 对比引擎:像素 diff / SSIM / PSNR / 热力图 / 直方图(参数可传入)
  imagegen.py   # 程序化生成演示截图(variant 0=不变 / 2=噪声 / 3=楼体位移)
  models.py     # Batch / Screenshot / Baseline / Comparison / ComparisonItem / Setting
  service.py    # run_comparison(同场景两批次按点位名配对)/ promote_baseline
  settings.py   # 对比算法可配置参数:默认值 + 持久化读写
  seed.py       # 种子:基线批次 -> 晋升基线 -> 新批次 -> 真实跑对比入库
  main.py       # REST API + 静态图片服务
frontend/src/
  router.js     # vue-router(history 模式):/batches /comparison /settings
  store.js      # Pinia:批次/对比/检查点/详情/设置的全部状态与加载逻辑
  views/        # BatchView(批次管理) / ComparisonView(对比结果)
  components/   # TopBar / FilterSidebar / BatchTable / BatchGrid(列表图) /
                # BatchPreview / ManualUpload(手动上报) / ResultSummary /
                # SceneList / DetailView / MetricsPanel / ProjectSettings / Pager
```
> 热力图以 WebP 存储(纯展示派生物,不参与像素对比);截图按上报原样存储(通常为 JPEG)。

## 批次上报与主要接口

```
POST   /api/batches                      # 建批次;scene_id/platform 必填,id/p4_version/shading_quality(画质)可选
POST   /api/batches/{id}/screenshots     # multipart: scene_name + file(+camera/frame_index)
GET    /api/batches/{id}/screenshots     # 该批次截图列表(预览/列表图用)
DELETE /api/batches/{id}                 # 级联删除批次(连带其对比/对比项/基线/图片)
DELETE /api/batches?created_before=<日期> # 批量删除该日期之前的批次(级联)
POST   /api/batches/{id}/auto-compare    # 与"同场景+同平台+同画质"的最新历史批次自动对比
POST   /api/comparisons                  # 发起对比 {batch_id, ref_batch_id, force?}(异步:返回 task_id)
GET    /api/comparisons/tasks/{task_id}  # 轮询对比进度/结果
GET    /api/scenes/{scene_id}/grid       # 列表图矩阵(同场景多批次)
GET/PUT /api/settings                    # 读取 / 更新对比算法配置
```

- 批次由 CI / 游戏端采集模块上报;`id` 省略时后端按**已有数字批次号自增**生成,`pipeline_data` 整体可省略。
- 平台侧选两个**同场景ID**的批次发起对比(**可跨平台**);对比**异步执行**,前端轮询 `tasks/{task_id}` 获取进度,完成后持久化复用,`force=true` 强制重算。
- 未带 `p4_version` 也能上报(前端显示「——」);`shading_quality`(0–5)对应 节能/流畅/均衡/精美/极致/电影,缺省按「极致」。

上报方式:① 网页「手动上报」拖入数据包文件夹;② 脚本 [`report.py`](report.py)(`python report.py <目录> --host <ip> --port <port>`);
数据包格式/示例见 [mock_uploads/](mock_uploads/README.md),接入细节见 [docs/上报接入指南.md](docs/上报接入指南.md)。

## 数据模型

- **批次(Batch)** 一次截图采集运行,带 **场景ID**(`scene_id`,UE Level)、**P4 版本**(`p4_version`,changelist,越大越新)、平台;产出一组 **点位截图(Screenshot)**。
- **基线(Baseline)** 把某个被认可的批次晋升为基线版本(按场景 + 平台隔离,同版本旧基线自动退役)。
- **对比(Comparison)** 同一场景ID的两个批次互比(可跨平台);同一批次可对比多个参照批次,结果持久化。
- **对比项(ComparisonItem)** 按 **点位名** 配对的单点位结果;两边都有 -> pass/warn/fail(阈值可配),
  仅当前有 -> `added`(新增点位),仅参照有 -> `missing`(点位缺失)。

> 术语:**场景ID** 指批次所属的 UE Level(同场景才能对比);**点位** 指批次内的单张截图/机位。

## 生产化方向

- SQLite → PostgreSQL;本地图片目录 → MinIO/S3(表中只存对象 key,前端走预签名 URL)
- 同步对比 → Celery + Redis 异步任务队列,WebSocket 推送批次进度
- `compare.py` 的全局 SSIM → `skimage.metrics.structural_similarity`(windowed),或 OpenCV 加速;对齐后再比以抗平移
- 基线版本管理、用户体系与权限
