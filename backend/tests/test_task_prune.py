import importlib

import app.db  # noqa: F401


def _fresh_main(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXELCOMP_DATA_DIR", str(tmp_path))
    # Reload the whole app package against the temp data dir. app.models binds
    # Base from app.db at import, so app.db AND every module that imported Base
    # must be reloaded before app.main, or create_all sees no tables.
    import app.db
    import app.models
    import app.service
    import app.settings
    import app.main
    importlib.reload(app.db)
    importlib.reload(app.models)
    importlib.reload(app.service)
    importlib.reload(app.settings)
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

    m._prune_tasks(now=m._TASK_TTL_SECONDS + 1)

    assert "old_done" not in m._TASKS
    assert "old_err" not in m._TASKS
    assert "running" in m._TASKS  # never pruned


def test_prune_keeps_recent_finished(tmp_path, monkeypatch):
    m = _fresh_main(tmp_path, monkeypatch)
    m._TASKS.clear()
    m._TASKS["recent"] = {"status": "done", "done": 1, "total": 1,
                          "comparison_id": 1, "error": None, "finished_at": 1000.0}
    m._prune_tasks(now=1000.0 + 5)
    assert "recent" in m._TASKS
