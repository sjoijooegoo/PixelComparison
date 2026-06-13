# PixelComparison — 游戏截图对比平台

前后端分离的视觉回归对比工具:采集模块上报批次截图,平台对任意两个批次做像素级对比。

📖 **完整使用文档见 [docs/使用文档.md](docs/使用文档.md)**(界面操作、采集接入、指标含义、API 一览)

- **backend/** — FastAPI + SQLite + Pillow/numpy 对比引擎(差异率、SSIM、PSNR、热力图、RGB 直方图)
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

## 结构说明

```
backend/app/
  compare.py    # 对比引擎:像素 diff / SSIM / PSNR / 热力图 / 直方图
  imagegen.py   # 程序化生成演示截图(variant 0=不变 1=楼体位移 2=噪声)
  models.py     # Batch / Screenshot / Baseline / Comparison / ComparisonItem
  service.py    # run_comparison(批次×基线按场景名配对)/ promote_baseline / 状态阈值
  seed.py       # 种子:基线批次 -> 晋升基线 -> 新批次 -> 真实跑对比入库
  main.py       # REST API(comparison 维度)+ 静态图片服务
frontend/src/
  store.js      # Pinia:对比/场景/详情的全部状态与加载逻辑
  components/   # TopBar / FilterSidebar / BatchTable / SceneList / DetailView / MetricsPanel
```

## 批次上报(供采集模块调用)

```
POST /api/batches                        # {project, branch, platform, creator, id?}
POST /api/batches/{id}/screenshots       # multipart: scene_name + file(PNG)
POST /api/comparisons                    # {batch_id, ref_batch_id} 发起对比(同步执行)
```

批次由 CI / 游戏端采集模块上报,平台侧用户通过「发起对比」选择两个批次
(同项目同平台,已晋升基线的批次优先展示)发起对比。

上报数据包的格式、示例与生成/上报脚本见 [mock_uploads/](mock_uploads/README.md)
(每批 = `manifest.json` + `images/` 目录,内置两批可互比的示例数据)。

## 数据模型

- **批次(Batch)** 一次截图采集运行,产出一组 **截图(Screenshot)**
- **基线(Baseline)** 把某个被认可的批次晋升为基线版本(按项目 + 平台隔离,同版本旧基线自动退役)
- **对比(Comparison)** 批次 × 基线;同一批次可对比多个基线
- **对比项(ComparisonItem)** 按场景名配对的单场景结果;
  两边都有 -> pass/warn/fail,仅当前有 -> `added`(新增场景),仅基线有 -> `missing`(场景缺失)

## 生产化方向

- SQLite → PostgreSQL;本地图片目录 → MinIO/S3(表中只存对象 key,前端走预签名 URL)
- 同步对比 → Celery + Redis 异步任务队列,WebSocket 推送批次进度
- `compare.py` 的全局 SSIM → `skimage.metrics.structural_similarity`(windowed),或 OpenCV 加速
- 新增上传接口(游戏端/CI 推送截图触发新批次)、基线版本管理、用户体系
