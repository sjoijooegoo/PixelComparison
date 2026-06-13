# 上报数据包(mock_uploads)

模拟采集模块(渲染农场 / CI)向平台上报的数据格式与示例。可用于联调上报流程、
填充演示数据。

## 数据包结构

每个批次是一个独立目录,**目录名即批次 ID**:

```
<批次ID>/
  manifest.json        批次元信息 + 场景清单
  images/
    01_废弃都市_广场_昼.png
    02_废弃都市_街道_夜.png
    ...
```

## manifest.json 格式

```json
{
  "format_version": 1,
  "captured_at": "2024-06-01T10:00:00",
  "engine_version": "UE5.3",
  "resolution": "1920x1080",
  "batch": {
    "id": "20240601_1000",
    "project": "Project_Starfall",
    "branch": "release/1.3.0",
    "platform": "Windows",
    "creator": "render-farm-ci"
  },
  "scenes": [
    {
      "name": "01_废弃都市_广场_昼",
      "image": "images/01_废弃都市_广场_昼.png",
      "area": "废弃都市",
      "time_of_day": "昼"
    }
  ]
}
```

字段说明:

| 字段 | 说明 |
|---|---|
| `batch` | 直接对应 `POST /api/batches` 的请求体(id/project/branch/platform/creator) |
| `scenes[].name` | 场景名,**唯一配对键**,两批对比时按它配对;前后版本必须一致 |
| `scenes[].image` | 截图相对路径(相对数据包根目录) |
| `captured_at` / `engine_version` / `resolution` / `scenes[].area` 等 | 采集端附带的元信息,当前上报接口未消费,留作扩展 |

> 上报接口只消费 `batch` 段与每个场景的 `name` + 图片文件;其余字段可按需扩展后端。

## 生成与上报

```powershell
# 1. 生成数据包(需后端 venv,内含 Pillow/numpy)
backend\.venv\Scripts\python mock_uploads\generate.py

# 2. 启动后端后,上报到平台
python mock_uploads\upload.py                 # 上报全部批次包
python mock_uploads\upload.py 20240601_1000   # 仅上报指定批次
```

`upload.py` 仅用标准库拼装 multipart,无需安装 requests。上报后在「批次管理」
页可见这两批,选其一为「对比批次」、另一为「基线批次」即可发起对比。

## 示例数据说明

内置 7 批,覆盖多种对比场景。差异类型:噪声=警告级(约 1.8%)、大幅楼体位移=失败级(约 6%)。

| 批次 | 项目 | 分支 | 平台 | 场景 | 说明 |
|---|---|---|---|---|---|
| `20240601_1000` | Starfall | release/1.3.0 | Windows | 8 | 干净基线 |
| `20240608_1600` | Starfall | release/1.3.1 | Windows | 8 | 回归:2 失败 + 2 警告 |
| `20240601_1030` | Starfall | release/1.3.0 | PS5 | 8 | 干净基线 |
| `20240608_1630` | Starfall | release/1.3.1 | PS5 | 8 | 回归:1 失败 + 1 警告 |
| `20240615_0900` | Starfall | release/1.3.2 | Windows | 8 | 删场景 07、增场景 09 |
| `20240610_1100` | Nebula | develop | Windows | 4 | 干净基线 |
| `20240614_1100` | Nebula | develop | Windows | 4 | 回归:1 失败 + 1 警告 |

推荐对比组合(对比批次 vs 基线批次):

- `20240608_1600` vs `20240601_1000` — Windows 回归,通过/警告/失败混合
- `20240608_1630` vs `20240601_1030` — PS5 回归
- `20240615_0900` vs `20240601_1000` — 演示**新增**(09)与**缺失**(07)场景
- `20240614_1100` vs `20240610_1100` — 另一个项目(Nebula)的回归

不同平台 / 不同项目的批次不能互比(界面会拦截),可用左侧筛选按项目、平台、分支过滤。
