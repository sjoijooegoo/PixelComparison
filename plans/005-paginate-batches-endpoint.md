# Plan 005: Server-side pagination for `/api/batches`

> **Executor instructions**: Follow step by step. Run every verification command
> and confirm the expected result before moving on. On any "STOP conditions"
> item, stop and report. When done, update this plan's status row in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat fc36009..HEAD -- backend/app/main.py frontend/src/store.js frontend/src/api.js frontend/src/components/BatchTable.vue frontend/src/components/FilterSidebar.vue`
> Confirm the working tree matches the "Current state" excerpts. On a mismatch,
> STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (changes an API response shape + frontend)
- **Depends on**: 001 (uses its pytest harness)
- **Category**: perf
- **Planned at**: commit `fc36009` (execute based on `main`, which already contains plans 001/002/004), 2026-06-17

## Why this matters

`GET /api/batches` returns **every** batch row in one response, and the batch
table paginates client-side by slicing the full array. Each row also triggers a
COUNT subquery, so the payload and query cost grow linearly with total batches
forever. As upload volume accumulates this gets slow and heavy. This plan adds
optional server-side pagination to `/api/batches` (backward compatible: no
pagination params → current "return all" behavior), and switches the batch table
to request one page at a time — mirroring the pattern the **scenes** list already
uses successfully.

## Current state

### The in-repo exemplar to copy: scenes pagination

The scenes list already does exactly what we want. **Match this pattern.**

Backend (`backend/app/main.py` `list_scenes`):
```python
# main.py:412-459 (relevant bits)
@app.get("/api/comparisons/{comparison_id}/scenes")
def list_scenes(
    comparison_id: int,
    db: Session = Depends(get_db),
    ...
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    ...
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(
        base.order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"total": total, "page": page, "page_size": page_size, "counts": counts, "items": [...]}
```

Frontend list that drives it (`frontend/src/components/SceneList.vue`) — dynamic
page size by available height, reloads on change:
```js
// SceneList.vue:13-29
function recalcPageSize() {
  const h = listEl.value?.clientHeight
  if (!h) return
  const fit = Math.max(5, Math.floor(h / ITEM_H))
  if (fit !== store.pageSize) {
    store.pageSize = fit
    store.page = 1
    if (store.selectedComparison) store.loadScenes()
  }
}
onMounted(() => {
  ro = new ResizeObserver(recalcPageSize)
  if (listEl.value) ro.observe(listEl.value)
  recalcPageSize()
})
```
Pager wiring (`SceneList.vue:90-92`): `@change="(p) => { store.page = p; store.loadScenes() }"`.

### What we are changing

Backend `list_batches` returns all rows, no pagination:
```python
# main.py:153-186 (head + tail)
@app.get("/api/batches")
def list_batches(
    db: Session = Depends(get_db),
    scene_id: str | None = None,
    platform: str | None = None,
    p4_min: int | None = None,
    p4_max: int | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    q: str | None = None,
):
    stmt = select(Batch).order_by(Batch.created_at.desc())
    ... # filters applied to stmt
    batches = db.scalars(stmt).all()
    return {"total": len(batches), "items": [batch_dto(b, db) for b in batches]}
```

Frontend store loads all and stores them (`frontend/src/store.js`):
```js
// store.js:16-17 (state) — filters object; NO batch page/pageSize yet
filters: { scene_id: '', platform: '', p4_min: null, p4_max: null, created_from: '', created_to: '', status: '' },
// store.js:83-87 (action)
async loadBatches() {
  const { items, total } = await api.batches(this.filters)
  this.batches = items
  this.batchTotal = total
},
```

API helper (`frontend/src/api.js:28`): `batches: (params) => get('/api/batches', params),`
(`get` already drops null/undefined/'' params — see `api.js:1-8`).

