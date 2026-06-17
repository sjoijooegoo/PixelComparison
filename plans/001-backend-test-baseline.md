# Plan 001: Establish a backend test baseline (pytest + FastAPI TestClient)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7621d9e..HEAD -- backend/app/db.py backend/app/main.py`
> Also confirm the working tree matches the "Current state" excerpts below
> (there were uncommitted changes at planning time). On a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `7621d9e` (+ uncommitted working-tree changes), 2026-06-17

## Why this matters

This repo has **zero automated tests** — no pytest config, no test directory,
no CI. Every change (including the other plans in this batch) is verified only
by hand. The next round of work deliberately changes request handling, the
compare pipeline, file storage, and an API response shape; without a safety net
a regression in the create-batch → upload → compare flow ships silently. This
plan creates a minimal but real backend test harness that exercises the whole
HTTP flow end to end, so plans 002–005 each have a place to add a regression
test and a one-command way to prove they didn't break anything.

## Current state

- `backend/app/db.py` — defines the SQLAlchemy engine and `DATA_DIR`. The data
  directory is **hardcoded**, which is the one thing blocking test isolation:

  ```python
  # backend/app/db.py:1-14
  from pathlib import Path
  from sqlalchemy import create_engine, event, text
  from sqlalchemy.orm import DeclarativeBase, sessionmaker

  DATA_DIR = Path(__file__).resolve().parent.parent / "data"
  IMAGES_DIR = DATA_DIR / "images"
  DATA_DIR.mkdir(parents=True, exist_ok=True)
  IMAGES_DIR.mkdir(parents=True, exist_ok=True)

  engine = create_engine(
      f"sqlite:///{DATA_DIR / 'shotdiff.db'}",
      connect_args={"check_same_thread": False},
  )
  ```

- `backend/app/main.py` — the FastAPI app. At import time it runs
  `Base.metadata.create_all(engine); migrate_columns()` (lines ~18-19), so just
  importing `app.main` creates the schema in whatever DB `db.py` points at.
  Key endpoints the tests will hit (all confirmed present):
  - `POST /api/batches` (201) — body `{id?, scene_id, p4_version, platform, creator?, ...}`
  - `POST /api/batches/{batch_id}/screenshots` (201) — multipart form: `scene_name`
    (required), `file` (PNG, required), optional `camera`, `frame_index`
  - `GET /api/batches` → `{total, items}`
  - `GET /api/batches/{batch_id}/screenshots` → `{total, items}`
  - `POST /api/comparisons` (202) — body `{batch_id, ref_batch_id, force?}`.
    Returns `{status:"done", comparison}` on cache hit, else
    `{task_id, status:"running", done, total}`. **Runs in a background thread.**
  - `GET /api/comparisons/tasks/{task_id}` → `{status, done, total, comparison?}`
  - `GET /api/meta` → `{scene_ids, platforms, baselines}`

- The compare pipeline (`backend/app/service.py` → `backend/app/compare.py`)
  opens the uploaded PNGs with Pillow and writes a heatmap. So the upload test
  must send **real PNG bytes** (generate them with Pillow), not random bytes.

- **Conventions to match**: the codebase is plain SQLAlchemy 2.0 + FastAPI, no
  existing test style to mirror (this is the first test). Use `pytest` plain
  functions (not classes), `httpx`/`fastapi.testclient.TestClient`, and Pillow
  (already a dependency, see `backend/requirements.txt`) to make image bytes.
- The venv lives at `backend/.venv`. Python is 3.10 (see
  `backend/app/__pycache__/*.cpython-310.pyc`).

## Commands you will need

Run these from the **`backend/` directory** (where `app/` lives).

| Purpose | Command (PowerShell, from `backend/`) | Expected on success |
|---------|----------------------------------------|---------------------|
| Install dev deps | `.\.venv\Scripts\python -m pip install -r requirements-dev.txt` | exit 0 |
| Run tests | `.\.venv\Scripts\python -m pytest -q` | all pass, exit 0 |
| Run one test | `.\.venv\Scripts\python -m pytest -q tests/test_smoke.py::test_full_compare_flow` | passes |

If the shell is Git Bash instead of PowerShell, the python path is
`./.venv/Scripts/python`.

## Scope

**In scope** (the only files you should create/modify):
- `backend/app/db.py` — make `DATA_DIR` overridable via an env var (small change).
- `backend/requirements-dev.txt` (create)
- `backend/tests/__init__.py` (create, empty)
- `backend/tests/conftest.py` (create)
- `backend/tests/test_smoke.py` (create)
- `backend/pytest.ini` (create)
- `plans/README.md` (update status row only)

**Out of scope** (do NOT touch):
- Any endpoint logic in `backend/app/main.py`, `service.py`, `compare.py`,
  `settings.py` — this plan only *observes* current behavior, it does not change it.
