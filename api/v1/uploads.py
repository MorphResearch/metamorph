"""POST /v1/uploads — save user-uploaded images into the task workspace.

图片以 base64 形式从浏览器上传，保存到目标工作空间的 uploads/ 子目录，
返回服务端路径；前端在消息气泡中展示缩略图，模型可通过文件名感知上传内容。
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from pathlib import Path

from api.middleware import json_response, safe_workspace_id
from api.workers import TaskWorker

_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 单图上限 10MB
_MAX_FILES = 6


def save_uploads(handler: object, worker: TaskWorker, body: bytes) -> None:
    """Save uploaded images and return their workspace-relative paths."""
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        json_response(handler, 400, {"error": f"invalid json: {exc}"})
        return
    if not isinstance(payload, dict):
        json_response(handler, 400, {"error": "JSON body must be an object"})
        return

    files = payload.get("files")
    if not isinstance(files, list) or not files:
        json_response(handler, 400, {"error": "files is required"})
        return
    if len(files) > _MAX_FILES:
        json_response(handler, 400, {"error": f"too many files (max {_MAX_FILES})"})
        return

    # 目标目录：优先绝对路径，其次默认 workspace/<id>
    workspace_path = str(payload.get("workspace_path", "")).strip()
    if workspace_path:
        base = Path(workspace_path).expanduser().resolve()
        if not base.exists() or not base.is_dir():
            json_response(handler, 400, {"error": f"workspace_path is not an existing directory: {workspace_path}"})
            return
    else:
        try:
            workspace_id = safe_workspace_id(payload.get("workspace_id", "default"))
        except ValueError as exc:
            json_response(handler, 400, {"error": str(exc)})
            return
        base = worker.settings.workspace_root / workspace_id

    upload_dir = base / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict):
            json_response(handler, 400, {"error": "each file must be an object"})
            return
        name = str(item.get("name", "image.png")).strip() or "image.png"
        ext = Path(name).suffix.lower()
        if ext not in _ALLOWED_EXTS:
            json_response(handler, 400, {"error": f"unsupported image type: {ext or '(none)'}"})
            return
        data_b64 = str(item.get("data_base64", ""))
        if not data_b64:
            json_response(handler, 400, {"error": "data_base64 is required"})
            return
        # 兼容 data URL 前缀（data:image/png;base64,xxxx）
        if "," in data_b64 and data_b64.strip().startswith("data:"):
            data_b64 = data_b64.split(",", 1)[1]
        try:
            raw = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            json_response(handler, 400, {"error": f"invalid base64 in {name}: {exc}"})
            return
        if len(raw) > _MAX_FILE_BYTES:
            json_response(handler, 400, {"error": f"{name} exceeds 10MB limit"})
            return
        saved_name = f"{uuid.uuid4().hex[:12]}{ext}"
        target = upload_dir / saved_name
        target.write_bytes(raw)
        saved.append({"name": name, "saved_path": str(target), "url_path": f"uploads/{saved_name}"})

    json_response(handler, 201, {"saved": saved})
