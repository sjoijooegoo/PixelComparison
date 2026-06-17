# Plan 002: Stop `_TASKS` from growing unbounded (prune finished tasks)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> "STOP conditions" item occurs, stop and report — do not improvise. When done,
> update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7621d9e..HEAD -- backend/app/main.py`
> Confirm the working tree matches the "Current state" excerpts (there were
> uncommitted changes at planning time). On a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 001 (uses its pytest harness for the regression test)
- **Category**: bug
- **Planned at**: commit `7621d9e` (+ uncommitted working-tree changes), 2026-06-17

## Why this matters

The in-memory comparison-task registry `_TASKS` only ever grows. Every call to
`POST /api/comparisons` that starts a background task inserts an entry, and
**nothing ever removes it** — the `finally` block pops `_RUNNING` but not
`_TASKS`. On a long-running server with many comparisons this is a slow memory
leak, and it also means stale completed-task results linger indefinitely. The
fix is to prune finished (`done`/`error`) task entries after a TTL, while never
touching entries that are still `running` or recent enough that the frontend
might still poll them.

## Current state

`backend/app/main.py` — the task registry and its lifecycle:

```python
# main.py:278-282
# 对比后台任务:task_id -> 进度/结果(内存,单进程)
_TASKS: dict = {}
# 并发护栏:串行化"查重/建行/起任务"这段;同一对比同时只跑一个计算任务
_COMPARE_LOCK = threading.Lock()
_RUNNING: dict[int, str] = {}   # comparison_id -> 正在计算它的 task_id
```

The background worker updates status but only cleans `_RUNNING`:

```python
# main.py:285-307 (_run_compare_task)
def _run_compare_task(task_id, comparison_id, batch_id, ref_id, baseline_id, settings):
    db = SessionLocal()
    try:
        ...
        run_comparison(db, comparison, batch, ref, baseline, settings, on_progress=on_progress)
        db.commit()
        _TASKS[task_id].update(status="done", comparison_id=comparison_id)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _TASKS[task_id].update(status="error", error=str(e))
    finally:
        with _COMPARE_LOCK:
            _RUNNING.pop(comparison_id, None)
        db.close()
```

Task entries are created here (note: `_TASKS[task_id]` is set, never deleted):

```python
# main.py:357-359 (inside create_comparison, under _COMPARE_LOCK)
        task_id = uuid.uuid4().hex
        _TASKS[task_id] = {"status": "running", "done": 0, "total": 0, "comparison_id": cid, "error": None}
        _RUNNING[cid] = task_id
```

And read here by the poller:

```python
# main.py:368-379 (get_comparison_task)
@app.get("/api/comparisons/tasks/{task_id}")
def get_comparison_task(task_id: str, db: Session = Depends(get_db)):
    t = _TASKS.get(task_id)
    if not t:
        raise HTTPException(404, "task not found")
    resp = {"status": t["status"], "done": t["done"], "total": t["total"]}
    if t["status"] == "done" and t["comparison_id"]:
        resp["comparison"] = comparison_dto(db.get(Comparison, t["comparison_id"]), db)
    elif t["status"] == "error":
        resp["error"] = t["error"]
    return resp
```

Frontend polling behavior (so we pick a safe TTL): `frontend/src/store.js`
`_awaitComparison` polls every 400ms and **stops polling once it sees
`status === "done"`** (it reads `t.comparison` from that same response). So once
a task is done, the client makes at most one more read; a TTL of an hour is far
more than enough and won't 404 an active poller.

## Commands you will need

From the **`backend/` directory**:

| Purpose | Command (PowerShell) | Expected |
|---------|----------------------|----------|
| Run tests | `.\.venv\Scripts\python -m pytest -q` | all pass, exit 0 |
| Run new test | `.\.venv\Scripts\python -m pytest -q tests/test_task_prune.py` | passes |

## Scope

**In scope**:
- `backend/app/main.py` — add TTL + a prune helper; stamp finished tasks with a
  timestamp; call prune at task creation. (Surgical edits only.)
- `backend/tests/test_task_prune.py` (create)
- `plans/README.md` (status row)

**Out of scope** (do NOT touch):
- `_RUNNING` semantics and the `_COMPARE_LOCK` critical section logic — only add
  the prune call inside the existing lock; don't restructure it.
- `service.py`, `compare.py`, the DTOs.
- Do NOT introduce a background timer/thread for pruning — prune lazily on
  task creation (and optionally on read). A timer thread adds lifecycle bugs.

## Git workflow

- Branch: `advisor/002-prune-task-registry`
- Commit message: short and descriptive (English or Chinese, matching repo).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a TTL constant and a prune helper

In `backend/app/main.py`, near the `_TASKS` definition (after line 282), add:

```python
# 完成/失败的任务保留时长;超时后清理,避免 _TASKS 无限增长。
_TASK_TTL_SECONDS = 3600


def _prune_tasks(now: float | None = None) -> None:
    """删除已结束(done/error)且超过 TTL 的任务条目;running 的一律保留。

    调用方应已持有 _COMPARE_LOCK(在临界区内调用)。
    """
    now = now if now is not None else time.monotonic()
    stale = [
        tid for tid, t in _TASKS.items()
        if t["status"] in ("done", "error")
        and now - t.get("finished_at", now) > _TASK_TTL_SECONDS
    ]
    for tid in stale:
        _TASKS.pop(tid, None)
