from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .config import Settings
from .events import EventLogger
from .model import build_model
from .runtime import AgentRuntime
from .store import RunStore


class RunService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = RunStore(settings.data_dir)
        self.model = build_model(settings.provider, settings.model_name, settings.base_url, settings.api_key_env)

    def submit(self, task: str, workspace: Path) -> str:
        workspace = workspace.expanduser().resolve()
        run_id = self.store.create(task, workspace)
        thread = threading.Thread(target=self._run, args=(run_id, task, workspace), daemon=True)
        thread.start()
        return run_id

    def _run(self, run_id: str, task: str, workspace: Path) -> None:
        run_dir = self.store.runs_dir / run_id
        logger = EventLogger(run_dir)
        self.store.update(run_id, "running")
        try:
            runtime = AgentRuntime(
                model=self.model,
                max_steps=self.settings.max_steps,
                max_read_bytes=self.settings.max_read_bytes,
                allow_write=self.settings.allow_write,
            )
            result = runtime.run(task, workspace, logger, run_id)
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
