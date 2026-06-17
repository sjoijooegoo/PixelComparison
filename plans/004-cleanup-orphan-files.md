# Plan 004: Clean up orphaned image/heatmap files

> **Executor instructions**: Follow step by step. Run every verification command
> and confirm the expected result before moving on. On any "STOP conditions"
> item, stop and report. When done, update this plan's status row in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7621d9e..HEAD -- backend/app/service.py`
> Confirm the working tree matches the "Current state" excerpts. On a mismatch,
> STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: 001 (uses its pytest harness)
- **Category**: tech-debt
- **Planned at**: commit `7621d9e` (+ uncommitted working-tree changes), 2026-06-17

## Why this matters

Image and heatmap files on disk accumulate without bound and are never reclaimed:

1. **Re-running a comparison leaks heatmaps.** `run_comparison` deletes the old
   `ComparisonItem` *rows* and regenerates heatmaps only for the checkpoints that
   still pair up. If a checkpoint disappeared between runs (renamed/removed
   screenshot), its old heatmap PNG stays on disk forever, now unreferenced.
2. **Deleted batches/comparisons leave files behind.** Batch deletion is done
   out-of-band (manual SQL) today; even when rows go away, the screenshot files
   under `data/images/batches/<id>/` and heatmap dirs under
   `data/images/heatmaps/<comparison_id>/` are never removed.

This plan fixes the re-run leak directly and adds a runnable cleanup utility that
removes files with no matching database row, so disk usage stays proportional to
live data.

## Current state

`backend/app/service.py` — re-run clears rows + regenerates heatmaps into a
per-comparison dir, but never clears stale heatmap files first:

```python
# service.py:44-65 (inside run_comparison)
    # 复用同一行:刷新基线关联并清掉旧明细(重算时 comparison.id 保持不变)
    comparison.baseline_id = baseline.id if baseline else None
    db.execute(delete(ComparisonItem).where(ComparisonItem.comparison_id == comparison.id))
    db.flush()

    heat_dir = IMAGES_DIR / "heatmaps" / str(comparison.id)
    heat_dir.mkdir(parents=True, exist_ok=True)

    names = sorted(set(current_shots) | set(baseline_shots))
    paired = [n for n in names if n in current_shots and n in baseline_shots]

    # 两边都有的检查点:并行跑像素对比(compare_images 纯计算 + 写热力图文件,不碰 DB)
    def _compare(name: str):
        cur, base = current_shots[name], baseline_shots[name]
        return name, compare_images(
            str(IMAGES_DIR / cur.path),
            str(IMAGES_DIR / base.path),
            str(IMAGES_DIR / f"heatmaps/{comparison.id}/{name}.png"),
            ...
        )
```

Storage layout (confirmed from `main.py` upload + `service.py`):
- Screenshots: `IMAGES_DIR/batches/<batch_id>/<scene_name>.png`
  (written in `main.py` `upload_screenshot`, `path = "batches/{batch_id}/{scene_name}.png"`).
- Heatmaps: `IMAGES_DIR/heatmaps/<comparison_id>/<scene_name>.png`.
- `IMAGES_DIR` is `backend/app/../data/images` (see `backend/app/db.py`:
  `IMAGES_DIR = DATA_DIR / "images"`), overridable via `PIXELCOMP_DATA_DIR`
  (added in plan 001).

DB models (`backend/app/models.py`): `Batch.id` (str PK), `Screenshot.path`
(relative to `IMAGES_DIR`), `Comparison.id` (int PK),
`ComparisonItem.heatmap_path` (relative, e.g. `heatmaps/12/shot_01.png`).
`Batch.screenshots` and `Comparison.items` both use
`cascade="all, delete-orphan"` — so deleting a Batch/Comparison row removes child
rows, but **not** the on-disk files.

## Commands you will need

From the **`backend/` directory**:

| Purpose | Command (PowerShell) | Expected |
|---------|----------------------|----------|
| Run tests | `.\.venv\Scripts\python -m pytest -q` | all pass, exit 0 |
| Run cleanup (dry-run) | `.\.venv\Scripts\python -m app.cleanup --dry-run` | lists orphans, exit 0 |
| Run cleanup | `.\.venv\Scripts\python -m app.cleanup` | deletes orphans, exit 0 |

## Scope

