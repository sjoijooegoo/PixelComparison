# 设计: 图片数据分层存储(COS 主存 + 本地热缓存)

> 状态: 方案设计, COS 连通性已验证, 后端存储层尚未实现。

## 1. 当前结论

本项目的图片数据可以迁到 COS。当前已用 `cos_helper` 验证 `arashimain` 桶下的 `/PixelComparison/` 前缀可以上传、下载和生成访问 URL。

已验证样例:

```text
COS 对象: /PixelComparison/_smoke/codex-20260622-180800/README.md
访问 URL: http://arashimain-70674.njc.vod.tencent-cloud.com/PixelComparison/_smoke/codex-20260622-180800/README.md
校验结果: 下载文件 SHA256 与本地 README.md 一致
```

关键事实:

- 当前 `arashimain` 是 **public-read** 桶。`cos_helper url` 返回普通 HTTP 直链, 不会生成临时签名 URL; 出现 `Bucket arashimain is public-read, cannot generate temporily URLs!` 是提示, 不是失败。
- 当前路径前缀固定使用 `/PixelComparison/`, 避免和已有 `MHPerf/PerfHeatmap/`、`StatsDC/GPM/` 等目录混用。
- `scripts/CosConfig.yaml` 属于本机配置, 可能含密钥, 已加入 `.gitignore`, 不应提交。

## 2. 背景与目标

当前所有图片都存在后端本地磁盘 `backend/data/images/`, 随批次累积会持续增长。当前量级约 271MB / 1072 张原图, 平均约 259KB。

目标:

- **COS 只作原图(批次截图)的持久主存**。原图最终必须安全落到 COS。**热力图和缩略图都不上 COS**(理由见 5 / 9.2)。
- **本地只保留热缓存**。批次原图默认保留最近 14 天; 老数据从本地淘汰, 需要展示或对比时按需从 COS 拉回。
- **对比是短期可重跑产物, 不是永久历史**。对比记录(及其本地热力图)默认只保留最近 7 天, 过期**整条删除**; 之后要看老对比, 用仍在 COS 的批次**重跑**即可。因此对比/热力图不需要上 COS。
- **SQLite 仍是元数据真源**。对象存储只保存原图大文件, 不承担查询、筛选、分页。
- **业务路径尽量少改**。上传、图片服务、缩略图、对比引擎统一通过存储抽象层访问文件, 其他业务逻辑保持现有模型。

非目标:

- 第一阶段不迁移 SQLite 到云数据库。
- 第一阶段不做按批次 tar/zip 冷归档。
- 第一阶段不依赖临时签名 URL, 因为当前桶是 public-read。

## 3. 现状

| 数据 | 当前本地位置 | 说明 |
| --- | --- | --- |
| 元数据 | `backend/data/shotdiff.db` | SQLite, 体积小; Batch/Screenshot/Baseline/Comparison/ComparisonItem/Setting |
| 原图截图 | `backend/data/images/batches/{batch_id}/{scene_name}.png` | 大头; 对比和放大都依赖; `Screenshot.path` 存相对路径 |
| 热力图 | `backend/data/images/heatmaps/{comparison_id}/*.webp` | 对比产物; **仅本地**, 随对比记录 7 天过期整条删除, 不上 COS |
| 缩略图 | `backend/data/images/thumbs/batches/{batch_id}/*.webp` | 派生缓存; 可重建, 不上 COS |

当前服务方式:

- `app.mount("/images", StaticFiles)` 直接暴露本地图片。
- `GET /thumb/<path>` 懒生成缩略图。
- `compare.py` / `service.py` 直接按本地文件路径读原图。

这些直接读盘的路径是本次改造的主要收敛点。

## 4. COS 接入事实

当前可用链路:

```text
配置文件: scripts/CosConfig.yaml                  # 本机文件, 不提交
工具:     cos_helper
bucket:   arashimain                              # 从 CosConfig.yaml 的 cos.bucket 读取
appid:    70674                                   # 由 CosConfig.yaml 提供
host:     njc.vod.tencent-cloud.com               # 由 CosConfig.yaml 提供
协议:     http                                    # 当前配置 network.use_https=false
前缀:     /PixelComparison/
URL:      http://arashimain-70674.njc.vod.tencent-cloud.com/PixelComparison/...
```

最小验证脚本:

```powershell
$env:COS_CONFIG="D:\PixelComparison\scripts\CosConfig.yaml"

python scripts\cos_pixelcomparison_smoke.py upload README.md test/README.md
python scripts\cos_pixelcomparison_smoke.py download test/README.md .\README.downloaded.md
python scripts\cos_pixelcomparison_smoke.py url test/README.md
```

注意:

- `cos_pixelcomparison_smoke.py` 只做验证, 不是最终后端存储层。
- **当前环境没有 `qcloud_cos` Python SDK, 只有 `cos_helper` 命令行**。因此后端 COS 访问也封装 `cos_helper`(见 `backend/app/cos_client.py`), 而不是接 SDK。`cos_helper` 的调用方式参考 `mhperf/cos_api.py` 与本项目 smoke 脚本(均已验证 put/get/url)。
- 子进程封装可接受的原因: **COS 永不在请求热路径上**——近期数据(<14 天)恒为本地命中, 热力图不上 COS, 故只有「冷回源 >14 天老原图(罕见)」「迁移/对账/淘汰(批量任务)」会真正调 COS。批量任务用线程池并发调用子进程, 冷回源在 storage 层限并发(10.1), 即可。
- 如果未来改为私有桶, 冷图直链策略要改成预签名 URL 或后端代理。

