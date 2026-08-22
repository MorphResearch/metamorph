from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from .events import utc_now


class RunStore:
    """Small SQLite store for run state; events and artifacts live on disk."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "runs.db"
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

    def create(self, task: str, workspace: Path) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(run_id, task, workspace, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, task, str(workspace), "queued", now, now),
            )
        return run_id

    def update(self, run_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ?, result_json = ? WHERE run_id = ?",
                (status, utc_now(), json.dumps(result or {}, ensure_ascii=False), run_id),
            )

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json") or "{}")
        return result
