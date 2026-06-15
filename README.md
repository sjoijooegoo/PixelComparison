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

## 三个界面

- **批次管理** — 筛选条件(场景ID / 平台 / P4 版本范围 / 创建时间)+ 批次列表;选「对比批次」与「基线批次」(须同场景ID)后「发起对比」,自动跳到对比结果页。
- **对比结果** — 顶部对比对(可下拉切换历史对比)+ 点位列表(按可用高度动态分页)+ 详情区(当前/参照两张小图 + 差异热力图大图,均可点击看大图;另有滑动对比)+ 右侧指标面板(差异率、SSIM、PSNR、通道差异、RGB 直方图)。同一对批次的结果会持久化复用,不重复计算。
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
  store.js      # Pinia:批次/对比/点位/详情/设置的全部状态与加载逻辑
  components/   # TopBar / FilterSidebar / BatchTable / ResultSummary /
                # SceneList / DetailView / MetricsPanel / ProjectSettings / Pager
```

## 批次上报(供采集模块调用)

```
POST /api/batches                        # {scene_id, p4_version, platform, creator, id?}
POST /api/batches/{id}/screenshots       # multipart: scene_name + file(PNG)
POST /api/comparisons                    # {batch_id, ref_batch_id, force?} 发起对比(同步执行)
GET/PUT /api/settings                    # 读取 / 更新对比算法配置
```

批次由 CI / 游戏端采集模块上报,平台侧用户通过「发起对比」选择两个**同场景ID**的批次发起对比
(可跨平台);同一对批次已对比过则直接复用结果,`force=true` 可强制重算。

上报数据包的格式、示例与生成/上报脚本见 [mock_uploads/](mock_uploads/README.md)
(每批 = `manifest.json` + `images/` 目录,内置 7 批可互比的示例数据)。

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
