# Plan 001: 将数据库日备份收拢到按日期隔离的快照目录

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving on. Stop on any condition
> listed under “STOP conditions”; do not improvise.
>
> **Drift check (run first)**:
>
> ```powershell
> git diff --stat 2c7d391..HEAD -- backend/app/backup.py backend/tests/test_backup.py README.md docs/使用文档.md
> git diff --stat -- backend/app/backup.py backend/tests/test_backup.py README.md docs/使用文档.md
> git diff --cached --stat -- backend/app/backup.py backend/tests/test_backup.py README.md docs/使用文档.md
> ```
>
> All three commands must show no in-scope drift. If any output appears, compare
> the live code with “Current state” and stop on a mismatch.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: migration
- **Planned at**: commit `2c7d391`, 2026-07-13

## Why this matters

The current flat `backup/db` layout mixes every daily snapshot with any SQLite
`-wal`/`-shm` sidecars. A date-scoped directory makes one day the restore and
retention unit, contains accidental auxiliary files, and leaves room for future
snapshot metadata. The operator already deleted all legacy backups, so the
implementation must support only the new layout—no migration or compatibility
branch is needed.

## Current state

- `backend/app/backup.py` creates `backup/db/shotdiff-YYYY-MM-DD.db`, validates
  it with `quick_check`, atomically publishes it, and prunes flat files by mtime.
- `backend/tests/test_backup.py` has three real-SQLite tests using `tmp_path`.
- `README.md` and `docs/使用文档.md` document the flat path and plain `mode=ro`
  validation, which can create sidecars.
- `<DATA_DIR>/backup` is currently absent and must be created lazily.
- Match the repository convention of small module functions, injected Path/time
  arguments, pytest monkeypatch/tmp_path, and Chinese operator-facing logs.

Required layout:

```text
<DATA_DIR>/backup/
  2026-07-13/
    db/
      shotdiff.db
```

For a custom `PIXELCOMP_DB_PATH`, preserve `DB_PATH.name` inside `db/`.

## Fixed function contracts

Implement these exact module-level names/signatures in `backend/app/backup.py`:

```python
BACKUP_ROOT = DATA_DIR / "backup"

def daily_backup_path(
    db_path: Path = DB_PATH,
    backup_root: Path = BACKUP_ROOT,
    now: datetime | None = None,
) -> Path: ...

def create_daily_backup(
    db_path: Path = DB_PATH,
    backup_root: Path = BACKUP_ROOT,
    now: datetime | None = None,
) -> Path | None: ...

def prune_backups(
    backup_root: Path = BACKUP_ROOT,
    retention_days: int = BACKUP_RETENTION_DAYS,
    now: datetime | None = None,
    db_name: str = DB_PATH.name,
) -> list[Path]: ...
```

Do not retain `BACKUP_DIR`, `backup_dir`, or `db_stem` compatibility aliases.
The scheduler calls the functions with defaults and logs `BACKUP_ROOT`.

Add these internal helpers as explicit test seams:

```python
def _validate_destination(connection: sqlite3.Connection) -> None: ...
def _cleanup_temp_files(temp: Path) -> None: ...
def _parse_backup_date(name: str) -> date | None: ...
```

`_validate_destination` sets/confirms `DELETE` journal mode and raises
`sqlite3.DatabaseError` unless `PRAGMA quick_check` is exactly `ok`.
`_cleanup_temp_files` removes only `temp`, `temp-journal`, `temp-wal`, and
`temp-shm`. `_parse_backup_date` accepts only `^\d{4}-\d{2}-\d{2}$`, parses with
`datetime.strptime`, and requires `strftime("%Y-%m-%d") == name`.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Targeted tests | `cd backend; .\.venv\Scripts\python -m pytest -q tests/test_backup.py` | exit 0, all pass |
| Backend regression | `cd backend; .\.venv\Scripts\python -m pytest -q` | exit 0, all pass |
| Frontend regression | `cd frontend; npm test; npm run build` | both exit 0 |
| Old path check | `rg -n 'backup/db|backup\\db' README.md docs/使用文档.md` | exit 1, no matches |
| Immutable check | `rg -n --pcre2 "mode=ro(?!&immutable=1)" README.md docs/使用文档.md backend/tests/test_backup.py` | exit 1, no matches |
| Diff hygiene | `git diff --check` | exit 0 |

