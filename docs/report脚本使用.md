# report.py 上报脚本使用说明

`report.py` 是采集端 / CI 用来把一次采集结果上报到 PixelComparison 后端的脚本。
**只依赖 Python 标准库**(无需 `pip install` 任何东西),可整文件拷到采集机器上直接用。

它做三件事:

1. `POST /api/batches` —— 用 `manifest.json` 里的 `pipeline_data` + `ue_data` 建批次
2. `POST /api/batches/{id}/screenshots` —— 逐张上传截图(带相机位姿 / 帧序,失败自动重试 3 次)
3. `POST /api/batches/{id}/auto-compare` —— 上传完成后,自动与「同场景 + 同平台 + 同画质」的最新历史批次对比(可关)

---

## 1. 前置:数据包结构

脚本的入参是一个**数据包目录**(或直接指向其中的 `manifest.json`)。目录结构:

```
<批次包>/
  manifest.json          批次元信息 + 截图清单
  Screenshot/
    01_xxx.png
    02_xxx.png
    ...
```

`manifest.json` 字段与平台字段的映射见 [上报接入指南.md](上报接入指南.md) 与 [mock_uploads/README.md](../mock_uploads/README.md)。
图片路径按 `manifest.json` 所在目录解析相对路径。

---

## 2. 基本调用

```powershell
# 指向含 manifest.json 的目录(最常用)
python report.py "C:\path\to\PixelComparison"

# 或直接指向 manifest.json
python report.py "C:\path\to\PixelComparison\manifest.json"
```

不带后端地址参数时,默认上报到 `http://127.0.0.1:8000`。

---

## 3. 指定后端地址

三选一(任意一种即可):

```powershell
# 方式 A:分别给 IP 和端口
python report.py ./pkg --host 10.30.129.32 --port 8000

# 方式 B:给完整地址(--base 省略 http:// 也可)
python report.py ./pkg --base http://10.30.129.32:8000
python report.py ./pkg --base 10.30.129.32:8000

# 方式 C:环境变量(BASE 优先,其次 HOST/PORT)
$env:BASE = "http://10.30.129.32:8000"; python report.py ./pkg
```

优先级:`--base` > `--host/--port` > 环境变量 `BASE`/`HOST`/`PORT` > 默认 `127.0.0.1:8000`。

---

## 4. 覆盖同号批次:`--overwrite`

批次号已存在时,**默认**会继续补传截图(同名截图跳过);加 `--overwrite` 则**删旧建新**——
清除旧批次的截图、它参与的对比 / 对比项、由它晋升的基线、热力图文件,再用本次数据重建。

```powershell
python report.py ./pkg --overwrite
```

也可以在 `manifest.json` 里写(让采集端决定,不必每次加参数):

```json
{ "pipeline_data": { "id": "7", "overwrite": true }, "ue_data": { } }
```

> `--overwrite` 优先级高于 manifest 字段;加了它就强制覆盖。
> 覆盖是**破坏性**操作;若该批次正参与「计算中的对比」,后端返回 409,稍后再覆盖即可。

---

## 5. 命令行覆盖批次字段:`--batch_id` / `--batch_url` / `--p4version`

不改 `manifest.json` 也能在上报时指定/覆盖这几个字段(**命令行优先于 manifest**):

```powershell
python report.py ./pkg --batch_id 88                    # 指定批次号
python report.py ./pkg --p4version 251200               # 指定 P4 版本(整数)
python report.py ./pkg --batch_url https://ci/exec/123  # 指定流水线链接
python report.py ./pkg --batch_id 88 --p4version 251200 --batch_url https://ci/exec/123
```

- `--batch_id`:批次号;不给则用 manifest 里的,manifest 也没有则由后端自增。
- `--p4version`:P4 changelist(整数)。
- `--batch_url`:批次列表里批次号的超链接地址。
- 未给的字段保持用 manifest 的值。常与 `--overwrite` 搭配(同一批次号重跑覆盖)。

---

## 6. 关闭自动对比:`--no-auto-compare`

默认上传完成(且无失败)后会自动找「同场景 + 同平台 + 同画质」的最新历史批次发起对比。
只想上传、不想自动对比时:

```powershell
python report.py ./pkg --no-auto-compare
```

---

## 7. 参数一览

| 参数 | 说明 |
|---|---|
| `manifest`(位置参数) | `manifest.json` 路径,或其所在目录 |
| `--host` | 后端 IP / 主机名(默认 `127.0.0.1`,或读环境变量 `HOST`) |
| `--port` | 后端端口(默认 `8000`,或读环境变量 `PORT`) |
| `--base` | 后端完整地址,如 `http://10.30.129.32:8000`;给了则忽略 `--host/--port` |
| `--batch_id` | 批次号,覆盖 manifest 的批次号(不给则用 manifest 或后端自增) |
| `--batch_url` | 流水线/构建链接,覆盖 manifest 的 `batch_url` |
| `--p4version` | P4 版本号(整数),覆盖 manifest 的 `p4_version` |
| `--overwrite` | 批次号已存在时覆盖重建(删旧建新),而非补传 |
| `--no-auto-compare` | 上传完成后不自动与历史批次对比 |

---

## 8. 退出码与输出

- 退出码 `0` —— 全部截图上传成功(自动对比失败不影响退出码,仅打印提示)
- 退出码 `1` —— 建批次失败,或有截图上传失败
- 退出码 `2` —— 无法连接后端

行为细节:
- 建批次返回 `409`(同号已存在且未覆盖)时,脚本继续补传截图,**不算失败**;同名截图后端返回 `409`,脚本按「已传过」计为成功。
- 单张截图遇网络错误 / `5xx` 会**退避重试,最多 3 次**;`4xx`(如 `409`)不重试。

---

## 9. 常见用法速查

```powershell
# 本机后端,标准上报 + 自动对比
python report.py ./pkg

# 远程后端
python report.py ./pkg --base http://10.30.129.32:8000

# 命令行指定批次号 / P4 / 链接(覆盖 manifest)
python report.py ./pkg --batch_id 88 --p4version 251200 --batch_url https://ci/exec/123

# 重新上报、覆盖旧批次(常用于同一批次号重跑采集)
python report.py ./pkg --base http://10.30.129.32:8000 --overwrite

# 只上传,不自动对比
python report.py ./pkg --no-auto-compare
```
