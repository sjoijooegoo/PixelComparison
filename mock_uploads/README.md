# 上报数据包(mock_uploads)

模拟采集模块(UE 客户端 / 渲染农场 / CI)向平台上报的数据格式与示例。可用于联调
上报流程、填充演示数据。格式与真实 UE 客户端产出的
`…/Saved/PixelComparison/manifest.json` 一致。

## 数据包结构

每个批次是一个独立目录,**目录名即批次 ID**:

```
<批次ID>/
  manifest.json          批次元信息(pipeline_data + ue_data)+ 截图清单
  Screenshot/
    01_废弃都市_广场_昼.png
    02_废弃都市_街道_夜.png
    ...
```

## manifest.json 格式(新版)

```json
{
  "format_version": 1,
  "capture_type": "levelsequence",
  "pipeline_data": {
    "batch_id": "7",
    "batch_url": "https://devops.woa.com/.../executeDetail",
    "captured_at": "2024-06-01T10:00:00"
  },
  "ue_data": {
    "levelsequence_path": "/Game/Cinematics/Seq_Lv_Starfall.Seq_Lv_Starfall",
    "levelsequence_name": "Seq_Lv_Starfall",
    "world_name": "Lv_Starfall",
    "platform": "WindowsEditor",
    "p4_version": "251200",
    "resolution": { "width": 1920, "height": 1080 }
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

字段说明 / 与平台字段的映射:

| manifest 路径 | 平台字段 | 说明 |
|---|---|---|
| `pipeline_data.batch_id` | `Batch.id` | 批次号 |
| `pipeline_data.batch_url` | `Batch.batch_url` | 真实流水线链接(批次ID超链接用它,旧数据回退占位地址) |
| `pipeline_data.captured_at` | `Batch.created_at` | 采集时间(ISO8601) |
| `ue_data.world_name` | `Batch.scene_id` | 场景 ID(UE Level),**同场景才能对比** |
| `ue_data.platform` | `Batch.platform` | **归一化**:WindowsEditor→Windows、IOSEditor→iOS、AndroidEditor→Android |
| `ue_data.p4_version` | `Batch.p4_version` | P4 changelist(字符串,后端转 int,越大越新;**可省略**) |
| `ue_data.shading_quality` | `Batch.shading_quality` | 画质档位 0–5(节能/流畅/均衡/精美/极致/电影),缺省按「极致」 |
| `ue_data.resolution` | `Batch.resolution` | 存为 `1920x1080` |
| `ue_data.levelsequence_name/path` | `Batch.levelsequence_name/path` | LevelSequence 身份 |
| `capture_type` | `Batch.capture_type` | 采集类型,如 `levelsequence` |
| `screenshots[].name` | `Screenshot.scene_name` | **唯一配对键**,两批对比按它配对;前后版本必须一致 |
| `screenshots[].image` | 上传的图片文件 | 相对数据包根目录(含 `Screenshot/` 子目录) |
| `screenshots[].index` | `Screenshot.frame_index` | 帧序 |
| `screenshots[].camera` | `Screenshot.camera` | 相机位姿(location/rotation),对比详情页展示 |

## 生成与上报

```powershell
# 1. 生成数据包(需后端 venv,内含 Pillow/numpy)
backend\.venv\Scripts\python mock_uploads\generate.py

# 2. 启动后端后,上报到平台
python mock_uploads\upload.py        # 上报全部批次包
python mock_uploads\upload.py 7      # 仅上报指定批次(目录名/批次 ID)
```

`upload.py` 仅用标准库拼装 multipart,无需安装 requests;它从 `pipeline_data` /
`ue_data` 拼出建批次请求,并逐张上传截图(带 `camera` / `frame_index`)。

> 注:种子数据(`app.seed`)占用批次 ID 1–6,故 mock 数据从 7 开始,目录名即批次 ID。

## 示例数据说明

内置 7 批,覆盖多种对比场景。差异类型:噪声=警告级(约 1.8%)、大幅楼体位移=失败级(约 6%)。

| 批次 | 场景ID | P4 版本 | 平台(上报值) | 检查点 | 说明 |
|---|---|---|---|---|---|
| `7`  | Lv_Starfall | 251200 | WindowsEditor | 8 | 干净基线 |
| `8`  | Lv_Starfall | 251640 | WindowsEditor | 8 | 回归:2 失败 + 2 警告 |
| `9`  | Lv_Starfall | 251205 | IOSEditor | 8 | 干净基线 |
| `10` | Lv_Starfall | 251645 | IOSEditor | 8 | 回归:1 失败 + 1 警告 |
| `11` | Lv_Starfall | 252180 | WindowsEditor | 8 | 删检查点 07、增检查点 09 |
| `12` | Lv_Nebula | 251800 | AndroidEditor | 4 | 干净基线 |
| `13` | Lv_Nebula | 252100 | AndroidEditor | 4 | 回归:1 失败 + 1 警告 |

> 平台列是 manifest 中的上报值(带 `Editor` 后缀);入库后会归一化为 Windows/iOS/Android。

推荐对比组合(对比批次 vs 基线批次):

- `8` vs `7` — Lv_Starfall 回归,通过/警告/失败混合
- `10` vs `9` — Lv_Starfall(iOS)回归
- `11` vs `7` — 演示**新增检查点**(09)与**缺失检查点**(07)
- `13` vs `12` — Lv_Nebula 回归
- `8` vs `9` — 跨平台同场景(Windows × iOS)也可对比

不同场景ID的批次不能互比(界面会拦截);可用顶部筛选按场景ID、画质、创建时间过滤。
