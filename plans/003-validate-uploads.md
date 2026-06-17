# Plan 003: Validate uploads (size cap + PNG signature)

> **Executor instructions**: Follow step by step. Run every verification command
> and confirm the expected result before moving on. On any "STOP conditions"
> item, stop and report. When done, update this plan's status row in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7621d9e..HEAD -- backend/app/main.py`
> Confirm the working tree matches the "Current state" excerpt below. On a
> mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: 001 (uses its pytest harness)
- **Category**: security
- **Planned at**: commit `7621d9e` (+ uncommitted working-tree changes), 2026-06-17

## Why this matters

The screenshot upload endpoint reads the **entire** uploaded file into memory and
writes it to disk with no size limit and no content check. A single oversized or
malformed upload (accidental or hostile) can exhaust RAM or fill the data
disk, and a non-image payload is happily stored as `<scene>.png` only to crash
later when the compare pipeline tries to open it with Pillow. Path traversal is
already handled (`safe_segment`), so this plan adds the two missing guards: a
maximum size and a real PNG-signature check, returning clean HTTP errors instead
of crashing or OOMing.

## Current state

`backend/app/main.py` — the upload endpoint (note `file.file.read()` with no
bound and no validation):

```python
# main.py:213-248
@app.post("/api/batches/{batch_id}/screenshots", status_code=201)
def upload_screenshot(
    batch_id: str,
    scene_name: str = Form(...),
    file: UploadFile = File(...),
    camera: str | None = Form(None),       # JSON 字符串:{location, rotation}
    frame_index: int | None = Form(None),
    db: Session = Depends(get_db),
):
    if not db.get(Batch, batch_id):
        raise HTTPException(404, "batch not found")
    scene_name = safe_segment(scene_name, "scene name")
    exists = db.scalar(
        select(Screenshot).where(
            Screenshot.batch_id == batch_id, Screenshot.scene_name == scene_name
        )
    )
    if exists:
        raise HTTPException(409, f"scene {scene_name} already uploaded")
    out_dir = IMAGES_DIR / "batches" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = f"batches/{batch_id}/{scene_name}.png"
    (IMAGES_DIR / path).write_bytes(file.file.read())
    cam = None
    if camera:
        try:
            cam = json.loads(camera)
        except json.JSONDecodeError:
            cam = None
    shot = Screenshot(
        batch_id=batch_id, scene_name=scene_name, path=path,
        camera=cam, frame_index=frame_index,
    )
    db.add(shot)
    db.commit()
    return {"id": shot.id, "scene_name": scene_name, "url": shot.url}
```

Relevant facts:
- `file` is a Starlette `UploadFile`; `file.file` is a `SpooledTemporaryFile`
  (large uploads already spill to a temp file on disk, so measuring its size by
  seeking does **not** load it into RAM).
- The compare pipeline opens these files with `Image.open(...).convert("RGB")`
  (`backend/app/compare.py:69-70`), so only valid images are usable downstream.
- Existing error convention in this file: `raise HTTPException(<code>, "<msg>")`.
  HTTP 413 = payload too large; 400 = bad request. Use those.
- Project images are stored as PNG (`path = ".../{scene_name}.png"`), and the
  upload doc/mock uploaders send PNGs. So validating the **PNG** signature
  specifically is correct here, not generic "any image".

## Commands you will need

From the **`backend/` directory**:

| Purpose | Command (PowerShell) | Expected |
|---------|----------------------|----------|
| Run tests | `.\.venv\Scripts\python -m pytest -q` | all pass, exit 0 |
| Run new test | `.\.venv\Scripts\python -m pytest -q tests/test_upload_validation.py` | passes |

## Scope

**In scope**:
- `backend/app/main.py` — add a size constant + a validation block in
  `upload_screenshot` (before writing the file).
- `backend/tests/test_upload_validation.py` (create)
- `plans/README.md` (status row)

**Out of scope** (do NOT touch):
- `safe_segment` (path traversal is already handled).
- The dedup/409 logic, the `camera`/`frame_index` parsing.
- `compare.py`, `service.py`.
- Do NOT add a new dependency (no `python-magic` etc.) — a literal signature
  check is enough.

## Git workflow

- Branch: `advisor/003-validate-uploads`
- Commit message: short and descriptive.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a max-size constant

Near the top-level constants in `main.py` (e.g. just after `ITEM_STATUSES` around
line 31), add:

```python
# 单张截图上传上限;游戏截图 PNG 一般 < 几 MB,25MB 足够且能挡住异常大文件。
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# PNG 文件头(magic number)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
```

### Step 2: Validate size and signature before writing

In `upload_screenshot`, replace the single write line:

```python
    path = f"batches/{batch_id}/{scene_name}.png"
    (IMAGES_DIR / path).write_bytes(file.file.read())
```

