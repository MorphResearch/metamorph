"""Task worker management: daemon threads that execute agent runs.

Analogous to scilink-agent's scheduler design — each submitted task spawns
a daemon thread that runs the agent loop to completion. This module tracks
active workers and ensures graceful shutdown behaviour.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from config import Settings
from graphs.agent import run_agent as _run_agent
from llm.client import build_client
from state.events import EventLogger
from state.store import RunStore


class TaskWorker:
    """Manages the lifecycle of submitted agent runs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = RunStore(settings.data_dir)
        self._client = build_client(
            settings.provider,
            model_name=settings.model_name,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
        )
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()

    @property
    def client(self) -> Any:
        return self._client

    def submit(self, task: str, workspace: Path) -> str:
        """Register a new run and start a background worker thread."""
        resolved = workspace.expanduser().resolve()
        run_id = self.store.create(task, resolved)
        thread = threading.Thread(
            target=self._run, args=(run_id, task, resolved), daemon=True, name=f"worker-{run_id}"
        )
        with self._lock:
            self._workers.append(thread)
        thread.start()
        return run_id

    def _run(self, run_id: str, task: str, workspace: Path) -> None:
        run_dir = self.store.runs_dir / run_id
        logger = EventLogger(run_dir)
        self.store.update(run_id, "running")
        try:
            answer = _run_agent(
                client=self.client.client,
                model_name=self.client.model_name,
                messages=[{"role": "user", "content": task}],
                logger=logger,
                data_dir=self.settings.data_dir,
                workspace_root=workspace,
                max_turns=self.settings.max_steps,
            )
            result: dict[str, Any] = {
                "run_id": run_id,
                "status": "completed",
                "answer": answer,
                "provider": self.client.provider,
                "model": self.client.model_name,
            }
            logger.emit("run.evaluated", result=result)
            logger.write_json("result.json", result)
            self.store.update(run_id, result["status"], result)
        except Exception as exc:
            logger.emit("run.error", error=str(exc))
            result = {"run_id": run_id, "status": "failed", "error": str(exc)}
            self.store.update(run_id, "failed", result)

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get(run_id)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_recent(limit)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        logger = EventLogger(self.store.runs_dir / run_id)
        return logger.read_all()
