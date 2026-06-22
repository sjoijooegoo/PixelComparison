# 设计:图片数据分层存储(COS 为主 + 本地两周热缓存)

> 状态:方案设计(待评审),尚未实现。

## 1. 背景与目标

当前所有图片都存在后端本地磁盘 `backend/data/images/`,随批次累积会无限增长(当前约 271MB / 1072 张原图,平均 259KB)。
我们有一个容量很大的 **COS 容器(对象存储)**,目标:

- **COS 作为图片的持久主存**(durable),本地只保留**最近约两周**的热数据做缓存。
- 用户看近两周数据:命中本地,快;看很久以前的:后端按需**从 COS 拉取**再展示(并顺带回填本地缓存)。
- 元数据(SQLite)与对比/检索逻辑尽量不动,改动集中在「图片的存取与服务」一层。

## 2. 现状(改造的输入)

| 数据 | 位置 | 量级 | 说明 |
|---|---|---|---|
| 元数据 | `data/shotdiff.db`(SQLite) | 小(~2MB) | Batch/Screenshot/Baseline/Comparison/ComparisonItem/Setting;含对比指标 JSON |
| 原图截图 | `images/batches/{batch_id}/{scene_name}.png` | **大头** | 对比与放大都读它;`Screenshot.path` 存的就是这个相对路径 |
| 热力图 | `images/heatmaps/{comparison_id}/*.webp` | 中(派生) | 对比产物 |
| 缩略图 | `images/thumbs/batches/{batch_id}/*.webp` | 小(派生缓存) | 懒生成,可随时重建 |

服务方式:`app.mount("/images", StaticFiles)`(原图)、`GET /thumb/<path>`(懒生成缩略图)。
对比引擎 `compare.py`/`service.py` 直接按本地文件路径读原图。

## 3. 总体架构

```
            上传(report.py / 手动上报)
                     │  写本地缓存 + 异步上传 COS
                     ▼
   ┌─────────────┐   put/get/delete   ┌──────────────┐
   │  本地热缓存   │ ◄────────────────► │     COS      │  ← 图片持久主存(原图/热力图)
   │ data/cache/  │   (storage 抽象层)  │  bucket/...  │
   └─────────────┘                    └──────────────┘
         ▲  命中即服务;未命中→从 COS 拉→回填→服务
         │
   SQLite(本地,元数据真源,始终在本地;可定期备份到 COS)
```

要点:
- **DB 留在本地**(对象存储不能做 SQL 查询/筛选/分页);只把**大 blob**(原图、热力图)放 COS。
- **本地目录变成「缓存」语义**:可被淘汰、可重建;COS 是真源。
- **对象 key 直接复用现有相对路径**(`batches/{id}/{scene}.png`、`heatmaps/{cid}/x.webp`),迁移与映射零心智负担。

## 参考实现(wedo_client_site/django_app)

队内已有项目 `tdm_data/views.py` 用的就是腾讯云 COS,可直接借鉴(也明确了几个坑):

```python
from qcloud_cos import CosConfig, CosS3Client          # 官方 cos-python-sdk-v5
cos_config = CosConfig(Region=..., SecretId=..., SecretKey=...,
                       Domain=f'{Bucket}.cos-internal.{Region}.tencentcos.cn', Scheme='http')
cos_client = CosS3Client(cos_config)
# 上传(分片+多线程)
cos_client.upload_file(Bucket=..., LocalFilePath=..., Key=f'tdm/{name}', PartSize=10, MAXThread=10)
# 取下载直链(预签名)
cos_client.get_presigned_url(Bucket=..., Key=..., Method="GET", Expired=...)
```

