"""SceneScope 热力图离线查看器（仅监听本机，只读）。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.gpm_offline_workspace import (  # noqa: E402
    OfflineHeatmapWorkspace,
    OfflineWorkspaceError,
)


def _first(query: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = query.get(name)
    return values[0] if values else default


def _integer(query: dict[str, list[str]], name: str, default: int | None = None) -> int | None:
    value = _first(query, name)
    if value in {None, ""}:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise OfflineWorkspaceError(422, "INVALID_QUERY", f"{name} 必须是整数") from error


class OfflineRequestHandler(BaseHTTPRequestHandler):
    server_version = "SceneScopeOffline/2"

    @property
    def workspace(self) -> OfflineHeatmapWorkspace:
        return self.server.workspace  # type: ignore[attr-defined]

    @property
    def site_dir(self) -> Path:
        return self.server.site_dir  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _json(self, payload: object, status: int = 200) -> None:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _asset(self, pack_id: str, entry: str) -> None:
        content, content_type = self.workspace.asset(pack_id, entry)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        # 同批次可覆盖导出，缩略图 URL 保持身份稳定，必须重新验证内容。
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _static(self, path: str) -> None:
        relative = path.lstrip("/")
        candidate = (self.site_dir / relative).resolve() if relative else self.site_dir / "index.html"
        if self.site_dir not in candidate.parents or not candidate.is_file():
            candidate = self.site_dir / "index.html"
        if not candidate.is_file():
            raise OfflineWorkspaceError(500, "OFFLINE_SITE_MISSING", "离线查看器缺少前端文件")
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache" if candidate.name == "index.html" else "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/client-logs":
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length:
                self.rfile.read(min(length, 64 * 1024))
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json({"detail": {"code": "OFFLINE_READ_ONLY", "message": "离线查看器只支持读取"}}, 405)

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            # 新包在下一次 API 刷新时纳入工作区；静态文件和每张缩略图不重复扫描目录。
            if path.startswith("/api/"):
                self.workspace.reload_if_changed()
            if path == "/":
                target = self.workspace.entry_path()
                return self._redirect("/gpm-heatmap/" + quote(target.removeprefix("/gpm-heatmap/"), safe=""))
            if path == "/api/meta":
                catalog = self.workspace.catalog("main")
                return self._json({
                    "runtime_mode": "offline_heatmap",
                    "branch_tags": catalog["branch_tags"],
                    "scene_ids": [],
                    "scene_data_flags": {},
                    "platforms": [],
                    "baselines": [],
                })
            if path == "/api/settings":
                return self._json({})
            if path == "/api/gpm-heatmaps/catalog":
                return self._json(self.workspace.catalog(_first(query, "branch_tag", "main") or "main"))
            if path.startswith("/gpm-assets/offline/"):
                suffix = path.removeprefix("/gpm-assets/offline/")
                pack_id, separator, entry = suffix.partition("/")
                if not separator:
                    raise OfflineWorkspaceError(404, "GPM_ASSET_NOT_FOUND", "离线热力图资源不存在")
                return self._asset(pack_id, entry)

            parts = [part for part in path.split("/") if part]
            if len(parts) == 5 and parts[:2] == ["api", "gpm-heatmaps"] and parts[2] == "maps" and parts[4] == "frame":
                return self._json(self.workspace.frame(
                    parts[3],
                    _first(query, "branch_tag", "main") or "main",
                    _first(query, "platform"),
                    _integer(query, "shading_quality"),
                    _first(query, "batch_id"),
                    _integer(query, "nearest_p4_version"),
                    _integer(query, "preferred_p4_version"),
                ))
            if len(parts) == 5 and parts[:2] == ["api", "gpm-heatmaps"] and parts[2] == "maps" and parts[4] == "trends":
                platform = _first(query, "platform")
                quality = _integer(query, "shading_quality")
                if not platform or quality is None:
                    raise OfflineWorkspaceError(422, "INVALID_QUERY", "趋势查询缺少平台或画质")
                return self._json(self.workspace.map_trends(
                    parts[3], _first(query, "branch_tag", "main") or "main",
                    platform, quality, _integer(query, "days", 14) or 14,
                ))
            if len(parts) in {4, 5} and parts[:3] == ["api", "gpm-heatmaps", "points"]:
                try:
                    point_id = int(parts[3])
                except ValueError as error:
                    raise OfflineWorkspaceError(422, "INVALID_QUERY", "point_id 必须是整数") from error
                if len(parts) == 4:
                    return self._json(self.workspace.point(point_id))
                if parts[4] == "trends":
                    return self._json(self.workspace.point_trends(point_id, _integer(query, "days", 14) or 14))

            if path.startswith(("/screenshot", "/map-build", "/batch-management", "/settings")):
                return self._redirect(self.workspace.entry_path())
            if path.startswith("/api/"):
                raise OfflineWorkspaceError(404, "OFFLINE_API_NOT_FOUND", "离线查看器不支持该接口")
            return self._static(parsed.path)
        except OfflineWorkspaceError as error:
            self._json({"detail": {"code": error.code, "message": error.message}}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:  # 本地查看器仍需向用户显示可诊断错误，而不是直接退出。
            self._json({"detail": {"code": "OFFLINE_INTERNAL_ERROR", "message": str(error)}}, 500)


def main() -> int:
    executable_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    # 单文件打包资源在临时解包目录，业务配置和数据始终读取 EXE 同级目录。
    site_dir = Path(sys._MEIPASS) / "site" if getattr(sys, "frozen", False) else ROOT / "frontend" / "dist"
    parser = argparse.ArgumentParser(description="SceneScope 热力图离线查看器")
    parser.add_argument("--data", type=Path, default=executable_dir / "data", help=".ssheat 数据包目录")
    parser.add_argument("--config", type=Path, help="共享配置 ZIP；默认使用 data 同级的 config/heatmap.zip")
    parser.add_argument("--site", type=Path, default=site_dir, help="覆盖内嵌前端的 dist 目录")
    parser.add_argument("--port", type=int, default=0, help="本机端口，0 表示自动选择")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    workspace = OfflineHeatmapWorkspace(args.data, args.config)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), OfflineRequestHandler)
    server.workspace = workspace  # type: ignore[attr-defined]
    server.site_dir = args.site.resolve()  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"SceneScope 离线热力图：{url}")
    print(f"数据目录：{workspace.data_dir}")
    print(f"共享配置：{workspace.config_path}")
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
