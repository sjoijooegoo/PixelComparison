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
    "id": "7",
    "scene_id": "Lv_Starfall",
    "p4_version": 251200,
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
| `batch` | 直接对应 `POST /api/batches` 的请求体(id/scene_id/p4_version/platform/creator) |
| `batch.scene_id` | 场景 ID(UE Level),**同场景才能对比** |
| `batch.p4_version` | P4 changelist 整数,越大越新 |
| `scenes[].name` | 点位名,**唯一配对键**,两批对比时按它配对;前后版本必须一致 |
| `scenes[].image` | 截图相对路径(相对数据包根目录) |
| `captured_at` / `engine_version` / `resolution` / `scenes[].area` 等 | 采集端附带的元信息,当前上报接口未消费,留作扩展 |

> 上报接口只消费 `batch` 段与每个场景的 `name` + 图片文件;其余字段可按需扩展后端。

## 生成与上报

```powershell
# 1. 生成数据包(需后端 venv,内含 Pillow/numpy)
backend\.venv\Scripts\python mock_uploads\generate.py

# 2. 启动后端后,上报到平台
python mock_uploads\upload.py        # 上报全部批次包
python mock_uploads\upload.py 7      # 仅上报指定批次(目录名/批次 ID)
```

`upload.py` 仅用标准库拼装 multipart,无需安装 requests。上报后在「批次管理」
页可见这些批次,选两个**同场景ID**的批次(对比批次 / 基线批次)即可发起对比。

> 注:种子数据(`app.seed`)占用批次 ID 1–6,故 mock 数据从 7 开始,目录名即批次 ID。

## 示例数据说明

内置 7 批,覆盖多种对比场景。差异类型:噪声=警告级(约 1.8%)、大幅楼体位移=失败级(约 6%)。

| 批次 | 场景ID | P4 版本 | 平台 | 点位 | 说明 |
|---|---|---|---|---|---|
| `7`  | Lv_Starfall | 251200 | Windows | 8 | 干净基线 |
| `8`  | Lv_Starfall | 251640 | Windows | 8 | 回归:2 失败 + 2 警告 |
| `9`  | Lv_Starfall | 251205 | iOS | 8 | 干净基线 |
| `10` | Lv_Starfall | 251645 | iOS | 8 | 回归:1 失败 + 1 警告 |
| `11` | Lv_Starfall | 252180 | Windows | 8 | 删点位 07、增点位 09 |
| `12` | Lv_Nebula | 251800 | Android | 4 | 干净基线 |
| `13` | Lv_Nebula | 252100 | Android | 4 | 回归:1 失败 + 1 警告 |

推荐对比组合(对比批次 vs 基线批次):

- `8` vs `7` — Lv_Starfall 回归,通过/警告/失败混合
- `10` vs `9` — Lv_Starfall(iOS)回归
- `11` vs `7` — 演示**新增点位**(09)与**缺失点位**(07)
- `13` vs `12` — Lv_Nebula 回归
- `8` vs `9` — 跨平台同场景(Windows × iOS)也可对比

不同场景ID的批次不能互比(界面会拦截);可用左侧筛选按场景ID、平台、P4 版本范围过滤。