## 5. 目标对象布局

本地仍保留现有相对路径, COS 上额外加统一项目根前缀:

| 类型 | 本地相对路径 | COS 对象 key |
| --- | --- | --- |
| 原图 | `batches/{batch_id}/{scene_name}.png` | `PixelComparison/images/batches/{batch_id}/{scene_name}.png` |
| DB 快照 | `shotdiff.db` | `PixelComparison/db-backups/shotdiff-{yyyyMMdd-HHmmss}.db` |
| 临时验证 | 无 | `PixelComparison/_smoke/...` |

**COS 上只有原图(和 DB 快照)**。热力图、缩略图都只存本地, 不上 COS:

- **缩略图**: 派生缓存, 可从原图重建; 冷数据第一次访问时先回源原图, 再按现有逻辑生成缩略图即可。
- **热力图**: 对比是「短期可重跑产物」, 记录只留 7 天即整条删除(见 9.2 / 13.2)。由于对比保留期(7 天) < 原图本地热缓存期(14 天), 热力图在其整个生命周期内都待在本地热窗口里, **永远不会被淘汰到「只剩 COS」**, 所以上传 COS 纯属多余。这样也彻底消除了「对比记录被删后 COS 热力图变 orphan」的问题。

## 6. 总体架构

```text
            上传(report.py / 手动上报)
                     |
                     | 写本地热缓存 + 上传 COS
                     v
   +-------------------------+        put/get/delete/url        +-----------------------------+
   | backend/data/images/    | <------------------------------> | COS: arashimain             |
   | 本地热缓存              |        storage 抽象层            | /PixelComparison/images/...  |
   +-------------------------+                                  +-----------------------------+
              ^
              | 命中即服务; 未命中则从 COS 拉回再服务
              |
   SQLite: backend/data/shotdiff.db
   元数据真源; 可定期快照到 COS
```

要点:

- `backend/data/images/` 第一阶段不改目录名, 只改变语义: 从“唯一存储”变成“本地缓存”。
- 所有图片读写必须经过 `app/storage.py`, 不再让业务代码直接拼磁盘路径。
- COS 是最终持久层; 本地文件可以被淘汰, 但未确认上云的批次不允许淘汰。

## 7. 配置设计

建议新增后端配置:

```text
COS_ENABLED=false                         # 默认 false, 纯本地模式; 控制「双写」和「淘汰」, 不控制「读」(见 7.1)
COS_CONFIG=scripts/CosConfig.yaml          # cos_helper 模式使用; 不提交真实文件
COS_HELPER=cos_helper                      # 可选, 不填则从 PATH/Python Scripts 查找
COS_BUCKET=                                # 可选覆盖; 默认读取 CosConfig.yaml 的 cos.bucket
COS_PREFIX=PixelComparison/images
COS_PUBLIC_BASE_URL=http://arashimain-70674.njc.vod.tencent-cloud.com
HOT_RETENTION_DAYS=14                      # 批次原图本地热缓存保留天数
COLD_REFILL_RETENTION_DAYS=2              # 冷读回填的原图额外驻留天数
COMPARISON_RETENTION_DAYS=7               # 对比记录(及本地热力图)保留天数, 过期整条删除
LOCAL_IMAGE_DIR=backend/data/images
```

配置约束(硬校验, 启动时检查):

- **`COMPARISON_RETENTION_DAYS` 必须 ≤ `HOT_RETENTION_DAYS`**。否则会出现「对比还在、但它依赖的原图本地已淘汰」需要回源、而热力图又没上 COS 的尴尬组合。**违反则启动失败**, 不做默认夹紧(避免静默改变用户意图)。当前默认 7 ≤ 14 满足。

安全要求:

- `CosConfig.yaml`、`.env`、运行日志不得提交。
- `cos_helper` 用的 `CosConfig.yaml`(含 `SecretId/SecretKey`)是本机文件, 必须 `.gitignore`, 不提交; 仓库只放脱敏 `CosConfig.example.yaml`。
- 当前桶 public-read, 因此不要上传包含隐私或未授权内容的图片。
- 如后续需要权限控制, 应切换私有桶并改为后端代理或预签名 URL。

启动自检:

- 若 `COS_ENABLED=true` 但 client 构造失败(密钥缺失、桶不通、配置文件不存在), 必须**启动失败或显式降级为只读本地 + 告警**, 不允许「以为在双写、其实啥也没传」的静默状态——否则一旦淘汰任务运行, 这批从未真正上云的数据会被删掉而丢失。

### 7.1 COS_ENABLED 的精确语义(开关式设计)

`COS_ENABLED` 是**部署级**开关(env, 改后重启生效), 不做运行时热切换 / 每请求 / 每用户粒度。它的语义必须精确, 否则一个布尔会变成能丢数据的按钮。

天真实现(到处 `if COS_ENABLED:`)有一个不可逆陷阱:

> 一旦淘汰任务跑过(本地删了、只剩 COS), 再把 `COS_ENABLED` 关掉 → 已淘汰批次本地没有、COS 又被禁止读 → **图全裂(brick)**。

因此把「能力」和「行为」分开, 开关只管能随意回退的部分, 把唯一不可逆的动作单独守卫:

| 关注点 | 由什么控制 | 可逆性 |
| --- | --- | --- |
| 是否构造 `CosClient`(cos_helper) | `COS_ENABLED` | — |
| 新上传是否**双写**到 COS | `COS_ENABLED` | 可随意开关 |
| 读: 本地 miss 时是否**回源** | **不看开关, 看该批次是否 `synced`** | 安全 |
| **淘汰本地文件** | 独立守卫: 必须 `COS_ENABLED` 且 `synced` | **唯一不可逆** |