## Scope

**In scope**:

- `backend/app/backup.py`
- `backend/tests/test_backup.py`
- `README.md`
- `docs/使用文档.md`
- `plans/README.md` (status only)

**Out of scope**:

- Legacy backup migration or flat-path compatibility.
- Database/API schemas, frontend behavior, comparison retention, image backup,
  scheduler interval, environment variable names, and default retention length.
- The pre-existing untracked root file `=ro`.

## Git workflow

- Stay on the operator-provided branch; do not rewrite history.
- Use one Chinese commit such as `优化数据库备份目录结构`.
- Do not push unless explicitly requested.

## Steps

### Step 1: Implement and test the new publication path

Update `backend/app/backup.py` and the creation tests together so the targeted
suite remains green at the end of the step.

`daily_backup_path()` resolves both inputs and returns
`backup_root/YYYY-MM-DD/db/db_path.name`. `create_daily_backup()` checks only the
final file for same-day deduplication, creates the final `db` parent lazily, and
places the UUID temp file in that same directory to preserve atomic `os.replace`.

Keep source access as SQLite URI `mode=ro` so committed source WAL data is
included. Back up into the temp connection, call `_validate_destination`, close
both connections, then publish with `os.replace`. The final file must report
`journal_mode=delete`. In `finally`, call `_cleanup_temp_files` regardless of
whether connection, backup, validation, close, or replace failed. Never issue a
checkpoint or journal-mode pragma against the source connection.

Add creation tests that assert:

- Exact path `<root>/2026-07-10/db/shotdiff.db`.
- A custom source filename is preserved.
- Committed source WAL rows are present.
- Source `.db-wal` size and SHA-256 are unchanged before/after backup while the
  source connection remains open.
- Published DB opened with `mode=ro&immutable=1` has `quick_check=ok`,
  `journal_mode=delete`, and no `-journal`/`-wal`/`-shm` siblings.
- A second same-day call returns `None`.
- A pre-existing empty date or `db` directory does not suppress creation.

**Verify**: targeted tests exit 0. Do not continue with failing path tests.

### Step 2: Implement and test safe date-directory retention

Update `prune_backups()` and its tests together. Enumerate only direct children
of `backup_root`; never use `rglob`. A candidate is eligible only when all are
true:

1. `_parse_backup_date(candidate.name)` returns a date.
2. `candidate` is a real directory, not a symlink.
3. `candidate.resolve()` equals `backup_root.resolve() / candidate.name` after
   resolving; this rejects junctions/symlinks redirected elsewhere or to another
   date directory.
4. `candidate/db` is a real, non-symlink directory whose resolved path equals
   `candidate.resolve() / "db"`; this rejects a nested junction/link escape.
5. `candidate/db/db_name` is a regular, non-symlink file whose resolved parent
   is the validated `db` directory.
6. The parsed date is strictly older than
   `(now or datetime.now()).date() - timedelta(days=retention_days)`.

If a candidate fails items 2–5, log a warning and skip it; continue pruning other
candidates. Malformed/non-date names are silently ignored. `retention_days <= 0`
removes nothing. Eligible date directories are backup-system-owned units:
`shutil.rmtree(candidate)` removes the expected DB plus any sidecars or future
metadata inside that date directory. Return the deleted date-directory paths.

Tests must cover expired/fresh dates, the exact cutoff (kept), retention 0,
`2026-7-1`, `2026-00-01`, `2026-02-30`, suffix names, missing DB, DB symlink,
`db` directory symlink/junction, date-directory symlink, a resolved-path mismatch
when supported, extra owned files inside an eligible snapshot (deleted with the
unit), and an unrelated non-date directory (untouched). On platforms where
creating a junction/symlink is unavailable, mark only that platform-specific
case skipped with the reason.

