#!/usr/bin/env python3
"""按日期清理旧批次:删除「创建日期早于指定日期」的所有批次。

走后端 DELETE 接口逐个删除(级联清理该批次的截图/对比/对比项/由其晋升的基线/
热力图/缩略图,并触发孤儿文件清理),不直接动 DB 或磁盘,保证一致性。

默认 **dry-run**(只列出不删);确认无误后加 --yes 才真正删除。

用法:
    python cleanup_batches.py --before 2026-06-01                 # 预览将删除哪些(dry-run)
    python cleanup_batches.py --before 2026-06-01 --yes           # 真正删除
    python cleanup_batches.py --before 2026-06-01 --base http://10.30.129.32:8000 --yes
    python cleanup_batches.py --before 2026-06-01 --host 10.30.129.32 --port 8000 --yes

说明:
    --before 2026-06-01 表示删除「2026-06-01 之前(不含当天)」创建的批次,
    即 created_at < 2026-06-01 00:00。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime


def _get(base: str, path: str):
    req = urllib.request.Request(base + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except urllib.error.URLError as e:
        return None, str(e)


def _delete(base: str, batch_id: str):
    req = urllib.request.Request(base + f"/api/batches/{batch_id}", method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except urllib.error.URLError as e:
        return None, str(e)


def _fetch_all_batches(base: str) -> list[dict]:
    """分页拉取全部批次(不带日期筛选)。"""
    items: list[dict] = []
    page, page_size = 1, 200
    while True:
        status, data = _get(base, f"/api/batches?page={page}&page_size={page_size}")
        if status is None:
            raise SystemExit(f"无法连接后端: {data}")
        if status != 200 or not isinstance(data, dict):
            raise SystemExit(f"拉取批次失败: HTTP {status} {data}")
        batch = data.get("items", [])
        items.extend(batch)
        if len(items) >= data.get("total", len(items)) or not batch:
            break
        page += 1
    return items


def _created_date(b: dict) -> date | None:
    s = b.get("created_at")
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def resolve_base(args) -> str:
    base = args.base or f"http://{args.host}:{args.port}"
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base.rstrip("/")


def main() -> None:
    ap = argparse.ArgumentParser(description="按日期清理旧批次(默认 dry-run)")
    ap.add_argument("--before", required=True,
                    help="删除此日期之前(不含当天)创建的批次,格式 YYYY-MM-DD")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", default=os.environ.get("PORT", "8000"))
    ap.add_argument("--base", default=os.environ.get("BASE"),
                    help="后端完整地址,如 http://10.30.129.32:8000;给了则忽略 --host/--port")
    ap.add_argument("--yes", action="store_true", help="确认真正删除(否则只预览)")
    args = ap.parse_args()

    try:
        cutoff = datetime.strptime(args.before, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"--before 日期格式应为 YYYY-MM-DD,收到: {args.before}")

    base = resolve_base(args)
    print(f"后端: {base}")
    print(f"清理目标: created_at < {cutoff}(不含当天)")

    all_batches = _fetch_all_batches(base)
    targets = [b for b in all_batches if (d := _created_date(b)) is not None and d < cutoff]
    targets.sort(key=lambda b: b.get("created_at", ""))

    print(f"总批次: {len(all_batches)};命中(将删除): {len(targets)}")
    for b in targets:
        print(f"  #{b['id']}  {b.get('created_at','?')}  场景={b.get('scene_id','?')}  "
              f"检查点={b.get('scene_count','?')}")

    if not targets:
        print("没有符合条件的批次,无需清理。")
        return
    if not args.yes:
        print(f"\n[dry-run] 以上 {len(targets)} 个批次将被删除。确认无误后加 --yes 执行。")
        return

    ok = fail = 0
    for b in targets:
        code, err = _delete(base, str(b["id"]))
        if code in (200, 204):
            ok += 1
        else:
            print(f"  ! 删除 #{b['id']} 失败: HTTP {code} {err or ''}")
            fail += 1
    print(f"\n完成: 已删除 {ok}/{len(targets)} 个批次" + (f"(失败 {fail})" if fail else ""))
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
