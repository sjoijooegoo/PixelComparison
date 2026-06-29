"""维护工具:删除磁盘上无对应数据库记录的截图/热力图文件。

用法(在 backend/ 目录):
    .venv\\Scripts\\python -m app.cleanup --dry-run   # 只列出,不删除
    .venv\\Scripts\\python -m app.cleanup             # 实际删除

注意:这是手动/定时运行的维护脚本,不要在上传/对比进行时运行。
"""
from __future__ import annotations

import shutil
import sys
import time

from sqlalchemy import select

from .db import IMAGES_DIR, SessionLocal
from .models import Batch, Comparison, Screenshot

# 缩略图是可重建的派生缓存:超过此天数「未被访问」(mtime)即淘汰,下次看列表图自动重生成
THUMBNAIL_RETENTION_DAYS = 60


def find_orphans(db) -> dict[str, list]:
    """返回需要清理的孤儿路径(尚未删除)。"""
    batches_dir = IMAGES_DIR / "batches"
    heat_dir = IMAGES_DIR / "heatmaps"
    thumb_dir = IMAGES_DIR / "thumbs"

    live_batch_ids = set(db.scalars(select(Batch.id)))
    live_comparison_ids = {str(cid) for cid in db.scalars(select(Comparison.id))}
    shot_paths = list(db.scalars(select(Screenshot.path)))
    live_shot_paths = {str((IMAGES_DIR / p).resolve()) for p in shot_paths}
    # 每张存活截图对应的合法缩略图路径(thumbs/<原路径>.webp)
    live_thumb_paths = {
        str((thumb_dir / p).with_suffix(".webp").resolve()) for p in shot_paths
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

    # 3) thumbs/**:缩略图是派生缓存,对应原图(存活截图)不存在的即孤儿
    if thumb_dir.is_dir():
        for f in thumb_dir.rglob("*"):
            if f.is_file() and str(f.resolve()) not in live_thumb_paths:
                orphan_files.append(f)

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


def prune_thumbnails(days: int = THUMBNAIL_RETENTION_DAYS, dry_run: bool = False) -> int:
    """删除 thumbs/ 下「mtime 早于 days 天」的缩略图缓存,并清掉随之变空的目录。

    缩略图是纯派生缓存(原图仍在则可由 /thumb 端点按需重建),删除无损;
    /thumb 命中缓存时会刷新 mtime,因此这里的「mtime 旧」近似「久未被访问」。
    返回删除的文件数。
    """
    thumb_dir = IMAGES_DIR / "thumbs"
    if not thumb_dir.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for f in thumb_dir.rglob("*.webp"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                print(("[dry-run] " if dry_run else "") + f"rm thumb {f}")
                if not dry_run:
                    f.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    if not dry_run:   # 自底向上清空目录(rmdir 仅在目录为空时成功)
        for d in sorted((p for p in thumb_dir.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
    return removed


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    db = SessionLocal()
    try:
        result = prune_orphans(db, dry_run=dry_run)
    finally:
        db.close()
    thumbs = prune_thumbnails(dry_run=dry_run)
    print(f"{'would remove' if dry_run else 'removed'}: "
          f"{result['dirs']} dir(s), {result['files']} file(s), "
          f"{thumbs} stale thumb(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