学到 / 要避开:
- **SDK 确定用官方 `qcloud_cos`**(`CosConfig`+`CosS3Client`),不用 boto3,和队内一致。
- 它的模型是「**上传 COS + 返回预签名直链让客户端直接下载**」,**没有本地分层缓存**——比我们要做的简单;我们在它之上加「两周本地热缓存 + 冷数据回源」。其上传/预签名代码可直接复用。
- **内网域名 `cos-internal.{region}.tencentcos.cn` + `http`**:后端在同云内网访问 COS 更快/省流;**但浏览器若不在该内网,内网域名直链打不开** → 直接影响下面「决策点 1」:要么冷图用**公网域名/CDN** 的预签名给浏览器,要么**后端代理**(后端在内网,能用内网域名)。
- **反面教材**:参考里把 `SecretId/SecretKey` 硬编码在源码里(还有 redis 密码)。我们**必须放环境变量/密管**,不入库不进 git。

## 4. 需要什么

- **COS 接入**:官方 `qcloud_cos`(`CosConfig`/`CosS3Client`,见上方参考);凭证 `SecretId/SecretKey/Region/Bucket` 经**环境变量注入**(不像参考那样硬编码);内网/公网 `Domain` 按「后端上传走内网、浏览器直链走公网/CDN」分别配。
- **配置项**(env / settings):`COS_*` 凭证、`HOT_RETENTION_DAYS=14`、`CACHE_DIR=data/cache`、`COS_ENABLED`(关掉则纯本地,保持现行为)。
- **存储抽象层** `app/storage.py`:统一 `put/get_path/exists/delete/presign`,内部封装「本地缓存 + COS 回源」。上层(上传/服务/对比)只调它,不直接碰磁盘或 COS。
- **迁移脚本** `app/migrate_to_cos.py`:把现有 `images/` 全量上传 COS、校验后把本地转为缓存(或清理超期)。
- **淘汰任务**:按批次 `created_at` 超过保留期、且确认已在 COS,删本地缓存文件(可手动 `python -m app.evict_cache` + 定时调度)。
- **DB 小改**:给 `Batch` 加 `cos_synced: bool`(或 `synced_at`),标记「图片已安全落 COS」,**未同步的不允许被淘汰**。

## 5. 怎么实现

### 5.1 存储抽象层(核心)
```python
# app/storage.py(示意)
def object_key(rel_path: str) -> str: ...          # 即现有相对路径
def put(rel_path: str, data: bytes): ...           # 写本地缓存 + 上传 COS(或入异步队列)
def local_path(rel_path: str) -> Path | None:      # 命中缓存返回本地路径
def ensure_local(rel_path: str) -> Path:           # 不在本地则从 COS 拉→回填→返回本地路径(冷读)
def delete(rel_path: str): ...                      # 删本地 + 删 COS
def presign_get(rel_path: str, ttl=300) -> str: ... # 可选:直链下载
```

### 5.2 写路径(上传截图 / 生成热力图)
- `upload_screenshot`:`storage.put("batches/{id}/{scene}.png", data)` —— 先写本地缓存(立即可用),再上传 COS。
  - 上传可**同步**(简单,慢一点)或**异步队列 + 重试**(快,需补「同步状态」标记)。建议先同步、失败重试,够用再异步化。
- 对比产物热力图:同样 `storage.put("heatmaps/{cid}/...webp", data)`。
- 全部成功后,`Batch.cos_synced=True`。

### 5.3 读路径(服务图片)——把静态挂载改为「缓存感知」端点
- 现 `/images` 的 `StaticFiles` 改为(或新增)`GET /images/{path}` 走 `storage.ensure_local(path)`:
  - 本地命中 → `FileResponse`(带现有 `Cache-Control`)。
  - 未命中 → 从 COS 拉到本地缓存 → `FileResponse`(冷读慢一次,之后命中)。
  - COS 也没有 → 404。
- `GET /thumb/<path>`:基于 `ensure_local(原图)` 再缩略;缩略图保持**本地派生缓存**,不上 COS。
- **可选优化(强烈建议给冷数据用)**:`presign_get` 让浏览器**直连 COS** 下载冷图(后端只发短期签名 URL),省后端带宽、并发更稳;热数据仍走本地。可按「本地有→本地 URL;本地无→COS 直链」二选一返回。