Batch table paginates **client-side** by slicing, and has a watcher that resets
page whenever `store.batches` changes (`frontend/src/components/BatchTable.vue`):
```js
// BatchTable.vue:18-47 (relevant)
const page = ref(1)
const pageSize = ref(8)
const pagedBatches = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return store.batches.slice(start, start + pageSize.value)
})
const tableWrap = ref(null)
let ro
function recalc() {
  const wrap = tableWrap.value
  if (!wrap) return
  const thH = wrap.querySelector('.arco-table-th')?.getBoundingClientRect().height || 36
  const rowH = wrap.querySelector('tbody .arco-table-tr')?.getBoundingClientRect().height || 40
  const fit = Math.max(3, Math.floor((wrap.clientHeight - thH) / rowH))
  if (fit !== pageSize.value) {
    pageSize.value = fit
    if (page.value > Math.ceil(store.batches.length / fit)) page.value = 1
  }
}
onMounted(() => {
  ro = new ResizeObserver(recalc)
  if (tableWrap.value) ro.observe(tableWrap.value)
  recalc()
})
onUnmounted(() => ro?.disconnect())
watch(() => store.batches, () => { page.value = 1; nextTick(recalc) })
```
The table uses `pagedBatches` as `:data` (`BatchTable.vue:140`) and the Pager
gets `:total="store.batchTotal" :page-size="pageSize" :current="page"` with
`@change="(p) => page = p"` (`BatchTable.vue:167-170`).

**Export caveat (must handle):** `exportCsv` (`BatchTable.vue:91-101`) iterates
`store.batches` to export the whole list. Once `store.batches` holds only one
page, export would silently export just that page. We fix this by having
`exportCsv` fetch all batches (no pagination params) at export time.

Filters apply via an explicit button (`frontend/src/components/FilterSidebar.vue`):
```js
// FilterSidebar.vue:18-26
async function apply() {
  await store.loadBatches()
  Message.success('筛选已应用')
}
async function reset() {
  store.filters = { scene_id: '', platform: '', p4_min: null, p4_max: null, created_from: '', created_to: '', status: '' }
  await apply()
}
```

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Backend tests (from `backend/`) | `.\.venv\Scripts\python -m pytest -q` | all pass, exit 0 |
| Frontend build (from `frontend/`) | `npm run build` | `✓ built`, exit 0 |
| Manual API check (server running) | `curl "http://localhost:8000/api/batches?page=1&page_size=2"` | JSON with ≤2 items + `total` |

(There is no frontend unit-test setup in this repo; `npm run build` is the
frontend verification gate.)

## Scope

**In scope**:
- `backend/app/main.py` — add `page`/`page_size` to `list_batches`.
- `frontend/src/store.js` — add `batchPage`/`batchPageSize` state; paginate in
  `loadBatches`.
- `frontend/src/components/BatchTable.vue` — use server pages; fix export.
- `frontend/src/components/FilterSidebar.vue` — reset to page 1 on apply.
- `backend/tests/test_pagination.py` (create)
- `plans/README.md` (status row)

**Out of scope** (do NOT touch):
- `/api/comparisons` pagination — the comparisons history is a recent-list
  dropdown (`ResultSummary.vue`); leave it returning all for now (note in
  Maintenance).
- The N+1 COUNT-per-row in `batch_dto` — separate deferred finding; pagination
  reduces its blast radius but don't refactor `batch_dto` here.
- `frontend/src/api.js` — no change needed (`batches(params)` already forwards
  arbitrary params and strips empties).

## Git workflow

- Branch: `advisor/005-paginate-batches-endpoint`
- Commit message: short and descriptive.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Backend — optional pagination on `list_batches`

