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

内置两批 8 场景、同平台(Windows)同项目的数据:

- `20240601_1000`(release/1.3.0)— 干净渲染
- `20240608_1600`(release/1.3.1)— 其中 4 个场景引入差异(2 个楼体位移=失败级、
  2 个噪声=警告级),其余与上一批一致

把这两批互相对比,可看到混合了通过 / 警告 / 失败的真实结果。