### 5.4 对比引擎读路径
- `service.py`/`compare.py` 读原图前,先 `storage.ensure_local(shot.path)` 把两个批次涉及的原图拉到本地再算。
- 冷对比(对很久以前的两个批次)会先批量拉原图 → 用现有后台任务 + 进度上报覆盖(已有 `_TASKS` 进度机制),前端轮询不变。

### 5.5 淘汰策略
- 周期任务:对 `created_at < now - HOT_RETENTION_DAYS` 且 `cos_synced=True` 的批次,删除其本地 `cache/batches/{id}`、`cache/heatmaps/{相关cid}`、`thumbs/...`。
- 冷读回填进来的旧数据:给「按需回填」的文件设较短 TTL(如 2 天)单独淘汰,避免久看一次就长期占地。
- 与现有 `app.cleanup`(孤儿清理)并存:cleanup 管「DB 没有的垃圾」,evict 管「DB 有但超期的本地缓存」。

### 5.6 迁移与 DB 备份
- 一次性 `migrate_to_cos`:遍历本地 `images/` 上传 COS、逐个校验(size/ETag),完成后把本地视为缓存。
- **SQLite 仍是单点**:建议加「定期把 `shotdiff.db` 快照上传 COS」(每日 + 关键操作后),机器损坏可恢复元数据。

## 6. 关键决策点(需拍板)

1. **冷图服务:后端代理拉取 vs COS 预签名直链**
   - 你的描述是「后端拉取展示」(代理)。代理实现简单、对客户端透明、能兜在鉴权后;但后端扛带宽,grid 冷开(几百张)压力大。
   - 预签名直链(浏览器直连 COS)对 grid 冷开/并发**明显更好**,代价是要求 COS 可被客户端网络访问 + 暴露短期签名 URL。
   - **关键约束(来自参考项目)**:后端用**内网域名**(`cos-internal...`)上传/回源最划算,但浏览器多半访问不了内网域名;若要直链,需给浏览器**公网域名/CDN** 的预签名。两套 Domain 都要配。
   - **建议**:热数据走本地;冷数据**优先公网预签名直链**,COS(公网)不可达或不想暴露时回退**后端代理**(后端走内网域名拉取)。
2. **对象粒度:每张一个对象 vs 每批次打包(tar/zip)**
   - 每张:实现最简、可单图按需取;但 grid 冷开 = 几百次 COS GET(请求数多、计费/延迟)。
   - 每批次打包:GET 次数少、利于整批冷读;但单图随机访问要解包,复杂。
   - **建议**:先每张(简单),配合预签名 + 前端懒加载(见 TODO「列表图虚拟化」)即可;请求数确实痛了再上「按批打包冷归档」。
3. **热力图/缩略图是否上云**
   - 热力图是对比产物,建议上 COS(避免冷查重算);缩略图是纯本地派生缓存,**不上云**,需要时从(已回源的)原图重建。

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 冷读延迟(尤其 grid 冷开几百张) | 用户看老数据卡 | 预签名直链 + 前端虚拟化/懒加载;后台预取整批;打包冷归档(进阶) |
| 上传 COS 失败/部分失败 | 数据只在本地,误淘汰即丢 | `cos_synced` 标记,**未同步不淘汰**;上传重试 + 对账任务 |
| 本地缓存与 COS 不一致(覆盖/删除未传播) | 看到旧图/孤儿对象 | `delete`/overwrite 同步删 COS;定期对账(DB↔COS↔本地三方) |
| COS 凭证泄露 | 数据安全 | 凭证仅后端环境变量;预签名短 TTL、最小权限子账号 |
| 费用:海量小对象 + 冷开高频 GET | 成本/限流 | 监控请求数;必要时按批打包、加 CDN/就近域名 |
| SQLite 单点(元数据不在 COS) | 机器坏=元数据丢 | 定期快照 DB 到 COS;远期迁 Postgres |
| 对比冷数据要拉两整批原图 | 慢、占带宽 | 后台任务 + 进度;算完即可按期淘汰原图、保留热力图 |
| 改动面大(读写/对比/清理全过 storage) | 回归风险 | `COS_ENABLED` 开关灰度;storage 层加单测;保留纯本地模式 |

