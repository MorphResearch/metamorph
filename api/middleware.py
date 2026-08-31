"""HTTP request middleware: path-traversal guard, error handling, response helpers.

Provides a thin middleware layer around the raw ``BaseHTTPRequestHandler`` so
route handlers stay focused on business logic.
"""

from __future__ import annotations

import json
import hmac
import mimetypes
import os
from pathlib import Path
from typing import Any


def json_response(handler: Any, status: int, payload: object) -> None:
    """Send a JSON response with the given status code and payload."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def static_file(
    handler: Any,
    relative: str,
    static_root: Path,
) -> bool:
    """Serve a static file if it exists within ``static_root``.

    Returns ``True`` when a file was served, ``False`` when not found (so the
    caller can fall through to 404). Includes a path-traversal guard.
    """
    root = static_root.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    if not target.is_file():
        return False
    content_type, _ = mimetypes.guess_type(str(target))
    body = target.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type or "application/octet-stream")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def safe_workspace_id(value: str) -> str:
    """Validate that ``value`` is a simple workspace name (no traversal)."""
    from pathlib import Path as _P

    value = str(value).strip()
    if (
        not value
        or _P(value).name != value
        or value in {".", ".."}
        or "\\" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("workspace_id must be a simple workspace name")
    return value


def is_authorized(handler: Any, token_env: str) -> bool:
    """Require a Bearer token when the server operator configured one."""
    expected = os.getenv(token_env)
    if not expected:
        return True
    authorization = str(handler.headers.get("Authorization", ""))
    return hmac.compare_digest(authorization, f"Bearer {expected}")
