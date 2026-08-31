"""HTTP router: dispatches requests to versioned handlers.

Replaces the monolithic ``routes.py`` with a cleaner routing table. The
ThreadingHTTPServer is configured here, delegating request handling through
``_RouteHandler`` which dispatches on path prefix.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .middleware import is_authorized, json_response, static_file
from .workers import TaskWorker
from .v1 import conversations, info, runs, tasks
from config import Settings


class _RouteHandler(BaseHTTPRequestHandler):
    worker: TaskWorker
    static_root: Path

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")

        if path.startswith("/v1/") and not is_authorized(self, self.worker.settings.api_token_env):
            json_response(self, 401, {"error": "unauthorized"})
            return

        # Serve static frontend for root and /static/ paths.
        if path in {"", "/"} or path == "/index.html":
            if not static_file(self, "index.html", self.static_root):
                json_response(self, 404, {"error": "not found"})
            return
        if path.startswith("/static/"):
            if not static_file(self, path[len("/static/"):], self.static_root):
                json_response(self, 404, {"error": "not found"})
            return

        # /v1/info
        if path == "/v1/info":
            info.handle_get(self, self.worker.settings)
            return

        # /v1/runs
        if path == "/v1/runs":
            runs.list_runs(self, self.worker)
            return

        # /v1/conversations
        if path == "/v1/conversations":
            conversations.list_conversations(self, self.worker)
            return

        # /v1/conversations/{id}
        if len(parts) == 4 and parts[1:3] == ["v1", "conversations"]:
            conversations.get_conversation(self, self.worker, parts[3])
            return

        # /v1/runs/{id}/events
        if len(parts) == 5 and parts[1:3] == ["v1", "runs"] and parts[4] == "events":
            runs.get_events(self, self.worker, parts[3])
            return

        # /v1/runs/{id}
        if len(parts) == 4 and parts[1:3] == ["v1", "runs"]:
            runs.get_run(self, self.worker, parts[3])
            return

        json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if path.startswith("/v1/") and not is_authorized(self, self.worker.settings.api_token_env):
            json_response(self, 401, {"error": "unauthorized"})
            return
        if path != "/v1/tasks":
            json_response(self, 404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                json_response(self, 413, {"error": "request body is too large"})
                return
            body = self.rfile.read(length) if length > 0 else b"{}"
        except ValueError:
            json_response(self, 400, {"error": "invalid Content-Length"})
            return
        tasks.submit_task(self, self.worker, body)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8787, static_root: Path | None = None) -> None:
    """Start the HTTP API + static frontend server."""
    if host not in {"127.0.0.1", "localhost", "::1"} and not os.getenv(settings.api_token_env):
        raise RuntimeError(f"refusing to bind API to {host!r} without {settings.api_token_env}")
    resolved_root = static_root or (Path(__file__).resolve().parent / "frontend")
    worker = TaskWorker(settings)
    handler_cls = type("MetamorphHandler", (_RouteHandler,), {
        "worker": worker,
        "static_root": resolved_root,
    })
    server = ThreadingHTTPServer((host, port), handler_cls)
    print(f"Metamorph UI & API listening at http://{host}:{port}")
    server.serve_forever()
