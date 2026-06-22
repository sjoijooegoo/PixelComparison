"""一次性迁移:把存量热力图 PNG 转成 WebP(q90),更新数据库路径并删除旧 PNG。

热力图是纯展示派生物(不参与像素对比),WebP q90 体积约为 PNG 的 1/12、观感无损。
新生成的对比已直接存 WebP;本脚本用于把历史 PNG 回收掉。

用法(在 backend/ 目录):
    .venv\\Scripts\\python -m app.migrate_heatmaps --dry-run   # 只统计,不改动
    .venv\\Scripts\\python -m app.migrate_heatmaps             # 实际转换

注意:这是手动维护脚本,不要在上传/对比进行时运行。
"""
from __future__ import annotations

import sys

from PIL import Image
from sqlalchemy import select

from .cleanup import prune_orphans
from .compare import HEATMAP_WEBP_QUALITY
from .db import IMAGES_DIR, SessionLocal
from .models import ComparisonItem


def migrate(db, dry_run: bool = False) -> dict[str, int]:
    items = db.scalars(
        select(ComparisonItem).where(ComparisonItem.heatmap_path.like("%.png"))
    ).all()
    converted = 0
    freed = 0
    for it in items:
        old = IMAGES_DIR / it.heatmap_path
        if not old.is_file():
            continue
        new_rel = it.heatmap_path[: -len(".png")] + ".webp"
        new = IMAGES_DIR / new_rel
        old_size = old.stat().st_size
        print(("[dry-run] " if dry_run else "") + f"convert {it.heatmap_path} -> {new_rel}")
        if not dry_run:
            with Image.open(old) as im:
                im.convert("RGB").save(new, format="WEBP", quality=HEATMAP_WEBP_QUALITY, method=6)
            new_size = new.stat().st_size
            old.unlink(missing_ok=True)
            it.heatmap_path = new_rel
            freed += old_size - new_size
        converted += 1
    if not dry_run and converted:
        db.commit()
        # 清掉无 DB 记录的遗留热力图/图片孤儿
        pruned = prune_orphans(db)
        print(f"pruned orphans: {pruned['dirs']} dir(s), {pruned['files']} file(s)")
    return {"converted": converted, "freed_mb": round(freed / 1024 / 1024, 1)}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    db = SessionLocal()
    try:
        res = migrate(db, dry_run=dry_run)
    finally:
        db.close()
    print(f"{'would convert' if dry_run else 'converted'}: {res['converted']} 张"
          + (f",回收 {res['freed_mb']} MB" if not dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
