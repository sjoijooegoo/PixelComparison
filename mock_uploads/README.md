# 示例上报数据包

`mock_uploads` 保存可重复生成的演示数据包，用于验证 manifest 解析、批次上报、截图配对、跨平台比较以及新增/缺失检查点。

生产接入请阅读[数据上报接入指南](../docs/上报接入指南.md)。这里的 `upload.py` 是演示工具，不是完整 CI 客户端。

## 目录结构

每个数字目录代表一个批次：

```text
mock_uploads/
  7/
    manifest.json
    Screenshot/
      01_废弃都市_广场_昼.png
      ...
  8/
    manifest.json
    Screenshot/
      ...
```

数据包必须包含：

- `manifest.json`：批次元数据和截图清单。
- `Screenshot/`：manifest 中 `screenshots[].image` 指向的图片。

## manifest 示例

```json
{
  "format_version": 1,
  "capture_type": "levelsequence",
  "pipeline_data": {
    "batch_id": "7",
    "batch_url": "https://ci.example/pipeline/7",
    "captured_at": "2024-06-01T10:00:00",
    "overwrite": false
  },
  "ue_data": {
    "world_name": "Lv_Starfall",
    "platform": "WindowsEditor",
    "p4_version": "251200",
    "shading_quality": 5,
    "resolution": { "width": 1920, "height": 1080 },
    "levelsequence_name": "Seq_Lv_Starfall",
    "levelsequence_path": "/Game/Cinematics/Seq_Lv_Starfall.Seq_Lv_Starfall"
  },
  "screenshots": [
    {
      "index": 0,
      "name": "01_废弃都市_广场_昼",
      "image": "Screenshot/01_废弃都市_广场_昼.png",
      "camera": {
        "location": { "x": -46087.0, "y": -27893.0, "z": -4280.0 },
        "rotation": { "pitch": -28.6, "yaw": 3.7, "roll": 0.0 }
      }
    }
  ]
}
```

重要字段：

| 字段 | 用途 |
|---|---|
| `pipeline_data.batch_id` | 批次 ID |
| `pipeline_data.batch_url` | 流水线链接 |
| `pipeline_data.captured_at` | 批次创建时间 |
| `pipeline_data.overwrite` | 同号时是否删旧建新 |
| `ue_data.world_name` | 场景 ID；同场景才能比较 |
| `ue_data.platform` | 上报平台，后端负责归一化 |
| `ue_data.p4_version` | P4 changelist，可省略 |
| `ue_data.shading_quality` | 画质档位 0–5 |
| `screenshots[].name` | 检查点配对键 |
| `screenshots[].image` | 相对数据包目录的图片路径 |
| `screenshots[].index` | 帧序 |
| `screenshots[].camera` | 相机位姿 |

## 生成示例包

生成器依赖后端环境中的 Pillow 和 NumPy：

```powershell
backend\.venv\Scripts\python mock_uploads\generate.py
```

命令会重建 7–13 号示例包中的 manifest 和截图，不会修改后端数据库。

## 上传示例包

先启动后端 8020：

```powershell
python mock_uploads\upload.py
```

只上传指定批次：

```powershell
python mock_uploads\upload.py 7
python mock_uploads\upload.py 7 8 11
```

指定远程后端：

```powershell
$env:BASE = "http://10.30.129.32:8020"
python mock_uploads\upload.py 7
```

脚本只依赖 Python 标准库，执行“创建批次 → 逐张上传截图”。批次已存在时继续补传；manifest 中 `overwrite=true` 时会请求覆盖。脚本不会自动发起对比，也没有完整的重试和 CI 退出码设计。

## 示例批次

| 批次 | 场景 | P4 | 平台上报值 | 检查点 | 目的 |
|---:|---|---:|---|---:|---|
| 7 | Lv_Starfall | 251200 | WindowsEditor | 8 | Windows 基线 |
| 8 | Lv_Starfall | 251640 | WindowsEditor | 8 | 失败和警告混合 |
| 9 | Lv_Starfall | 251205 | IOSEditor | 8 | iOS 基线 |
| 10 | Lv_Starfall | 251645 | IOSEditor | 8 | iOS 回归 |
| 11 | Lv_Starfall | 252180 | WindowsEditor | 8 | 新增 09、缺失 07 |
| 12 | Lv_Nebula | 251800 | AndroidEditor | 4 | Android 基线 |
| 13 | Lv_Nebula | 252100 | AndroidEditor | 4 | Android 回归 |

推荐组合：

- 8 对 7：同平台常规回归。
- 10 对 9：iOS 回归。
- 11 对 7：新增和缺失检查点。
- 13 对 12：另一个场景的回归。
- 8 对 9：同场景跨平台比较。

不同场景 ID 的批次不能比较。