with a measured, validated read:

```python
    path = f"batches/{batch_id}/{scene_name}.png"

    # 大小校验:seek 到末尾测量,不把文件读进内存(SpooledTemporaryFile)
    upload = file.file
    upload.seek(0, 2)        # end
    size = upload.tell()
    upload.seek(0)           # rewind
    if size == 0:
        raise HTTPException(400, "空文件")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大(>{MAX_UPLOAD_BYTES // (1024 * 1024)}MB)")

    data = upload.read()     # size 已限制在上限内
    if not data.startswith(_PNG_SIGNATURE):
        raise HTTPException(400, "仅支持 PNG 图片")

    (IMAGES_DIR / path).write_bytes(data)
```

Leave everything after the write (camera parse, `Screenshot(...)`, commit,
return) unchanged.

### Step 3: Add the regression test

Create `backend/tests/test_upload_validation.py`:

```python
import io

from PIL import Image


def _png(color=(100, 110, 120), size=(32, 24)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _create_batch(client, bid="b1"):
    r = client.post("/api/batches", json={
        "id": bid, "scene_id": "SceneA", "p4_version": 1, "platform": "Windows"})
    assert r.status_code == 201, r.text


def _upload(client, bid, scene, data):
    return client.post(
        f"/api/batches/{bid}/screenshots",
        data={"scene_name": scene},
        files={"file": (f"{scene}.png", data, "image/png")},
    )


def test_valid_png_accepted(client):
    _create_batch(client)
    assert _upload(client, "b1", "ok", _png()).status_code == 201


def test_non_png_rejected(client):
    _create_batch(client)
    r = _upload(client, "b1", "bad", b"this is not a png")
    assert r.status_code == 400


def test_empty_file_rejected(client):
    _create_batch(client)
    r = _upload(client, "b1", "empty", b"")
    assert r.status_code == 400


def test_oversized_rejected(client, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "MAX_UPLOAD_BYTES", 1024)  # shrink the cap for the test
    _create_batch(client)
    big = _png(size=(400, 400))  # comfortably > 1KB as PNG
    assert len(big) > 1024
    r = _upload(client, "b1", "big", big)
    assert r.status_code == 413
```

> Note: `monkeypatch.setattr(m, "MAX_UPLOAD_BYTES", 1024)` works because the
> endpoint reads the module-level constant at call time. If the `client` fixture
> reloads `app.main` (it does, per plan 001), patch after the fixture has run —
> requesting `client` before patching, as written above, ensures the reloaded
> module is the one patched. If ordering causes the patch not to take, see STOP.

**Verify**: from `backend/`, `.\.venv\Scripts\python -m pytest -q` → all pass
(plan 001's 7, plan 002's 2 if present, plus these 4).

### Step 4: Update the plan index

Set this plan's status to DONE in `plans/README.md`.

## Test plan

- New file `backend/tests/test_upload_validation.py`: valid PNG accepted (201);
  non-PNG rejected (400); empty file rejected (400); oversized rejected (413,
  via a shrunk cap). Pattern: `backend/tests/conftest.py` fixtures from plan 001.
- Confirm plan 001's `test_create_batch_and_upload` (which uploads a real PNG)
  still passes — the new validation must accept the existing valid path.

## Done criteria

ALL must hold:

- [ ] `main.py` defines `MAX_UPLOAD_BYTES` + `_PNG_SIGNATURE` and validates size
      (0 and over-cap) and PNG signature before writing the file.
- [ ] No new third-party dependency was added.
- [ ] From `backend/`: `.\.venv\Scripts\python -m pytest -q` exits 0; the 4 new
      tests exist and pass.
- [ ] `git status` shows only in-scope files changed.
- [ ] `plans/README.md` status row for 003 says DONE.

## STOP conditions

Stop and report if:

- The `upload_screenshot` body doesn't match the "Current state" excerpt.
- The `monkeypatch` of `MAX_UPLOAD_BYTES` doesn't take effect (oversized test
  returns 201) — report rather than restructuring the endpoint to read the cap
  differently.
- A real mock/sample upload (`mock_uploads/`, `report.py`) sends non-PNG images
  that this would now reject — if you happen to run one and it breaks, report;
  do not loosen the check silently.

## Maintenance notes

- The 25MB cap is a constant; if 4K/8K capture is added later, bump
  `MAX_UPLOAD_BYTES` deliberately (and reconsider whether the compare pipeline's
  full-image numpy arrays scale at that resolution).
- If non-PNG formats (JPEG/WebP) ever need to be supported, this signature check
  and the hardcoded `.png` output path both need updating together — they are
  coupled.
- Reviewer should confirm the size is measured via seek/tell (not by reading then
  checking `len`), so an oversized upload is rejected before it's fully read.
</content>
