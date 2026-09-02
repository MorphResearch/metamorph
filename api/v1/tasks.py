"""POST /v1/tasks — task submission endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from api.middleware import json_response, safe_workspace_id
from api.workers import TaskWorker


def submit_task(
    handler: object,
    worker: TaskWorker,
    body: bytes,
) -> None:
    """Create a new agent task run and return the run id.

    Expects JSON body with ``task`` (str) and optional ``workspace_id``
    (defaults to ``default``). Returns HTTP 202 with ``{run_id, status}``.
    """
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        json_response(handler, 400, {"error": f"invalid json: {exc}"})
        return
    if not isinstance(payload, dict):
        json_response(handler, 400, {"error": "JSON body must be an object"})
        return

    task = str(payload.get("task", "")).strip()
    if not task:
        json_response(handler, 400, {"error": "task is required"})
        return

    conversation_id = payload.get("conversation_id")
    if conversation_id:
        conversation_id = str(conversation_id).strip() or None

    mode = str(payload.get("mode", worker.settings.mode)).strip() or worker.settings.mode
    if mode not in {"single", "multiagent"}:
        json_response(handler, 400, {"error": "mode must be single or multiagent"})
        return

    try:
        workspace_id = safe_workspace_id(payload.get("workspace_id", "default"))
    except ValueError as exc:
        json_response(handler, 400, {"error": str(exc)})
        return

    # 优先使用用户选择的本地文件夹（绝对路径），其次回退到默认 workspace/<id>
    workspace_path = str(payload.get("workspace_path", "")).strip()
    if workspace_path:
        candidate = Path(workspace_path).expanduser()
        if not candidate.is_absolute():
            json_response(handler, 400, {"error": "workspace_path must be an absolute path"})
            return
        candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_dir():
            json_response(handler, 400, {"error": f"workspace_path is not an existing directory: {workspace_path}"})
            return
        workspace = candidate
    else:
        workspace = worker.settings.workspace_root / workspace_id
    try:
        run_id, conv_id = worker.submit(task, workspace, conversation_id=conversation_id, mode=mode)
    except ValueError as exc:
        json_response(handler, 400, {"error": str(exc)})
        return
    json_response(handler, 202, {"run_id": run_id, "conversation_id": conv_id, "mode": mode, "status": "queued"})
