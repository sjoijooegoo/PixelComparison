"""从当前 SceneScope 后端数据目录导出一个缩略图热力图离线包。"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.gpm_offline_package import build_offline_package  # noqa: E402
from app.gpm_configuration_package import export_configuration_package, remove_transfer  # noqa: E402
from app.gpm_offline_format import CONFIGURATION_FILENAME  # noqa: E402
from app.gpm_common import safe_segment  # noqa: E402


def _publish(target: Path, content: bytes) -> None:
    """同目录原子替换，运行中的查看器不会扫描到尚未写完的包。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".offline-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 SceneScope 热力图缩略图离线包")
    parser.add_argument("batch_id", nargs="?", help="要导出的采集批次 ID；仅更新配置时可省略")
    parser.add_argument("--branch", default="main", help="分支，默认 main")
    parser.add_argument("--output", type=Path, default=Path.cwd(), help="离线工作区根目录，内部使用 config/ 和 data/")
    parser.add_argument("--export-config", action="store_true", help="导出或更新唯一共享配置；日常批次导出无需此参数")
    args = parser.parse_args()

    if not args.batch_id and not args.export_config:
        parser.error("请提供 batch_id 或 --export-config")
    if args.output.suffix.lower() == ".ssheat":
        parser.error("--output 现在接受工作区目录，不再接受 .ssheat 文件路径")
    if args.export_config:
        source, _ = export_configuration_package("all")
        try:
            target = args.output / "config" / CONFIGURATION_FILENAME
            _publish(target, source.read_bytes())
        finally:
            remove_transfer(source)
        print(f"共享配置已导出：{target.resolve()}")
    if not args.batch_id:
        return 0

    content, manifest = build_offline_package(args.batch_id, args.branch)
    branch = safe_segment(manifest["upload"]["branch_tag"], "main")
    batch = safe_segment(manifest["upload"]["batch_id"], "batch")
    target = args.output / "data" / f"SceneScope-heatmap-{branch}-{batch}.ssheat"
    _publish(target, content)
    point_count = sum(int(item["point_count"]) for item in manifest["maps"])
    print(f"已导出：{target.resolve()}")
    print(f"地图：{len(manifest['maps'])}，点位：{point_count}，图片模式：缩略图")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