核心规则: **只要从未运行过淘汰, 开关就完全可逆**(关掉只是「不再上传新数据」); **淘汰是唯一会让你回不去纯本地的操作**。所以读路径按「数据是否已上云(synced)」判断, 而不是按全局开关判断——已 synced 的数据即使双写被关, 本地 miss 仍允许回源, 绝不会读裂。

如果确实要在淘汰发生后关掉 COS, 必须先用 `prefetch_cos_cache`(见 16 节)把已淘汰数据重新拉回本地, 再关。

## 8. 存储抽象层

### 8.1 用策略模式选后端, 业务代码对开关无感

`COS_ENABLED` 不应散落在业务代码里。只有 `storage.py` 在启动时挑一个后端实现, `main.py` / `service.py` / `compare.py` 永远只调统一接口, 看不到开关:

```python
def make_storage():
    if not settings.COS_ENABLED:
        return LocalStorage(LOCAL_IMAGE_DIR)                  # 纯本地, 零 COS 依赖
    return TieredStorage(LOCAL_IMAGE_DIR, CosClient(...))     # 双写 + 回源(CosClient 封装 cos_helper)
```

- `LocalStorage.ensure_local`: 在就返回路径, 不在就 None(404)。
- `TieredStorage.ensure_local`: 本地 miss 时按 7.1 的能力规则回源(per-key 锁 + tmp 原子替换)。
- 两者实现同一接口, 便于测试: 测 `LocalStorage` 不碰网络; 测 `TieredStorage` 注入假 client。

### 8.2 统一 API

新增 `backend/app/storage.py`, 提供统一 API:

```python
def object_key(rel_path: str) -> str:
    """batches/1/a.png -> PixelComparison/images/batches/1/a.png"""

def put_file(rel_path: str, local_path: Path) -> None:
    """上传已有本地文件到 COS。"""

def put_bytes(rel_path: str, data: bytes) -> Path:
    """写本地缓存, 再上传 COS, 返回本地路径。"""

def local_path(rel_path: str) -> Path:
    """返回本地缓存路径, 但不保证存在。"""

def ensure_local(rel_path: str) -> Path:
    """本地不存在时从 COS 下载到临时文件, 校验后原子替换。"""

def exists_remote(rel_path: str) -> bool:
    """检查 COS 对象是否存在。"""

def delete(rel_path: str) -> None:
    """删除本地缓存和 COS 对象。"""

def public_url(rel_path: str) -> str:
    """当前 public-read 桶下返回普通 HTTP URL。"""
```

实现细节:

- 所有 `rel_path` 必须做路径清洗, 禁止 `..`、绝对路径、盘符路径。
- `ensure_local()` 下载到 `*.tmp` 后再 `replace()`, 避免并发读到半文件。
- 同一个对象的冷读回源应加轻量锁, 避免多个请求同时下载同一张图。
- COS 操作要有超时、重试和明确日志(已在 `cos_client.py`: 每次调用带 timeout + returncode 检查 + `CosError`, 不回显文件内容/密钥)。
- `TieredStorage` 持有一个 `CosClient`(封装 `cos_helper`); 环境无 `qcloud_cos` SDK, 不接 SDK。

## 9. 写路径

### 9.1 上传截图

现状是上报后写入本地 `backend/data/images/batches/{batch_id}/...`。

改造后:

1. 先写本地缓存, 保证当前请求和后续对比可立即读取。
2. 调 `storage.put_file()` 上传到 `PixelComparison/images/batches/{batch_id}/...`。
3. 上传成功后标记批次 COS 同步完成。
4. 上传失败时保留本地文件, 标记 `pending/failed`, 不允许淘汰。

建议第一阶段采用同步上传:

- 当前单张图平均约 259KB, 同步上传实现简单。
- 失败可以直接暴露给日志/状态, 排障成本低。
- 如果后续上报耗时明显增加, 再改后台队列。

### 9.2 生成热力图(仅本地, 不上 COS)

热力图算完只写本地, 不上传 COS:

```text
本地: backend/data/images/heatmaps/{comparison_id}/{name}.webp
COS:  (无)
```

原因:

- 对比是「短期可重跑产物」, 记录只留 7 天即整条删除(13.2), 没有长期保存需求。
- 热力图依赖**生成时的对比参数**(`heatmap_method`/`gamma`/… 会随设置漂移), 用今天参数重算老对比得到的图和当时不同, 也和库里旧指标对不上——所以「保留旧图」本就只对「保留旧记录」才有意义; 既然记录 7 天即弃, 图也一起弃。
- 要看 7 天前的对比, 直接用仍在 COS 的批次重跑一次(得到当前参数下的全新对比), 语义正确。

### 9.3 删除批次 / 覆盖同号批次(单批次, 同步改 COS)

只支持**单批次**删除和覆盖, **不提供多选/批量删除入口**——把 COS 删除的爆炸半径锁死在一个批次, 单对象级删除的非原子性才可接受。

- **删除批次**: 先删 DB 记录(真源)→ 再 best-effort 删 COS `batches/{id}/` 前缀(失败只记日志, 留给对账兜底, 因为记录已没、对象天然是 orphan)→ 删本地缓存(原图/缩略图)。其本地热力图随对比记录级联删。
- **覆盖同号批次**: 顺序相反, 保证任何时刻都能读到完整数据——先上传新原图到 COS 并校验到位 → 再改 DB → 最后清理旧对象。
- **对账兜底(必须有)**: 周期 `reconcile` 脚本扫 `PixelComparison/images/batches/` 下「DB 已无对应批次」的对象并清理。理由: ① 单次 COS 删除仍可能失败; ② 当前是 public 桶, 删剩的图在被清理前任何人凭 URL 都能访问, 既是成本也是数据暴露, 不能只靠「每次删都成功」的乐观假设。

