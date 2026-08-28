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

    task = str(payload.get("task", "")).strip()
    if not task:
        json_response(handler, 400, {"error": "task is required"})
        return

    conversation_id = payload.get("conversation_id")
    if conversation_id:
        conversation_id = str(conversation_id).strip() or None

    try:
        workspace_id = safe_workspace_id(payload.get("workspace_id", "default"))
    except ValueError as exc:
        json_response(handler, 400, {"error": str(exc)})
        return

    workspace = worker.settings.workspace_root / workspace_id
    run_id, conv_id = worker.submit(task, workspace, conversation_id=conversation_id)
    json_response(handler, 202, {"run_id": run_id, "conversation_id": conv_id, "status": "queued"})