## 8. 分阶段落地

1. **抽象先行**:落 `app/storage.py`,把上传/服务/对比/清理全部改成走它,但**后端实现仍是本地磁盘**(行为不变、加测试)。这步零风险,为接 COS 铺路。
2. **接 COS(双写)**:`put` 同时写本地+COS;读仍本地优先。加迁移脚本把存量上云。`cos_synced` 标记。
3. **开启淘汰**:超期本地缓存删除,读未命中走 `ensure_local` 回源。冷读跑通。
4. **优化冷读**:冷图预签名直链 / 前端虚拟化;按需做按批打包与 DB 快照备份。

## 9. 影响的文件(预估)

- 新增:`app/storage.py`(抽象层)、`app/migrate_to_cos.py`、`app/evict_cache.py`、`tests/test_storage.py`。
- 改:`app/main.py`(`/images` 服务改缓存感知或预签名、`/thumb`、upload、删除/overwrite 同步 COS)、`app/service.py`+`app/compare.py`(读原图前 `ensure_local`)、`app/cleanup.py`(与 evict 协作)、`app/models.py`(+`cos_synced`)、`app/db.py`/配置(COS env、CACHE_DIR)、`requirements.txt`(cos sdk)。
- 文档:README / 使用文档 的「存储/部署」小节。

## 10. 你需要提供什么(对接清单)

### A. COS 接入信息(必需,缺了没法连)
- [ ] **Bucket 名**(通常带 appid 后缀,如 `xxx-1257943044`)
- [ ] **Region**(如 `ap-chongqing`)
- [ ] **SecretId / SecretKey** —— 建议给**专用子账号**,权限**只**限这个 bucket(最小权限),不要主账号密钥
- [ ] **内网域名**(后端上传/回源用,如 `{bucket}.cos-internal.{region}.tencentcos.cn`)
- [ ] **公网域名 / CDN 域名**(仅当"浏览器直连下载冷图"时需要;走后端代理则不需要)
- [ ] **专用路径前缀**(建议给一个做隔离,如 `pixelcomparison/`)

### B. 网络事实(决定架构,必答)
- [ ] **后端部署机与 COS 是否同云/同内网?**(能否用 `cos-internal` 内网域名直传)
- [ ] **最终用户浏览器能否访问 COS 公网/CDN 域名?**
  - 能 → 冷图用**预签名直链**(性能最好);不能(纯内网) → 冷图走**后端代理拉取**(则无需公网域名)

### C. 需要拍板的决策
- [ ] 本地热缓存**保留期**(默认 **14 天**?);冷读回填的旧图再缓存多久(如 2 天)
- [ ] 冷图服务方式:**预签名直链** / **后端代理**(取决于 B)
- [ ] 对象粒度:**每张一对象**(推荐先这样) / 每批次打包
- [ ] **热力图是否上 COS**(建议是;缩略图不上)
- [ ] **SQLite 元数据库是否定期备份到 COS**(防机器损坏丢元数据)

### D. 部署 / 运维(确认即可)
- [ ] 密钥经部署机**环境变量**注入(谁来配);**绝不**写进代码/git
- [ ] 存量数据(当前约 **271MB / 1072 张**)一次性迁移到 COS 的**时间窗口**(迁移期尽量别同时上报)

> **最小启动集**:给齐 **A** + 回答 **B**,即可落地阶段 ①②(抽象层 + 接 COS 双写 + 迁移);C/D 可边做边定。
> **建议**:先开一个**测试 bucket / 测试前缀**给我连通验证,跑通再切正式。

## 11. 其它待定参数
- COS SDK 已定为官方 `qcloud_cos`(见「参考实现」)。