- The production data directory `backend/data/` — tests must never write there.
- The frontend.

## Git workflow

- Branch: `advisor/001-backend-test-baseline`
- Commit message style matches the repo (short, descriptive; repo uses Chinese
  subjects, e.g. `7621d9e 适配新版上报 manifest + 多人并发护栏 + 详情页打磨`).
  A clear English subject is acceptable too. End with the repo's existing
  trailer convention if any; otherwise no trailer.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Make `DATA_DIR` overridable via env var

Tests must run against a throwaway directory, never `backend/data/`. The engine
is created at import time, so the override has to happen via environment before
`app.db` is imported. Change **only** the `DATA_DIR` line in `backend/app/db.py`:

Current:
```python
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
```
Change to:
```python
import os
DATA_DIR = Path(
    os.environ.get("PIXELCOMP_DATA_DIR")
    or (Path(__file__).resolve().parent.parent / "data")
)
```
Keep the `import os` at the top of the file with the other imports (move it up
next to `from pathlib import Path` rather than inline if you prefer — either is
fine, but it must execute before `DATA_DIR` is assigned). Do not change anything
else in the file. Default behavior (no env var set) is identical to today.

**Verify**: `.\.venv\Scripts\python -c "import os; os.environ['PIXELCOMP_DATA_DIR']=r'%TEMP%\pc_probe'; from app.db import DATA_DIR; print(DATA_DIR)"`
run from `backend/` → prints a path ending in `pc_probe` (not `backend\data`).
Then delete that probe dir.

### Step 2: Add dev dependencies

Create `backend/requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0
httpx>=0.27
```
(`httpx` is what `fastapi.testclient.TestClient` uses under the hood.)

Install:
**Verify**: `.\.venv\Scripts\python -m pip install -r requirements-dev.txt` → exit 0,
then `.\.venv\Scripts\python -m pytest --version` → prints a pytest version.

### Step 3: Add pytest config

Create `backend/pytest.ini`:
```ini
[pytest]
testpaths = tests
addopts = -ra
```

### Step 4: Add the test fixtures (`conftest.py`)

Create `backend/tests/__init__.py` (empty) and `backend/tests/conftest.py`.
The fixture sets `PIXELCOMP_DATA_DIR` to a fresh temp dir **before** importing
`app.main`, builds a `TestClient`, and provides a PNG-bytes helper:

```python
import importlib
import io
import os

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by an isolated temp data dir + fresh SQLite db.

    PIXELCOMP_DATA_DIR must be set before app.db is imported, because the engine
    and DATA_DIR are created at import time. We (re)import the app modules inside
    the fixture so each test gets a clean schema in tmp_path.
    """
    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))

    # Force a fresh import of the app against the temp data dir.
    import app.db
    import app.main
    importlib.reload(app.db)
    importlib.reload(app.main)

    from fastapi.testclient import TestClient
    with TestClient(app.main.app) as c:
        yield c


@pytest.fixture()
def png_bytes():
    """Return a callable producing a solid-color PNG of a given size/color."""
    from PIL import Image

    def _make(color=(120, 130, 140), size=(64, 48)):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="PNG")
        return buf.getvalue()

    return _make
```

> Note on `importlib.reload`: because `app.db` and `app.main` may already be
> imported by a previous test, reloading them rebinds the engine to the new
> `tmp_path`. If reload causes problems (e.g. SQLAlchemy mapper warnings that
> fail the run), see STOP conditions.

### Step 5: Write the smoke / characterization tests

Create `backend/tests/test_smoke.py`. These assert **current** behavior (they
are characterization tests — they lock in how the app works today):

