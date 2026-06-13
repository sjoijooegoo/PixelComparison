"""读取上报数据包并通过 API 上报到平台。

对每个批次包:
    1. POST /api/batches                     用 manifest.batch 建批次
    2. POST /api/batches/{id}/screenshots    逐张上传 manifest.scenes 中的截图

仅依赖标准库(自行拼装 multipart),无需安装 requests。

用法:
    python mock_uploads/upload.py                 # 上报本目录下所有批次包
    python mock_uploads/upload.py 20240601_1000   # 仅上报指定批次
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


def post_screenshot(url: str, scene_name: str, image_path: Path):
    boundary = uuid.uuid4().hex
    parts = []
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="scene_name"\r\n\r\n'
        f"{scene_name}\r\n".encode("utf-8")
    )
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


def upload_package(pkg_dir: Path) -> None:
    manifest = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
    batch = manifest["batch"]
    print(f"\n上报批次 {batch['id']} ({batch['branch']} / {batch['platform']})")

    status, body = post_json(f"{BASE}/api/batches", batch)
    if status not in (200, 201):
        print(f"  建批次失败: {status} {body}")
        if status != 409:  # 409=已存在,继续补传截图
            return
        print("  批次已存在,继续上传截图…")

    ok = 0
    for scene in manifest["scenes"]:
        img = pkg_dir / scene["image"]
        code = post_screenshot(
            f"{BASE}/api/batches/{batch['id']}/screenshots", scene["name"], img
        )
        if code in (200, 201):
            ok += 1
        else:
            print(f"  ! {scene['name']}: HTTP {code}")
    print(f"  完成: {ok}/{len(manifest['scenes'])} 张截图")


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