```

Add `import time` to the imports at the top of `main.py` (it currently imports
`json, threading, uuid` and `from datetime import datetime, timedelta` — add
`import time` alongside `import threading`).

### Step 2: Stamp tasks with `finished_at` when they end

In `_run_compare_task` (main.py ~298-303), record a finish timestamp on both the
success and error branches. Change:

```python
        _TASKS[task_id].update(status="done", comparison_id=comparison_id)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _TASKS[task_id].update(status="error", error=str(e))
```
to:
```python
        _TASKS[task_id].update(status="done", comparison_id=comparison_id, finished_at=time.monotonic())
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _TASKS[task_id].update(status="error", error=str(e), finished_at=time.monotonic())
```

### Step 3: Prune when a new task is created

Inside `create_comparison`, within the existing `with _COMPARE_LOCK:` block,
right before the new task is registered (main.py ~357, just above
`task_id = uuid.uuid4().hex`), add a prune call:

```python
        _prune_tasks()
        task_id = uuid.uuid4().hex
        _TASKS[task_id] = {"status": "running", "done": 0, "total": 0, "comparison_id": cid, "error": None}
```

This keeps the registry bounded by activity without any timer thread. (We prune
at the natural growth point — task creation.)

### Step 4: Add the regression test

Create `backend/tests/test_task_prune.py`. It drives prune directly against the
module-level registry to prove TTL eviction without waiting an hour:

```python
import importlib

import app.db  # noqa: F401  (ensures app package import path is set up)


def _fresh_main(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))
    import app.db
    import app.main
    importlib.reload(app.db)
    importlib.reload(app.main)
    return app.main


def test_prune_removes_old_finished_tasks(tmp_path, monkeypatch):
    m = _fresh_main(tmp_path, monkeypatch)
    m._TASKS.clear()
    m._TASKS["old_done"] = {"status": "done", "done": 1, "total": 1,
                            "comparison_id": 1, "error": None, "finished_at": 0.0}
    m._TASKS["old_err"] = {"status": "error", "done": 0, "total": 0,
                           "comparison_id": None, "error": "boom", "finished_at": 0.0}
    m._TASKS["running"] = {"status": "running", "done": 0, "total": 0,
                           "comparison_id": 2, "error": None}

    # now far in the future relative to finished_at=0 -> the two finished ones expire
    m._prune_tasks(now=m._TASK_TTL_SECONDS + 1)

    assert "old_done" not in m._TASKS
    assert "old_err" not in m._TASKS
    assert "running" in m._TASKS  # never pruned


def test_prune_keeps_recent_finished(tmp_path, monkeypatch):
    m = _fresh_main(tmp_path, monkeypatch)
    m._TASKS.clear()
    m._TASKS["recent"] = {"status": "done", "done": 1, "total": 1,
                          "comparison_id": 1, "error": None, "finished_at": 1000.0}
    m._prune_tasks(now=1000.0 + 5)  # well within TTL
    assert "recent" in m._TASKS
```

**Verify**: from `backend/`, `.\.venv\Scripts\python -m pytest -q` → all tests
pass (the 7 from plan 001 plus these 2). No regressions.

### Step 5: Update the plan index

Set this plan's status to DONE in `plans/README.md`.

## Test plan

- New file `backend/tests/test_task_prune.py`: (1) old `done` and `error` tasks
  past TTL are evicted; (2) `running` tasks are never evicted; (3) recent
  finished tasks within TTL are kept. Structural pattern: the fixtures/imports in
  `backend/tests/conftest.py` (from plan 001).
- The existing `test_full_compare_flow` (plan 001) already covers that a real
  task still completes and is readable — confirm it still passes (the change
  must not break the poll path).

## Done criteria

ALL must hold:

- [ ] `main.py` defines `_TASK_TTL_SECONDS` and `_prune_tasks`, imports `time`,
      stamps `finished_at` on done/error, and calls `_prune_tasks()` inside the
      `_COMPARE_LOCK` block before creating a new task.
- [ ] No background timer/thread was added for pruning.
- [ ] From `backend/`: `.\.venv\Scripts\python -m pytest -q` exits 0; the 2 new
      tests exist and pass.
- [ ] `git status` shows only in-scope files changed.
- [ ] `plans/README.md` status row for 002 says DONE.

## STOP conditions

Stop and report if:

- The `_TASKS`/`_run_compare_task`/`create_comparison` code doesn't match the
  excerpts (drift since planning).
- Adding the prune call appears to require changing the `_COMPARE_LOCK` critical
  section structure beyond inserting one line.
- `test_full_compare_flow` from plan 001 starts failing after this change —
  that means the prune is evicting live tasks; report it instead of widening
  the TTL.

## Maintenance notes

- This is an interim fix for the **single-process** design. When task state is
  moved to the database (the deferred "multi-worker readiness" item), `_TASKS`,
  `_prune_tasks`, and `_RUNNING` all go away — this code should be deleted, not
  ported.
- Reviewer should confirm `finished_at` uses `time.monotonic()` (not wall clock)
  so it's immune to system clock changes, and that `running` tasks can never be
  pruned (an orphaned "running" entry whose thread died would persist — that's an
  acceptable, rare edge for now; note it but don't fix here).
</content>