**缓存一致性(覆盖必须处理)**: 覆盖后 COS key 不变(`batches/{id}/{scene}.png`), 而 `/images` 带了 `Cache-Control: public, max-age=86400`——浏览器/CDN 在缓存期内会**继续返回旧图最长一天**, 用户「覆盖完看还是旧的」。因此:

- 覆盖时给该批次记一个版本指纹(用新原图的 `etag` 或写入时刻 `mtime`/递增 `rev`, 存 `Screenshot` 或 `Batch`)。
- 前端图片 URL 统一带版本 query: `/images/batches/{id}/{scene}.png?v={fingerprint}`。指纹随覆盖变化, 自然击穿浏览器/CDN 缓存; 未覆盖时指纹不变, 缓存照常命中。
- `?v=` 只参与缓存键, 后端 `serve_image` 忽略它(不参与 `object_key`)。删除批次同理不需处理(URL 整个失效)。

## 10. 读路径

### 10.1 原图服务

将当前 `/images` 静态挂载替换为缓存感知端点:

```text
GET /images/{path}
```

处理逻辑:

1. 调 `storage.ensure_local(path)`。
2. 本地命中则直接 `FileResponse`(支持 Range, 大图放大/拖动可分段)。
3. 本地缺失则从 COS 下载, 回填本地后 `FileResponse`。
4. COS 也不存在则 404。

这样前端图片 URL 可以暂时不变, 风险最低。

**冷读失败/超时行为(必须定义, 否则拖垮线程池)**: COS 慢或挂时, 冷读会在下载上阻塞, grid 冷开几十张并发会把 anyio 线程池占满、整站变慢。因此给冷读一个明确的「快速失败 + 降级」预算, 而不是无限等:

- **单对象下载超时预算**(如连接 3s / 总 10s)+ 有限重试(如 1 次), 超出即放弃。
- 失败不要 500 挂住, 返回**可缓存性低的明确错误**: 缩略图端点返回占位图(前端已有 `onThumbErr` 回退逻辑可复用), 原图端点返回 503/404 让前端显示「图片暂不可用」。
- **回源并发上限**: 给冷读回源单独限并发(如全局信号量 N), 满了快速失败而非排队, 保护正常的本地命中请求不被冷读拖死。
- per-key 锁(8.1)避免同一对象重复下载; 注意锁表会随 key 增长, 需带上界清理, 且只在单进程有效(多 worker 前提见 17 节)。

### 10.2 缩略图

`GET /thumb/<path>` 改成:

1. `storage.ensure_local(原图 path)`。
2. 用现有逻辑生成或读取本地缩略图。
3. 缩略图仍只保存在本地。

### 10.3 冷图直链优化

当前 `arashimain` 是 public-read, 所以冷图可以直接给浏览器普通 URL:

```text
http://arashimain-70674.njc.vod.tencent-cloud.com/PixelComparison/images/...
```

但建议不要第一阶段就改前端直连, 原因:

- 代理回源方式对前端透明, 回归风险低。
- 仍可复用现有鉴权、缓存头、错误处理。
- 后续确认 grid 冷开慢时, 再对列表图/大图做“本地有走后端、本地无走 COS URL”的优化。

如果未来换私有桶:

- public URL 不再可用。
- 需要改成后端代理, 或用短 TTL 预签名 URL。

## 11. 对比引擎读路径

对比任务启动前, 先批量确保两批次原图在本地:

```python
for shot in shots:
    storage.ensure_local(shot.path)
```

然后保持 `compare.py` 的本地文件计算模型不变。

冷历史对比的行为:

- 第一次会慢, 因为要从 COS 拉两批原图。建议在对比任务线程内用小线程池并发 `ensure_local`, 否则几十张串行回源会很慢; 可把「回源中 x/N」并入现有进度轮询。
- 现有后台任务和进度轮询机制可以继续承载。
- 计算完成后热力图只写本地(不上 COS), 原图仍按缓存 TTL 淘汰。

## 12. DB 状态与一致性

建议给 `Batch` 增加同步状态字段:

```text
cos_sync_status: local_only | pending | synced | failed
cos_synced_at: datetime | null
cos_sync_error: text | null
```

最低可用版本也可以只加:

```text
cos_synced_at: datetime | null
```

但推荐状态字段, 因为它能区分:

- 未启用 COS 的历史本地数据。
- 正在上传或部分失败的数据。
- 已确认可从 COS 恢复的数据。

缓存淘汰任务只能删除 `synced` 批次的本地**原图**(热力图由对比记录淘汰负责, 见 13.2)。`pending` 和 `failed` 必须保留。

新增 `cos_sync_status` 列时, **存量历史批次的默认值必须是 `local_only`, 绝不能是 `synced`**——否则淘汰任务会把从未上过云的老数据当成「可删」直接删掉, 造成数据丢失。只有迁移脚本上传校验成功后, 才把对应批次改为 `synced`。

为防回源/迁移校验「仅看大小蒙混过关」, 建议给 `Screenshot` 存 `size_bytes`(最低)或 COS 返回的 `etag`, 供 `ensure_local` 和迁移校验比对; 仅靠 public 桶 HEAD 的 `Content-Length` 不足以发现错误页/截断响应。

