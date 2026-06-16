#!/usr/bin/env python3
"""按 manifest.json 把一次采集结果上报到 PixelComparison 后端。

只依赖 Python 标准库,可整文件拷到采集端使用。

用法:
    python report.py <manifest.json 或其所在目录>
    python report.py C:\\path\\to\\PixelComparison\\manifest.json
    python report.py C:\\path\\to\\PixelComparison          # 目录里需有 manifest.json
    python report.py ./pkg --base http://host:8000          # 指定后端地址
    BASE=http://host:8000 python report.py ./pkg            # 用环境变量指定

流程:
    1) POST /api/batches                    用 pipeline_data + ue_data 建批次
    2) POST /api/batches/{id}/screenshots   逐张上传 screenshots(带相机位姿/帧序)
图片路径相对 manifest.json 所在目录解析。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def post_json(base: str, path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except urllib.error.URLError as e:
        return None, str(e)


def _field(name: str, value: str, boundary: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def post_screenshot(base: str, batch_id: str, scene_name: str, image_path: Path,
                    camera=None, frame_index=None):
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
    req = urllib.request.Request(
        base + f"/api/batches/{batch_id}/screenshots", data=b"".join(parts), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except urllib.error.URLError as e:
        return None, str(e)


def build_batch_body(manifest: dict) -> dict:
    """从 manifest 的 pipeline_data + ue_data 拼出 POST /api/batches 请求体。"""
    pipeline = manifest.get("pipeline_data", {})
    ue = manifest["ue_data"]
    res = ue.get("resolution") or {}
    resolution = (
        f"{res['width']}x{res['height']}" if res.get("width") and res.get("height") else None
    )
    # 兼容字段命名:新版 id/url,旧版 batch_id/batch_url
    batch_id = pipeline.get("id") or pipeline.get("batch_id")
    batch_url = pipeline.get("url") or pipeline.get("batch_url")
    return {
        "id": str(batch_id) if batch_id is not None else None,
        "scene_id": ue["world_name"],
        "p4_version": int(ue["p4_version"]),
        "platform": ue["platform"],            # 后端归一化(WindowsEditor→Windows)
        "creator": manifest.get("creator", "render-farm-ci"),
        "batch_url": batch_url,
        "resolution": resolution,
        "capture_type": manifest.get("capture_type"),
        "levelsequence_name": ue.get("levelsequence_name"),
        "levelsequence_path": ue.get("levelsequence_path"),
        "captured_at": pipeline.get("captured_at"),
    }


def resolve_manifest(arg: str) -> Path:
    p = Path(arg).expanduser()
    if p.is_dir():
        p = p / "manifest.json"
    if not p.is_file():
        raise SystemExit(f"找不到 manifest.json: {p}")
    return p


def report(manifest_path: Path, base: str) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pkg_dir = manifest_path.parent
    body = build_batch_body(manifest)
    shots = manifest.get("screenshots", [])

    print(f"后端: {base}")
    print(f"批次: {body['id']}  场景: {body['scene_id']}  P4: {body['p4_version']}  "
          f"平台: {body['platform']}  截图: {len(shots)}")

    status, resp = post_json(base, "/api/batches", body)
    if status is None:
        print(f"  无法连接后端: {resp}")
        return 2
    if status not in (200, 201):
        if status == 409:
            print("  批次已存在,继续补传截图…")
        else:
            print(f"  建批次失败: HTTP {status} {resp}")
            return 1

    batch_id = body["id"]
    ok = fail = 0
    for s in shots:
        img = (pkg_dir / s["image"]).resolve()
        if not img.is_file():
            print(f"  ! 缺图: {s['image']}")
            fail += 1
            continue
        code, err = post_screenshot(
            base, batch_id, s["name"], img,
            camera=s.get("camera"), frame_index=s.get("index"),
        )
        if code in (200, 201):
            ok += 1
        elif code == 409:
            ok += 1  # 已传过,视为成功
        else:
            print(f"  ! {s['name']}: HTTP {code} {err or ''}")
            fail += 1

    print(f"完成: {ok}/{len(shots)} 张截图" + (f"(失败 {fail})" if fail else ""))
    return 0 if fail == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="按 manifest.json 上报采集结果到 PixelComparison 后端")
    ap.add_argument("manifest", help="manifest.json 文件路径,或其所在目录")
    ap.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8000"),
                    help="后端地址(默认 http://127.0.0.1:8000,或读环境变量 BASE)")
    args = ap.parse_args()
    sys.exit(report(resolve_manifest(args.manifest), args.base.rstrip("/")))


if __name__ == "__main__":
    main()
