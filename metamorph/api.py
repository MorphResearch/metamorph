from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .config import Settings
from .service import RunService


class _Handler(BaseHTTPRequestHandler):
    service: RunService

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")

        # 前端页面与静态资源（与 API 同源，避免跨域）
        if path in {"", "/"} or path == "/index.html":
            self._serve_static("index.html")
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
            return

        # 服务元信息
        if path == "/v1/info":
            settings = self.service.settings
            self._send(200, {
                "version": __version__,
                "provider": settings.provider,
                "model_name": settings.model_name,
                "allow_write": settings.allow_write,
                "workspace_root": str(settings.workspace_root),
            })
            return

        # 运行历史列表
        if path == "/v1/runs":
            self._send(200, self.service.list_runs())
            return

        # 单条运行详情
        if len(parts) == 4 and parts[1:3] == ["v1", "runs"]:
            run = self.service.get(parts[3])
            self._send(200 if run else 404, run or {"error": "run not found"})
            return

        # 单条运行的事件时间线
        if len(parts) == 5 and parts[1:3] == ["v1", "runs"] and parts[4] == "events":
            run = self.service.get(parts[3])
            self._send(200 if run else 404, self.service.events(parts[3]) if run else {"error": "run not found"})
            return

        self._send(404, {"error": "not found"})

    def _serve_static(self, relative: str) -> None:
        root = self.static_root.resolve()
        target = (root / relative).resolve()
        # 防止路径穿越：目标必须仍在静态根目录内
        if not str(target).startswith(str(root)) or not target.is_file():
            self._send(404, {"error": "not found"})
            return
        content_type, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if path != "/v1/tasks":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            task = str(payload.get("task", "")).strip()
            workspace_id = str(payload.get("workspace_id", "default")).strip()
            if not task:
                raise ValueError("task is required")
            if not workspace_id or Path(workspace_id).name != workspace_id or workspace_id in {".", ".."}:
                raise ValueError("workspace_id must be a simple workspace name")
            workspace = self.service.settings.workspace_root / workspace_id
            run_id = self.service.submit(task, workspace)
            self._send(202, {"run_id": run_id, "status": "queued"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8787, static_root: Path | None = None) -> None:
    resolved_root = static_root or (Path(__file__).resolve().parent / "frontend")
    service = RunService(settings)
    handler = type("MetamorphHandler", (_Handler,), {"service": service, "static_root": resolved_root})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Metamorph UI & API listening at http://{host}:{port}")
    server.serve_forever()
