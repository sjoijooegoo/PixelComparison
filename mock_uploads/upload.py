"""读取上报数据包并通过 API 上报到平台(新版 manifest 格式)。

对每个批次包:
    1. POST /api/batches                     用 pipeline_data + ue_data 建批次
    2. POST /api/batches/{id}/screenshots    逐张上传 screenshots(带相机位姿/帧序)

仅依赖标准库(自行拼装 multipart),无需安装 requests。

用法:
    python mock_uploads/upload.py                 # 上报本目录下所有批次包
    python mock_uploads/upload.py 7               # 仅上报指定批次
    BASE=http://host:8000 python mock_uploads/upload.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = os.environ.get("BASE", "http://127.0.0.1:8000")


def post_json(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")


def _field(name: str, value: str, boundary: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def post_screenshot(url: str, scene_name: str, image_path: Path,
                    camera: dict | None = None, frame_index=None):
    boundary = uuid.uuid4().hex
    parts = [_field("scene_name", scene_name, boundary)]
    if camera is not None:
        parts.append(_field("camera", json.dumps(camera, ensure_ascii=False), boundary))
    if frame_index is not None:
        parts.append(_field("frame_index", str(frame_index), boundary))
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{image_path.name}"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode("utf-8")
    )
    parts.append(image_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def build_batch_body(manifest: dict) -> dict:
    """从新版 manifest 的 pipeline_data + ue_data 拼出 POST /api/batches 请求体。"""
    pipeline = manifest.get("pipeline_data") or {}
    ue = manifest["ue_data"]
    res = ue.get("resolution") or {}
    resolution = (
        f"{res['width']}x{res['height']}" if res.get("width") and res.get("height") else None
    )
    # 兼容字段命名:新版用 id/url,旧版用 batch_id/batch_url
    batch_id = pipeline.get("id") or pipeline.get("batch_id")
    batch_url = pipeline.get("url") or pipeline.get("batch_url")
    p4_raw = ue.get("p4_version")
    return {
        "id": str(batch_id) if batch_id is not None else None,
        "scene_id": ue["world_name"],
        "p4_version": int(p4_raw) if p4_raw not in (None, "") else None,
        "platform": ue["platform"],            # 后端归一化(WindowsEditor→Windows)
        "creator": "render-farm-ci",
        "batch_url": batch_url,
        "resolution": resolution,
        "capture_type": manifest.get("capture_type"),
        "levelsequence_name": ue.get("levelsequence_name"),
        "levelsequence_path": ue.get("levelsequence_path"),
        "shading_quality": ue.get("shading_quality"),
        "captured_at": pipeline.get("captured_at"),  # 新版可能不带,缺省用入库时间
    }


def upload_package(pkg_dir: Path) -> None:
    manifest = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
    batch = build_batch_body(manifest)
    print(f"\n上报批次 {batch['id']} (P4 {batch['p4_version']} / {batch['platform']})")

    status, body = post_json(f"{BASE}/api/batches", batch)
    if status not in (200, 201):
        print(f"  建批次失败: {status} {body}")
        if status != 409:  # 409=已存在,继续补传截图
            return
        print("  批次已存在,继续上传截图…")

    shots = manifest["screenshots"]
    ok = 0
    for s in shots:
        img = pkg_dir / s["image"]
        code = post_screenshot(
            f"{BASE}/api/batches/{batch['id']}/screenshots",
            s["name"], img, camera=s.get("camera"), frame_index=s.get("index"),
        )
        if code in (200, 201):
            ok += 1
        else:
            print(f"  ! {s['name']}: HTTP {code}")
    print(f"  完成: {ok}/{len(shots)} 张截图")


def main() -> None:
    names = sys.argv[1:]
    if names:
        dirs = [ROOT / n for n in names]
    else:
        dirs = [p for p in ROOT.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    if not dirs:
        print("未找到批次包,请先运行 generate.py")
        return
    for d in sorted(dirs):
        upload_package(d)


if __name__ == "__main__":
    main()