In `main.py` `list_batches`, add two params and apply pagination only when
`page_size` is provided (preserving "return all" when it isn't). Replace the
signature's param list end and the final two lines.

Add params (after `q: str | None = None,`):
```python
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
```
(`Query` is already imported in `main.py`.)

Replace:
```python
    batches = db.scalars(stmt).all()
    return {"total": len(batches), "items": [batch_dto(b, db) for b in batches]}
```
with:
```python
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if page_size is not None:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    batches = db.scalars(stmt).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [batch_dto(b, db) for b in batches],
    }
```
(`func` and `select` are already imported.) Behavior: no `page_size` →
`total`=full count, all items returned (old callers still work, `total` now
reflects the real total rather than `len(items)`, which is what the frontend
already expects).

**Verify**: covered by Step 5 tests; also manual `curl` from the table above.

### Step 2: Store — add batch page state + paginate `loadBatches`

In `frontend/src/store.js`:

Add to `state` (next to `batchTotal`, around line in the `// 顶部:原始批次列表`
block):
```js
    batchPage: 1,
    batchPageSize: PAGE_SIZE,
```

Change `loadBatches`:
```js
    async loadBatches() {
      const { items, total } = await api.batches({
        ...this.filters,
        page: this.batchPage,
        page_size: this.batchPageSize,
      })
      this.batches = items
      this.batchTotal = total
    },
```

### Step 3: BatchTable — consume server pages instead of slicing

In `frontend/src/components/BatchTable.vue` `<script setup>`:

- Delete the local `page`/`pageSize` refs, the `pagedBatches` computed, and the
  `watch(() => store.batches, ...)` watcher.
- Rewrite `recalc` to set the **store** page size and reload (mirror SceneList):
```js
function recalc() {
  const wrap = tableWrap.value
  if (!wrap) return
  const thH = wrap.querySelector('.arco-table-th')?.getBoundingClientRect().height || 36
  const rowH = wrap.querySelector('tbody .arco-table-tr')?.getBoundingClientRect().height || 40
  const fit = Math.max(3, Math.floor((wrap.clientHeight - thH) / rowH))
  if (fit !== store.batchPageSize) {
    store.batchPageSize = fit
    store.batchPage = 1
    store.loadBatches()
  }
}
```
- Keep the `onMounted`/`onUnmounted` ResizeObserver block as-is (it calls
  `recalc`). Remove `nextTick` from imports only if no longer used; keep `watch`
  removed. (Leave other imports intact.)
- In `<template>`, change the table `:data` from `pagedBatches` to
  `store.batches` (`BatchTable.vue:140`).
- Change the Pager wiring (`BatchTable.vue:167-170`) to:
```html
      <Pager
        :total="store.batchTotal" :page-size="store.batchPageSize" :current="store.batchPage"
        @change="(p) => { store.batchPage = p; store.loadBatches() }" />
```
- Fix `exportCsv` to export ALL batches (not just the current page) by fetching
  without pagination. Replace its first line (`const head = ...` stays) — change
  the data source:
```js
async function exportCsv() {
  const head = '批次ID,场景ID,P4版本,平台,检查点数,创建时间'
  const { items } = await api.batches(store.filters)  // 不带分页 -> 全量
  const rows = items.map(b =>
    [b.id, b.scene_id, b.p4_version, b.platform, b.scene_count, b.created_at].join(','))
  const blob = new Blob(['﻿' + head + '\n' + rows.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'pixelcomparison_batches.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}
```
  Add `import { api } from '../api'` at the top of `BatchTable.vue` if not already
  imported (check the existing imports; `store` is imported, `api` may not be).

### Step 4: FilterSidebar — reset to page 1 when filters apply

In `frontend/src/components/FilterSidebar.vue` `apply`:
```js
async function apply() {
  store.batchPage = 1
  await store.loadBatches()
  Message.success('筛选已应用')
}
```
(`reset` calls `apply`, so it's covered.)

### Step 5: Backend regression tests

Create `backend/tests/test_pagination.py`:

```python
def _seed(client, n):
    for i in range(n):
        r = client.post("/api/batches", json={
            "id": f"b{i:02d}", "scene_id": "S", "p4_version": i, "platform": "Windows"})
        assert r.status_code == 201, r.text


def test_no_params_returns_all(client):
    _seed(client, 5)
    body = client.get("/api/batches").json()
    assert body["total"] == 5
    assert len(body["items"]) == 5


def test_pagination_slices(client):
    _seed(client, 5)
    p1 = client.get("/api/batches", params={"page": 1, "page_size": 2}).json()
    assert p1["total"] == 5
    assert p1["page"] == 1 and p1["page_size"] == 2
    assert len(p1["items"]) == 2

    p3 = client.get("/api/batches", params={"page": 3, "page_size": 2}).json()
    assert len(p3["items"]) == 1  # 5 items, last page has the remainder

    # pages don't overlap
    ids_p1 = {b["id"] for b in p1["items"]}
    ids_p2 = {b["id"] for b in client.get(
        "/api/batches", params={"page": 2, "page_size": 2}).json()["items"]}
    assert ids_p1.isdisjoint(ids_p2)


def test_pagination_respects_filters(client):
    _seed(client, 3)
    client.post("/api/batches", json={
        "id": "other", "scene_id": "OTHER", "p4_version": 9, "platform": "Windows"})
    body = client.get("/api/batches", params={
        "scene_id": "S", "page": 1, "page_size": 10}).json()
    assert body["total"] == 3  # 'other' excluded by filter
```

**Verify**:
- From `backend/`: `.\.venv\Scripts\python -m pytest -q` → all pass.
- From `frontend/`: `npm run build` → `✓ built`, exit 0.
- Manual smoke (optional but recommended): start backend + open the batch table,
  confirm rows fill the height, the pager pages through server-side, "应用筛选"
  resets to page 1, and "导出列表" exports more rows than one page when there are
  many batches.

### Step 6: Update the plan index

Set this plan's status to DONE in `plans/README.md`.

## Test plan

- `backend/tests/test_pagination.py`: no params → all rows + correct `total`;
  `page`/`page_size` slices correctly and pages are disjoint; pagination still
  respects filters (`total` reflects filtered count). Pattern: plan 001 fixtures.
- Frontend has no unit harness — gate is `npm run build` plus the manual smoke
  steps above.

## Done criteria

ALL must hold:

- [ ] `GET /api/batches` accepts `page`/`page_size`; with `page_size` it returns
      at most that many items and a full `total`; without it, returns all (old
      behavior). Response includes `total`, `page`, `page_size`, `items`.
- [ ] `store.js` has `batchPage`/`batchPageSize` and `loadBatches` sends them.
- [ ] `BatchTable.vue` no longer slices client-side (`pagedBatches` removed,
      `store.batches` table not exceeding `batchPageSize` rows), pager is
      server-driven, and `exportCsv` fetches all batches.
- [ ] `FilterSidebar.apply` resets `batchPage` to 1.
- [ ] From `backend/`: `pytest -q` exits 0 with the 3 new tests passing.
- [ ] From `frontend/`: `npm run build` exits 0.
- [ ] `git status` shows only in-scope files changed.
- [ ] `plans/README.md` status row for 005 says DONE.

## STOP conditions

Stop and report if:

- Any "Current state" excerpt doesn't match the live files (drift).
- After the change the batch table shows no rows or pages incorrectly and the
  cause isn't obvious within one fix attempt — report with the network response
  for `/api/batches?page=1&page_size=...`.
- `npm run build` fails for a reason tied to these edits (e.g. `api` not
  imported in `BatchTable.vue`) and isn't fixed by adding the import.
- You find another consumer of `store.batches` that assumes it holds *all*
  batches (besides `exportCsv`, which this plan handles) — report it rather than
  guessing whether it needs the full list.

## Maintenance notes

- `/api/comparisons` was intentionally left un-paginated; if the comparisons
  history grows large, apply the same pattern there (and update
  `store.loadComparisons` + `ResultSummary.vue`).
- The per-row COUNT in `batch_dto` (deferred N+1 finding) still runs once per
  returned row — now bounded by `page_size`, so the urgency drops, but it's the
  natural next optimization (batch the counts into one grouped query).
- Reviewer should confirm `total` is computed **before** offset/limit (full
  count), and that the dynamic-height `recalc` doesn't loop (it only reloads when
  `fit !== store.batchPageSize`).
</content>
