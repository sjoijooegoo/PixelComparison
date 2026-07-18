"""场景目录上报脚本的格式校验和真实 HTTP PUT 行为。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "report_scene_catalog.py"


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=10,
        check=False,
    )


def test_no_json_file_prints_required_data_format():
    result = _run()

    assert result.returncode == 2
    assert '"scene_id_order"' in result.stdout
    assert "数组顺序就是前端场景下拉框顺序" in result.stdout


def test_dry_run_rejects_duplicate_without_sending(tmp_path):
    payload = tmp_path / "catalog.json"
    payload.write_text(
        json.dumps({"scene_id_order": ["Scene", "Scene"]}),
        encoding="utf-8",
    )

    result = _run(str(payload), "--dry-run")

    assert result.returncode == 2
    assert "数据格式错误" in result.stderr
    assert "重复" in result.stderr


def test_uploads_utf8_json_with_put_and_verifies_response(tmp_path):
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):  # noqa: N802 - 标准库回调名称
            length = int(self.headers["Content-Length"])
            received["path"] = self.path
            received["content_type"] = self.headers["Content-Type"]
            received["payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
            body = json.dumps({
                "configured": True,
                "scene_id_order": received["payload"]["scene_id_order"],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = tmp_path / "catalog.json"
        expected = {"scene_id_order": ["森林_场景", "OtherScene"]}
        payload.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
        url = f"http://127.0.0.1:{server.server_port}/api/scene-catalog"

        result = _run(str(payload), "--url", url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stderr
    assert "上报成功" in result.stdout
    assert received == {
        "path": "/api/scene-catalog",
        "content_type": "application/json; charset=utf-8",
        "payload": expected,
    }