对象 key 不需要存 DB:

- `Screenshot.path` 已经是稳定相对路径。
- `object_key(path)` 可确定性生成 COS key。
- 避免 DB 中出现两套路径来源。

## 13. 淘汰策略

淘汰是**整套方案唯一不可逆的操作**(见 7.1): 它把「本地是唯一副本」变成「COS 是唯一副本」。因此淘汰任务有两条硬前置, 缺一不可:

- `COS_ENABLED=true`(开关开着)。
- 目标批次 `cos_sync_status=synced`(确认已上云)。`pending` / `failed` / `local_only` 一律不淘汰。

只要从未跑过淘汰, `COS_ENABLED` 就可以随意关回纯本地; 一旦淘汰过, 关开关前必须先 `prefetch_cos_cache` 回填。

系统里有**两类语义完全不同的淘汰**, 必须分开实现, 不要混成一个:

- **13.1 原图缓存淘汰**: 记录仍在, 只清本地原图缓存, **保留 COS**。可逆(回源能拉回)。
- **13.2 对比记录淘汰**: **整条记录删除**(DB 行 + 本地热力图), 因为对比是短期可重跑产物。由于热力图不上 COS, 这里没有 COS 删除、没有 orphan、不需要对账。

### 13.1 原图缓存淘汰(`app/evict_cache.py`)

```text
HOT_RETENTION_DAYS=14
COLD_REFILL_RETENTION_DAYS=2
```

周期任务:

1. 查询 `created_at < now - HOT_RETENTION_DAYS` 且 `cos_sync_status=synced` 的批次。
2. **排除基线批次**(见下「基线豁免」)。
3. 删除本地 `backend/data/images/batches/{batch_id}` 和缩略图 `thumbs/batches/{batch_id}`。
4. **不删除 COS 对象**(原图主存留在 COS)。

**基线豁免(关键, 否则基线被反复冷拉)**: 基线批次(`Baseline` 关联的批次)是**长期高频被引用**的参照——几乎每次对比都要读它。纯按 `created_at` 淘汰会把老基线删掉, 然后每次对比都得从 COS 冷拉、又被下轮按日期删掉, 来回拉。所以:

- 淘汰时**豁免所有当前被 `Baseline` 引用的批次**, 不删其本地原图。
- 基线一旦被取消/替换(不再被任何 `Baseline` 引用), 则回归普通批次, 按 13.1 正常计龄淘汰。
- 这是「按创建时间」和「按访问热度」的错配修正; 第一阶段用「基线集合豁免」即可, 不必上完整 LRU。

冷读回填与「双 TTL 合并规则」(关键, 否则回填即被秒删):

- 回填的原图按文件 mtime 计龄(`ensure_local` 的 `tmp.replace` 会把 mtime 置为回填时刻)。
- **一个 synced 老批次的本地原图, 必须「`created_at` 超过 `HOT_RETENTION_DAYS`」且「文件 mtime 超过 `COLD_REFILL_RETENTION_DAYS`」两个条件同时满足才可删**。否则会出现「用户刚回填一张三个月前的图, 下一轮淘汰按 `created_at` 立刻又删掉」, 回填白做、老图永远要等回源。即: 回填的文件享有 `COLD_REFILL_RETENTION_DAYS` 的最短驻留宽限期。

**淘汰 vs 正在被读/对比的文件(Windows 文件锁)**: 在 Windows 上删除一个正被 `FileResponse` 发送、或正被对比读取的文件会失败/受阻。所以淘汰必须:

- 对**删除失败的文件容错跳过**(记日志, 下一轮再删), 不能因单个被占用文件中断整轮淘汰。
- `ensure_local` 要容忍「文件读到一半被淘汰删掉」: 读不到时重新回源, 不向上抛硬错。
- 建议淘汰**避开正在运行的对比所涉批次**(`_RUNNING` 里的批次跳过), 进一步减少与对比读的竞争。

### 13.2 对比记录淘汰(替换原 100 条上限)

把现有「最新 100 条」(`_evict_old_comparisons` + `_MAX_COMPARISONS`)改为**按时间**:

```text
COMPARISON_RETENTION_DAYS=7
```

逻辑:

1. 查询 `created_at < now - COMPARISON_RETENTION_DAYS` 的 comparison。
2. **整条删除**: 删 DB 的 `Comparison` + `ComparisonItem`(级联)+ 本地 `heatmaps/{comparison_id}/`。
3. 没有 COS 操作(热力图不上云)。
4. `_MAX_COMPARISONS` 常量退休; 它原来在对比任务 `finally` 里跑, 现在改成按时间判据即可(也可挪到周期任务里)。

代价(已确认接受): 主机损坏时最近 7 天对比会丢失(热力图未上云), 但批次原图都在 COS, **重跑即可恢复**。

### 与 `app.cleanup` 的边界

- `cleanup`: 清理 DB 中已经不存在的孤儿**本地**文件。**COS 模式下它不应触碰 COS 对象**(否则「看一眼老图→回源→被 cleanup 当孤儿删 COS」会是灾难); 删 COS 对象只由 9.3 的删除/覆盖 + `reconcile` 负责。
- `evict_cache`(13.1): 清理 DB 中仍存在、但已上云且超期的本地原图缓存。
- 对比记录淘汰(13.2): 删整条对比记录及其本地热力图。

## 14. 迁移方案

新增 `backend/app/migrate_to_cos.py`:

流程:

