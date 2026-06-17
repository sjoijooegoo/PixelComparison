"""维护工具:删除磁盘上无对应数据库记录的截图/热力图文件。

用法(在 backend/ 目录):
    .venv\\Scripts\\python -m app.cleanup --dry-run   # 只列出,不删除
    .venv\\Scripts\\python -m app.cleanup             # 实际删除

注意:这是手动/定时运行的维护脚本,不要在上传/对比进行时运行。
"""
from __future__ import annotations

import shutil
import sys

from sqlalchemy import select

from .db import IMAGES_DIR, SessionLocal
from .models import Batch, Comparison, Screenshot


def find_orphans(db) -> dict[str, list]:
    """返回需要清理的孤儿路径(尚未删除)。"""
    batches_dir = IMAGES_DIR / "batches"
    heat_dir = IMAGES_DIR / "heatmaps"

    live_batch_ids = set(db.scalars(select(Batch.id)))
    live_comparison_ids = {str(cid) for cid in db.scalars(select(Comparison.id))}
    live_shot_paths = {
        str((IMAGES_DIR / p).resolve())
        for p in db.scalars(select(Screenshot.path))
    }

    orphan_dirs: list = []
    orphan_files: list = []

    # 1) batches/<batch_id> 目录:批次已不存在 -> 整个目录孤儿
    if batches_dir.is_dir():
        for d in batches_dir.iterdir():
            if d.is_dir() and d.name not in live_batch_ids:
                orphan_dirs.append(d)
            elif d.is_dir():
                for f in d.iterdir():
                    if f.is_file() and str(f.resolve()) not in live_shot_paths:
                        orphan_files.append(f)

    # 2) heatmaps/<comparison_id> 目录:对比已不存在 -> 整个目录孤儿
    if heat_dir.is_dir():
        for d in heat_dir.iterdir():
            if d.is_dir() and d.name not in live_comparison_ids:
                orphan_dirs.append(d)

    return {"dirs": orphan_dirs, "files": orphan_files}


def prune_orphans(db, dry_run: bool = False) -> dict[str, int]:
    found = find_orphans(db)
    for d in found["dirs"]:
        print(("[dry-run] " if dry_run else "") + f"rm dir  {d}")
        if not dry_run:
            shutil.rmtree(d, ignore_errors=True)
    for f in found["files"]:
        print(("[dry-run] " if dry_run else "") + f"rm file {f}")
        if not dry_run:
            f.unlink(missing_ok=True)
    return {"dirs": len(found["dirs"]), "files": len(found["files"])}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    db = SessionLocal()
    try:
        result = prune_orphans(db, dry_run=dry_run)
    finally:
        db.close()
    print(f"{'would remove' if dry_run else 'removed'}: "
          f"{result['dirs']} dir(s), {result['files']} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