```python
import time


def test_meta_and_empty_batches(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"scene_ids", "platforms", "baselines"}

    r = client.get("/api/batches")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def _create_batch(client, batch_id, scene_id="SceneA", p4=100, platform="Windows"):
    r = client.post("/api/batches", json={
        "id": batch_id, "scene_id": scene_id,
        "p4_version": p4, "platform": platform,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, batch_id, scene_name, data):
    return client.post(
        f"/api/batches/{batch_id}/screenshots",
        data={"scene_name": scene_name},
        files={"file": (f"{scene_name}.png", data, "image/png")},
    )


def test_create_batch_and_upload(client, png_bytes):
    _create_batch(client, "b1")
    r = _upload(client, "b1", "shot_01", png_bytes())
    assert r.status_code == 201, r.text

    # duplicate batch id -> 409
    r = client.post("/api/batches", json={
        "id": "b1", "scene_id": "SceneA", "p4_version": 1, "platform": "Windows"})
    assert r.status_code == 409

    # duplicate scene in same batch -> 409
    r = _upload(client, "b1", "shot_01", png_bytes())
    assert r.status_code == 409

    # list screenshots
    r = client.get("/api/batches/b1/screenshots")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_platform_normalized(client):
    body = _create_batch(client, "bwin", platform="WindowsEditor")
    assert body["platform"] == "Windows"


def test_path_traversal_rejected(client, png_bytes):
    _create_batch(client, "b2")
    r = _upload(client, "b2", "../evil", png_bytes())
    assert r.status_code == 400


def test_full_compare_flow(client, png_bytes):
    # Two batches, same scene_id, one differing screenshot.
    _create_batch(client, "base", scene_id="SceneX", p4=100)
    _create_batch(client, "cur", scene_id="SceneX", p4=200)
    for bid, color in (("base", (10, 10, 10)), ("cur", (200, 10, 10))):
        assert _upload(client, bid, "shot_01", png_bytes(color)).status_code == 201

    r = client.post("/api/comparisons", json={"batch_id": "cur", "ref_batch_id": "base"})
    assert r.status_code == 202, r.text
    body = r.json()

    if body.get("status") == "done":
        comp = body["comparison"]
    else:
        task_id = body["task_id"]
        comp = None
        for _ in range(50):  # ~10s budget
            t = client.get(f"/api/comparisons/tasks/{task_id}").json()
            if t["status"] == "done":
                comp = t["comparison"]
                break
            assert t["status"] != "error", t
            time.sleep(0.2)
        assert comp is not None, "comparison task did not finish in time"

    # one paired checkpoint, with a measurable diff
    assert comp["scene_count"] == 1
    r = client.get(f"/api/comparisons/{comp['id']}/scenes")
    assert r.status_code == 200
    scenes = r.json()
    assert scenes["total"] == 1
    item = scenes["items"][0]
    assert item["name"] == "shot_01"
    assert item["diff_pct"] is not None

    # item detail
    r = client.get(f"/api/items/{item['id']}")
    assert r.status_code == 200
    assert r.json()["heatmap_url"]
```

**Verify**: from `backend/`, run `.\.venv\Scripts\python -m pytest -q` →
all tests pass (7 tests), exit 0. The run must NOT create or modify
`backend/data/` (check `git status` shows no changes under `backend/data/`).

### Step 6: Update the plan index

Set this plan's status to DONE in `plans/README.md`.

## Test plan

This plan *is* the test plan — it bootstraps the suite. New file
`backend/tests/test_smoke.py` covering: meta + empty list, create/upload +
both 409 dedup paths, platform normalization, path-traversal rejection (the
`safe_segment` guard), and the full create→upload→compare→scenes→item flow
including background-task polling. Structural pattern for future tests:
`backend/tests/test_smoke.py` itself (plain functions + the `client`/`png_bytes`
fixtures from `conftest.py`).

## Done criteria

ALL must hold:

- [ ] `backend/requirements-dev.txt`, `backend/pytest.ini`,
      `backend/tests/__init__.py`, `backend/tests/conftest.py`,
      `backend/tests/test_smoke.py` exist.
- [ ] `backend/app/db.py` reads `PIXELCOMP_DATA_DIR` and falls back to the old
      default when unset (and only that line/its import changed).
- [ ] From `backend/`: `.\.venv\Scripts\python -m pytest -q` exits 0 with all
      tests passing.
- [ ] `git status` shows no changes under `backend/data/` and no files modified
      outside the in-scope list.
- [ ] `plans/README.md` status row for 001 says DONE.

## STOP conditions

Stop and report back (do not improvise) if:

- `backend/app/db.py` does not match the "Current state" excerpt (it was changed
  since planning).
- `importlib.reload` in `conftest.py` produces SQLAlchemy mapper/registry errors
  that make tests fail regardless of test logic. (Fallback to report: an
  alternative is a session-scoped temp dir set via `pytest` `conftest`-level
  `os.environ` before any import, but try the per-test fixture first.)
- The compare flow test cannot reach `status == "done"` within the 10s budget —
  do not extend the timeout blindly; report the task's last `{status, done,
  total}` and any error.
- Making the tests pass appears to require changing endpoint logic in `main.py`
  or `service.py` (those are out of scope — characterization tests must accept
  current behavior, not "fix" it).

## Maintenance notes

- The `PIXELCOMP_DATA_DIR` env override is now the supported way to point the app
  at an alternate data root — useful for tests and for running multiple isolated
  instances. The production scripts (`run.ps1`, `run-prod.ps1`) don't set it, so
  prod behavior is unchanged.
- Plans 002–005 will each add a test to `backend/tests/`; reviewers should
  expect the suite to grow and stay green.
- If the background-compare flow is ever moved off threads (e.g. to a task
  queue), `test_full_compare_flow`'s polling loop must be revisited.
</content>