1. 遍历 `backend/data/images/batches/`(**只迁原图**, 热力图不上 COS)。
2. 按 `object_key(rel_path)` 上传到 COS; 上传前可先 `exists_remote` 跳过已存在对象(幂等, 便于重跑)。
3. 上传后校验对象可访问。优先比对存库的 `size_bytes`/`etag`(见 12 节); public-read 桶至少用 `HEAD public_url` 校验 `Content-Length`。
4. 一个批次内全部原图上传校验成功后, 才更新该批次 `cos_sync_status=synced`、`cos_synced_at=now`(批次粒度, 任一失败整批标 `failed`)。
5. 迁移完成前不做本地淘汰。

参数:

```powershell
python -m app.migrate_to_cos --dry-run
python -m app.migrate_to_cos --limit 100
python -m app.migrate_to_cos --batch-id 123
python -m app.migrate_to_cos --verify-only
```

迁移注意:

- 迁移期间尽量暂停大批量上报, 或先只迁历史批次。
- 每个对象上传失败要记录, 不应中断后丢失上下文。
- 迁移日志不能打印密钥。

## 15. SQLite 备份

SQLite 仍留在本地, 但必须定期快照到 COS。否则新主机只有图片对象, 没有批次、截图、对比关系等元数据, 无法恢复完整服务。

```text
PixelComparison/db-backups/shotdiff-20260622-180000.db
PixelComparison/db-backups/shotdiff-latest.db
```

触发方式:

- 每日定时。
- 大批量迁移完成后。
- 可选: 每次删除批次/覆盖批次后。

备份前建议:

- 使用 SQLite backup API 或先复制一致性快照, 不直接上传正在写入的 DB 文件。
- 保留最近 N 天快照, 避免无限增长。
- `shotdiff-latest.db` 用于快速恢复, 时间戳快照用于回滚到历史版本。

## 16. 新主机迁移 / 灾备恢复

本方案应支持后端迁移到另一台机器。迁移时新主机不需要旧机器上的完整 `backend/data/images/` 目录, 只需要代码、COS 配置和 SQLite 快照。

恢复流程:

```text
1. 在新主机部署代码。
2. 配置 COS 访问: scripts/CosConfig.yaml 或 COS_CONFIG / COS_HELPER。
3. 从 COS 下载 PixelComparison/db-backups/shotdiff-latest.db。
4. 放到 backend/data/shotdiff.db。
5. 启动后端。
6. 本地图片缓存为空也可以运行; 用户访问图片或发起对比时, storage.ensure_local() 按需从 COS 回源。
```

可选预热:

```text
python -m app.prefetch_cos_cache --days 14
python -m app.prefetch_cos_cache --batch-id 123
```

预热脚本只负责把最近批次或指定批次图片提前拉到 `backend/data/images/`, 提升新主机首次访问速度。没有预热也不影响正确性。

迁移能力依赖两个条件:

- 批次原图已经上传到 `PixelComparison/images/batches/...`。
- SQLite 快照已经上传到 `PixelComparison/db-backups/...`。

缺少任一条件都不能完整恢复:

- 只有 SQLite, 没有 COS 原图: 页面有批次记录, 但图片无法展示、也无法重跑对比。
- 只有 COS 原图, 没有 SQLite: 新主机不知道有哪些批次和截图。

注意: 恢复后**最近 7 天的对比记录与热力图不会回来**(它们从不上云, 已确认接受)。批次原图齐全, 需要时重跑即可。

建议增加恢复演练:

- 每周或每次大改后, 在临时目录下载 `shotdiff-latest.db`。
- 启动一套临时后端, 不复制旧 `images/`。
- 打开一个近期批次和一个历史批次, 确认图片可从 COS 回源。

## 17. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| COS 上传失败 | 本地仍是唯一副本, 淘汰会丢数据 | `cos_sync_status` 未 synced 不淘汰; 重试/对账 |
| 淘汰后关 `COS_ENABLED` | 已淘汰批次本地无、又禁读 COS, 图全裂(brick) | 读路径按 synced 能力判断而非开关(7.1); 关开关前先 `prefetch_cos_cache` 回填 |
| 开关开着但 COS 不通却静默 | 以为在双写, 实际没上云, 淘汰后丢数据 | 启动自检: 构造失败即启动失败或降级只读 + 告警(7 节) |
| public-read 桶泄露访问路径 | 知道 URL 即可读 | 只放允许公开访问的数据; 需要权限时改私有桶 |
| 冷读慢 | 老批次首次打开或对比慢 | 后端回源 + 本地回填; 后续可加直链/预取/虚拟列表 |
| 基线按日期被淘汰 | 高频引用的老基线反复冷拉, 对比变慢 | 淘汰豁免 `Baseline` 引用的批次(13.1) |
| 覆盖后服务旧图 | 同 key + max-age=86400, 浏览器/CDN 一天内返回旧图 | 图片 URL 带版本指纹 `?v={etag/rev}`, 覆盖时变更击穿缓存(9.3) |
| 淘汰 vs 占用文件 | Windows 删被读/被算的文件失败, 淘汰中断或半删 | 删失败容错跳过下轮再删; `ensure_local` 容忍中途被删重新回源; 跳过 `_RUNNING` 批次(13.1) |
| 冷读打满线程池 | COS 慢/挂时回源阻塞, grid 冷开拖垮整站 | 下载超时预算 + 有限重试; 回源并发上限信号量; 失败返回占位图/503 不挂住(10.1) |
| 冷开 grid 请求多 | 几百张缩略图需先回源全尺寸原图再生成, 放大成几十次全图下载 | 只回源可视区 + 懒加载(建议提前到阶段 3); 前端虚拟滚动; 后台预取 |
| 删除/覆盖后 COS 残留 orphan | public 桶下删剩图仍可被 URL 访问, 且占成本 | 只允许单批次删除/覆盖(禁批量), 删除走 9.3 时序; 周期 `reconcile` 兜底扫 orphan |
| 主机损坏丢最近 7 天对比 | 近 7 天对比记录/热力图不可恢复 | 已接受: 批次原图在 COS, 重跑恢复; 不接受则需让热力图上 COS + 用 COS 生命周期规则自动过期 |
| SQLite 单点 | 机器损坏后元数据丢失, 新主机无法恢复 | 定期 DB 快照到 COS, 保留 `latest` 和时间戳版本 |
| 路径穿越 | 读取/覆盖非图片目录 | storage 层统一清洗 rel_path |
| 并发冷读同一对象 | 重复下载、半文件 | per-key 锁 + tmp 文件原子替换 |

