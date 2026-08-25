"""GET /v1/runs and GET /v1/runs/{id} — run history and detail endpoints."""

from __future__ import annotations

from api.middleware import json_response
from api.workers import TaskWorker


def list_runs(handler: object, worker: TaskWorker, limit: int = 50) -> None:
    """Return the most recent runs (metadata only)."""
    json_response(handler, 200, worker.list_runs(limit))


def get_run(handler: object, worker: TaskWorker, run_id: str) -> None:
    """Return a single run by id, or 404."""
    run = worker.get(run_id)
    if run is None:
        json_response(handler, 404, {"error": "run not found"})
        return
    json_response(handler, 200, run)


def get_events(handler: object, worker: TaskWorker, run_id: str) -> None:
    """Return the full event log for a run, or 404."""
    run = worker.get(run_id)
    if run is None:
        json_response(handler, 404, {"error": "run not found"})
        return
    json_response(handler, 200, worker.events(run_id))