**Verify**: targeted tests exit 0.

### Step 3: Add deterministic failure-cleanup tests

Use the fixed internal helpers rather than inventing a connection abstraction:

- Monkeypatch `_validate_destination` with a function that creates exact temp
  `-journal`, `-wal`, and `-shm` siblings and then raises
  `sqlite3.DatabaseError`. Assert all temp artifacts are gone and no final DB
  exists.
- Monkeypatch `os.replace` to raise `OSError` after validation. Assert the temp
  DB and exact sidecars are gone and no final DB exists.
- Monkeypatch `_validate_destination` to raise before publication and assert the
  source WAL size/hash remains unchanged.

Do not monkeypatch `sqlite3.Connection.backup` or introduce a public connection
factory solely for tests.

**Verify**: targeted tests exit 0, including all failure paths.

### Step 4: Update documentation and stale-reference gates

Update both docs consistently:

- All trees and examples use `backup/YYYY-MM-DD/db/shotdiff.db`.
- Custom `PIXELCOMP_DB_PATH` preserves its basename inside the daily `db/`.
- Verification uses `mode=ro&immutable=1` and explains this prevents creating
  sidecars; the directory layout only contains sidecars if another tool creates
  them.
- Restore copies the chosen day's DB to the active DB path after stopping the
  backend.
- Replication guidance syncs the complete `backup/` tree.
- The date directory is the retention/deletion unit and must not contain
  operator-owned unrelated files.
- Do not mention migration or legacy compatibility.

Run both repository-search commands in “Commands”. They must return exit 1 with
no matches. Manually inspect all remaining occurrences from
`rg -n "backup|备份|mode=ro" README.md docs/使用文档.md` and confirm they describe
the new structure.

**Verify**: both search gates behave exactly as specified and `git diff --check`
passes.

### Step 5: Run the complete regression suite

Run targeted tests, full backend tests, frontend tests/build, both stale-reference
checks, and diff hygiene. Do not start the scheduler against production data;
`tmp_path` integration tests prove lazy directory creation.

`git status --short` must show only in-scope files, the plan status update, and
the pre-existing `=ro`. Mark Plan 001 DONE only after every command passes.

**Verify**: every applicable command exits with its expected code.

## Test plan

Use real SQLite databases and `tmp_path`, matching the existing test style.
Required test groups are:

- WAL-consistent publication, custom basename, idempotency, immutable integrity,
  DELETE journal mode, and absence of published sidecars.
- Source WAL size/hash unchanged.
- Validation and publication failure cleanup with sidecars actually created.
- Strict date parsing, cutoff semantics, retention 0, required DB ownership,
  full-unit deletion, and link/junction containment.

## Done criteria

- [ ] New snapshots use `<DATA_DIR>/backup/YYYY-MM-DD/db/<DB_PATH.name>`.
- [ ] Published snapshots are standalone, immutable-readable, `quick_check=ok`,
      `journal_mode=delete`, and have no sidecars.
- [ ] Source WAL content is unchanged by backup.
- [ ] Retention deletes only eligible, contained, expired owned date directories.
- [ ] No legacy migration/compatibility code exists.
- [ ] All targeted/full backend and frontend verification passes.
- [ ] Documentation and stale-reference checks pass.
- [ ] No out-of-scope file is modified; `plans/README.md` is DONE.

## STOP conditions

Stop and report when:

- Any drift check reports an in-scope mismatch.
- Atomic publication cannot stay on one filesystem.
- Correct behavior requires legacy migration or flat-path compatibility.
- The source WAL changes during the backup regression test.
- Safe retention requires following/removing a link or junction.
- A verification gate fails twice after a reasonable correction.
- The change would touch database/API schemas, frontend behavior, or images.

## Maintenance notes

- Date directories are reserved backup-system-owned deletion units. Revisit
  retention before adding new artifact types beneath them.
- Future validation examples must use immutable read-only mode.
- Reviewers should scrutinize `rmtree` containment and exact temp-sidecar cleanup.
- Same-disk snapshots still require separate off-disk replication for disk loss.