## 18. 分阶段落地

**两个门槛(决定能否进入 COS 阶段)**: 阶段 2 及以后都依赖 ① **确认拿到 COS 桶的写权限 + 凭据**(`SecretId/SecretKey`, 当前仅验证过 cos_helper 的 put/get/url, `cos_client` 的 rm/ls/exists 未现场验证); ② **public 桶安全决策已拍板**(见待拍板 #5: key 顺序可枚举, 是否接受公开, 还是换私有桶)。在这两条落地前, **只做阶段 0–1**(全部 COS 无关, 不等凭据、不等决策, 立即有价值)。

### 阶段 0: 连通性与配置固化

- 已验证 `/PixelComparison/` 上传、下载、URL(cos_helper)。
- 已有 `scripts/cos_pixelcomparison_smoke.py`; `CosConfig.yaml` / `cos_helper.log` 已入 `.gitignore`。

剩余:

- **已封装 `backend/app/cos_client.py`**(cos_helper 库化: put/get/delete/list/exists/url + 超时 + `CosError`, 复用 smoke 脚本已验证的配置/解析)。环境无 `qcloud_cos` SDK, 故走 cos_helper。
- 待用真实写权限**冒烟验证 `cos_client` 的 put/get/delete/list/exists/url** 一轮(smoke 脚本已验过 put/get/url, 新增的 rm/ls/exists 需现场跑一次)。
- `scripts/CosConfig.example.yaml`(脱敏示例)+ README 本机 COS 配置说明。

### 阶段 1: COS 无关的独立改进 + 存储抽象(可立即做)

本阶段不碰 COS, 不需要凭据或安全决策, 每项都能独立提交、独立测试、立即有收益:

- **1a 对比淘汰改时间(13.2)**: 把「最新 100 条」(`_evict_old_comparisons`/`_MAX_COMPARISONS`)改为「7 天整条删除」。纯本地(删 DB 记录 + 本地热力图), 与 COS 无关, 可先落地。
- **1b 覆盖缓存击穿(9.3)**: 给图片 URL 加版本指纹 `?v={rev/mtime}`, 覆盖时变更。**这是修现存 bug**——`/images` 已带 `max-age=86400` + 覆盖功能已上线, 当前覆盖后浏览器/CDN 最长一天返回旧图。纯本地, 越早越好。
- **1c 存储抽象层**: 新增 `storage.py` 先做纯本地实现(`LocalStorage`); 把 `/images`、`/thumb`、上传、对比读图统一收口走 storage; 加 `tests/test_storage.py`(路径清洗/读写/404)。目标: 行为不变, 只收口路径, 为阶段 2 铺底。
- **1d(并行可选)grid 虚拟化/懒加载**: 也 COS 无关。既治当前多人同时开 grid 的尾延迟(一次几百张图), 又预先消除阶段 3 的「冷开 grid 放大成几十次全图回源」。建议在进入冷读阶段前完成。

### 阶段 2: COS 双写(仅原图)—— 需门槛 ①②

- `COS_ENABLED=true` 时上传**原图**到 COS(热力图不上); `TieredStorage` 持有 `CosClient`(cos_helper)。
- 新增 DB 同步状态字段(默认 `local_only`)+ `Screenshot.size_bytes/etag`。
- 新增迁移脚本(只迁原图, 幂等, 批次粒度置 `synced`)。
- 上传失败保留本地并标记 `failed`; 启动自检(7 节)。
- 删除/覆盖走 9.3 时序; 加 `reconcile` 对账(带 grace period, 跳过刚上传未提交的新对象, 见待拍板 #7)。

目标: 新数据可恢复, 老数据可迁移; 删除/覆盖与 COS 一致。

### 阶段 3: 冷读回源 —— 需门槛 ①②

- `/images/{path}` 本地 miss 时从 COS 下载, 带**超时预算 + 有限重试 + 回源并发上限 + 失败降级(占位图/503)**(10.1), 别拖垮线程池。
- `/thumb` 基于回源后的原图生成。
- 对比任务启动前**并发** `ensure_local()` 两批原图, 进度并入轮询。

目标: 删除本地老图后仍能查看和对比历史数据。

### 阶段 4: 淘汰与备份 —— 需门槛 ①②

- 新增 `app/evict_cache.py`(13.1 原图缓存淘汰): 只淘汰 `synced` 批次, **豁免基线**, 遵守**双 TTL 合并规则**, 删失败容错跳过、跳过 `_RUNNING` 批次。
- 增加 SQLite 快照上传(WAL 下用 backup API / `VACUUM INTO`, 不直接复制文件); 明确快照间隔 = 元数据丢失窗口(RPO, 见待拍板 #6)。
- 新主机恢复脚本/文档 + `prefetch_cos_cache` 预热。

目标: 本地磁盘增长受控, 新主机可通过 COS 恢复服务。

### 阶段 5: 冷读优化 —— 需门槛 ①②

- public-read 桶下让冷图直接走 COS URL(注意 http 直链与 https 前端的 mixed-content; 私有桶则需预签名/代理)。
- COS 请求量/流量监控告警(成本主要在请求数, 不是存储, 见待拍板 #8)。
- 请求数或费用变高后再评估按批打包。

## 19. 影响文件

新增:

- `backend/app/cos_client.py`(cos_helper 封装: put/get/delete/list/exists/url + 超时 + `CosError`)**[已建]**
- `backend/app/storage.py`(策略模式: `LocalStorage` / `TieredStorage`, 后者持有 `CosClient`)
- `backend/app/migrate_to_cos.py`(只迁原图)
- `backend/app/evict_cache.py`(13.1 原图缓存淘汰; 豁免基线、双 TTL、删失败容错)
- `backend/app/reconcile_cos.py`(扫 COS orphan 兜底)
- `backend/app/backup_db_to_cos.py`
- `backend/app/restore_db_from_cos.py` 或恢复脚本文档
- `backend/app/prefetch_cos_cache.py`
- `backend/tests/test_storage.py`
- `scripts/CosConfig.example.yaml`

修改:

- `backend/app/main.py`: `/images`(冷读超时预算+并发上限+占位/503 降级, 忽略 `?v=`)、`/thumb`、上传、删除/覆盖(覆盖写版本指纹)逻辑
- `backend/app/service.py`: 对比任务前并发 `ensure_local` 原图; 对比淘汰改为 7 天整条删除(替换 `_MAX_COMPARISONS`/`_evict_old_comparisons`)
- `backend/app/compare.py`: 如仍直接读路径, 接收 storage 返回的本地路径
- `backend/app/models.py`: 增加 COS 同步状态字段(默认 `local_only`); `Screenshot.size_bytes/etag`(校验 + 覆盖缓存指纹)
- `backend/app/db.py`: 迁移/初始化字段(默认值务必 `local_only`)
- `backend/app/cleanup.py`: 与 evict 边界拆清; COS 模式下不碰 COS 对象
- `backend/app/settings.py`: 增加 COS/cache 配置 + 启动校验(`COMPARISON_RETENTION_DAYS ≤ HOT_RETENTION_DAYS`、COS 连通自检)
- `backend/requirements.txt`: 无需加 `qcloud_cos`(环境无 SDK); COS 经 `cos_helper` 子进程(`cos_client.py`)。PyYAML 可选(缺失有极简解析回退)
- `frontend/src/api.js` 等: 图片 URL 拼接版本指纹 `?v={fingerprint}`(覆盖后击穿缓存, 见 9.3); 缩略图失败回退占位已有 `onThumbErr` 可复用
- `README.md` / `docs/使用文档.md`: 增加部署和恢复说明

## 20. 决策记录与待拍板

已定:

- **热力图不上 COS**, 只本地, 随对比记录 7 天过期整条删除。
- **对比保留改为按时间(7 天)整条删除**, 替换原「100 条上限」; 接受主机损坏丢最近 7 天对比(重跑恢复)。
- **配置约束 `COMPARISON_RETENTION_DAYS ≤ HOT_RETENTION_DAYS`**, 违反则启动失败(不夹紧)。
- **只允许单批次删除/覆盖, 禁批量删除**; 配 `reconcile` 对账兜底。
- **后端 COS 访问封装 `cos_helper`**(`backend/app/cos_client.py`), 因当前环境无 `qcloud_cos` SDK; 参考 `mhperf/cos_api.py`。子进程模型可接受, 因 COS 永不在热路径(见 4 节)。
- `COS_ENABLED` 为部署级开关, 语义见 7.1(控制双写+淘汰, 不控制读)。

待拍板:

- 本地热缓存保留期是否固定为 14 天; 冷读回填驻留是否固定 2 天。
- DB 快照保留策略: 保留多少天、是否保留 `latest`。
- 新主机迁移时是否默认预热最近 14 天原图, 还是完全按需回源。
- **#5 public 桶 + 顺序可枚举 key 的安全性**: 对象 key 是确定性的 `batches/{batch_id}/...` 且 batch_id 多为顺序整数, 任何人可枚举遍历全部截图。对未发布画面是泄露。是否接受公开? 不接受则需 ① key 加不可猜随机段(存 DB), 或 ② 换私有桶 + 后端代理/预签名。**这是阶段 2 的前置门槛之一**。
- **#6 容灾 RPO(数据丢失窗口)**: 恢复依赖 `shotdiff-latest.db` 快照, 元数据丢失窗口 = 快照间隔(每日 = 最多丢 24h 批次)。且「快照后新上报」的批次其 COS 对象在新主机不可见、「快照后删除」的批次恢复后会复活。需定快照频率(是否关键操作后即拍)与可接受窗口。
- **#7 `reconcile` 误删在传对象**: 对账删「DB 无记录」对象时, 可能撞上「刚上传成功、DB 行未提交」的瞬间。reconcile 须只清「超过 grace period(如 30min)」的对象或跳过 `pending` 批次。(实现于阶段 2。)
- **#8 成本模型与监控**: 主要成本是**请求数/下行流量**(grid 冷开一次几百 GET), 非存储。需成本量级估算 + COS 请求量/流量监控告警, 否则阶段 5 的冷读优化凭感觉做。