**In scope**:
- `backend/app/service.py` — clear the heatmap dir before regenerating (fix #1).
- `backend/app/cleanup.py` (create) — orphan-file scanner/remover + `__main__`.
- `backend/tests/test_cleanup.py` (create)
- `plans/README.md` (status row)

**Out of scope** (do NOT touch):
- Adding a DELETE endpoint (separate deferred finding) — this plan only reclaims
  files; it does not add HTTP deletion.
- `main.py`, `compare.py`, the models.
- Do NOT wire `cleanup` to run automatically on startup or a timer — it is a
  manually/cron-invoked maintenance tool. Auto-running it risks deleting files
  during a concurrent upload.

## Git workflow

- Branch: `advisor/004-cleanup-orphan-files`
- Commit message: short and descriptive.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Clear stale heatmaps on re-run

In `service.py` `run_comparison`, replace the heatmap-dir creation:

```python
    heat_dir = IMAGES_DIR / "heatmaps" / str(comparison.id)
    heat_dir.mkdir(parents=True, exist_ok=True)
```
with a clear-then-recreate (so a re-run never leaves last run's heatmaps for
checkpoints that no longer pair up):

```python
    import shutil  # 顶部已无 shutil 导入则加到文件 import 区
    heat_dir = IMAGES_DIR / "heatmaps" / str(comparison.id)
    if heat_dir.exists():
        shutil.rmtree(heat_dir)
    heat_dir.mkdir(parents=True, exist_ok=True)
```

Prefer adding `import shutil` to the import block at the **top** of
`service.py` (next to `from concurrent.futures import ...`) rather than inline.
Inline is shown only to mark where it's used.

**Verify**: covered by Step 3's `test_rerun_clears_stale_heatmaps`.

### Step 2: Add the orphan-cleanup utility

Create `backend/app/cleanup.py`. It compares on-disk files against DB rows and
removes the ones with no owner. It uses its own `SessionLocal` session and the
same `IMAGES_DIR`, so it honors `PIXELCOMP_DATA_DIR`.

```python
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
                # 批次存在,但目录内有无对应 Screenshot 行的散图
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
```

### Step 3: Add tests

Create `backend/tests/test_cleanup.py`:

```python
import importlib

from PIL import Image


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))
    import app.db
    import app.main
    import app.cleanup
    importlib.reload(app.db)
    importlib.reload(app.main)
    importlib.reload(app.cleanup)
    return app


def _png_file(path, color=(10, 20, 30)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path, format="PNG")


def test_orphan_dirs_and_files_removed(tmp_path, monkeypatch):
    app = _fresh(tmp_path, monkeypatch)
    images = app.db.IMAGES_DIR

    # live batch + screenshot via the API
    from fastapi.testclient import TestClient
    with TestClient(app.main.app) as client:
        client.post("/api/batches", json={
            "id": "live", "scene_id": "S", "p4_version": 1, "platform": "Windows"})
        import io
        buf = io.BytesIO(); Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, "PNG")
        client.post("/api/batches/live/screenshots",
                    data={"scene_name": "keep"},
                    files={"file": ("keep.png", buf.getvalue(), "image/png")})

    # orphans on disk
    _png_file(images / "batches" / "ghost_batch" / "x.png")          # dir for missing batch
    _png_file(images / "batches" / "live" / "stray.png")             # stray file in live batch
    (images / "heatmaps" / "999").mkdir(parents=True, exist_ok=True) # heatmap for missing comparison
    _png_file(images / "heatmaps" / "999" / "h.png")

    from app.cleanup import find_orphans, prune_orphans
    db = app.db.SessionLocal()
    try:
        before = find_orphans(db)
        assert any(d.name == "ghost_batch" for d in before["dirs"])
        assert any(d.name == "999" for d in before["dirs"])
        assert any(f.name == "stray.png" for f in before["files"])

        prune_orphans(db, dry_run=False)
        after = find_orphans(db)
        assert after["dirs"] == [] and after["files"] == []
    finally:
        db.close()

    # live data untouched
    assert (images / "batches" / "live" / "keep.png").exists()


def test_dry_run_deletes_nothing(tmp_path, monkeypatch):
    app = _fresh(tmp_path, monkeypatch)
    images = app.db.IMAGES_DIR
    _png_file(images / "batches" / "ghost" / "x.png")

    from app.cleanup import prune_orphans
    db = app.db.SessionLocal()
    try:
        prune_orphans(db, dry_run=True)
    finally:
        db.close()
    assert (images / "batches" / "ghost" / "x.png").exists()  # still there
```

**Verify**: from `backend/`, `.\.venv\Scripts\python -m pytest -q` → all pass.

### Step 4: Add a re-run stale-heatmap test

Append to `backend/tests/test_cleanup.py` a test that proves Step 1 removed the
re-run leak. Drive it through the API so it exercises the real path:

```python
def test_rerun_clears_stale_heatmaps(tmp_path, monkeypatch):
    import io, time
    app = _fresh(tmp_path, monkeypatch)
    images = app.db.IMAGES_DIR
    from fastapi.testclient import TestClient

    def png(c):
        b = io.BytesIO(); Image.new("RGB", (16, 16), c).save(b, "PNG"); return b.getvalue()

    def upload(client, bid, scene, c):
        return client.post(f"/api/batches/{bid}/screenshots",
                           data={"scene_name": scene},
                           files={"file": (f"{scene}.png", png(c), "image/png")})

    def run_and_wait(client, cur, ref, force=False):
        r = client.post("/api/comparisons",
                        json={"batch_id": cur, "ref_batch_id": ref, "force": force})
        body = r.json()
        if body.get("status") == "done":
            return body["comparison"]
        tid = body["task_id"]
        for _ in range(50):
            t = client.get(f"/api/comparisons/tasks/{tid}").json()
            if t["status"] == "done":
                return t["comparison"]
            assert t["status"] != "error", t
            time.sleep(0.2)
        raise AssertionError("compare did not finish")

    with TestClient(app.main.app) as client:
        for bid in ("base", "cur"):
            client.post("/api/batches", json={
                "id": bid, "scene_id": "S", "p4_version": 1, "platform": "Windows"})
        # first run: two paired checkpoints -> two heatmaps
        upload(client, "base", "a", (0, 0, 0)); upload(client, "cur", "a", (255, 0, 0))
        upload(client, "base", "b", (0, 0, 0)); upload(client, "cur", "b", (0, 255, 0))
        comp = run_and_wait(client, "cur", "base")
        hdir = images / "heatmaps" / str(comp["id"])
        assert (hdir / "a.png").exists() and (hdir / "b.png").exists()

    # Simulate "b" disappearing from one side by removing its DB rows, then force re-run.
    from sqlalchemy import delete
    from app.models import Screenshot
    db = app.db.SessionLocal()
    try:
        db.execute(delete(Screenshot).where(Screenshot.scene_name == "b"))
        db.commit()
    finally:
        db.close()

    with TestClient(app.main.app) as client:
        comp = run_and_wait(client, "cur", "base", force=True)
        hdir = images / "heatmaps" / str(comp["id"])
        assert (hdir / "a.png").exists()
        assert not (hdir / "b.png").exists()  # stale heatmap cleared on re-run
```

**Verify**: from `backend/`, `.\.venv\Scripts\python -m pytest -q` → all pass.

### Step 5: Update the plan index

Set this plan's status to DONE in `plans/README.md`.

## Test plan

- `backend/tests/test_cleanup.py`: (1) orphan batch dir, stray file in live
  batch, and orphan heatmap dir are all found and removed while live files
  survive; (2) `--dry-run`/`dry_run=True` deletes nothing; (3) re-running a
  comparison clears a now-stale heatmap. Pattern: plan 001's fixtures +
  `TestClient` usage.

## Done criteria

ALL must hold:

- [ ] `service.py` clears `heat_dir` (rmtree) before recreating it on each run,
      with `import shutil` at the top of the file.
- [ ] `backend/app/cleanup.py` exists with `find_orphans`, `prune_orphans`,
      `main`, and a `__main__` guard; `--dry-run` is honored.
- [ ] `.\.venv\Scripts\python -m app.cleanup --dry-run` runs (exit 0) against a
      data dir and prints a summary line.
- [ ] From `backend/`: `.\.venv\Scripts\python -m pytest -q` exits 0; the new
      tests pass.
- [ ] cleanup is NOT invoked automatically anywhere (no startup/timer hook).
- [ ] `git status` shows only in-scope files changed.
- [ ] `plans/README.md` status row for 004 says DONE.

## STOP conditions

Stop and report if:

- `service.py`'s heatmap section doesn't match the "Current state" excerpt.
- `find_orphans` would flag a live file as an orphan in the tests (path
  normalization mismatch) — report rather than relaxing the comparison; the
  likely cause is `resolve()` differences on Windows symlinked temp dirs.
- The re-run test can't reach `status == "done"` within budget — report the last
  task state.

## Maintenance notes

- When a real DELETE endpoint is added (deferred finding), it should call
  `prune_orphans` (or delete the specific batch/comparison dirs) so deletion
  reclaims disk immediately, instead of relying on this periodic sweep.
- `prune_orphans` is **not** concurrency-safe against in-flight uploads/compares
  (it could delete a file being written). That's why it's manual-only. If it's
  ever scheduled, schedule it during a quiet window or add a lock.
- Reviewer should confirm `find_orphans` never lists a path that has a live DB
  row (the `live_shot_paths`/`live_*_ids` sets), and that `dry_run` truly skips
  all deletions.
</content>
