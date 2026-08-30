from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from .events import utc_now


class RunStore:
    """SQLite store: run state, conversation history."""

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
                    conversation_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_conv "
                "ON conversation_messages(conversation_id, id)"
            )

    def create(self, task: str, workspace: Path, conversation_id: str | None = None) -> tuple[str, str]:
        """Create a run. Returns (run_id, conversation_id)."""
        run_id = uuid.uuid4().hex[:12]
        conv_id = conversation_id or uuid.uuid4().hex[:12]
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(run_id, conversation_id, task, workspace, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, conv_id, task, str(workspace), "queued", now, now),
            )
        return run_id, conv_id

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

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id, conversation_id, task, workspace, status, created_at, updated_at "
                "FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_conversation_runs(self, conversation_id: str) -> list[dict[str, Any]]:
        """Return all runs in one conversation, oldest first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json") or "{}")
            result.append(item)
        return result

    def get_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        """List distinct conversations with latest message preview."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.conversation_id,
                       c.task,
                       c.created_at,
                       (SELECT cm.content FROM conversation_messages cm
                        WHERE cm.conversation_id = c.conversation_id
                        ORDER BY cm.id DESC LIMIT 1) AS last_message,
                       (SELECT COUNT(*) FROM runs r WHERE r.conversation_id = c.conversation_id) AS run_count
                FROM (
                    SELECT DISTINCT conversation_id,
                           (SELECT r2.task FROM runs r2 WHERE r2.conversation_id = runs.conversation_id ORDER BY r2.created_at LIMIT 1) AS task,
                           (SELECT MIN(r3.created_at) FROM runs r3 WHERE r3.conversation_id = runs.conversation_id) AS created_at
                    FROM runs
                ) c
                ORDER BY c.created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- conversation
    def get_conversation(self, conversation_id: str) -> list[dict[str, str]]:
        """Return all messages in a conversation, oldest first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM conversation_messages "
                "WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        """Append a single message to the conversation history."""
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO conversation_messages(conversation_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, utc_now()),
            )

    def delete_conversation(self, conversation_id: str) -> int:
        """Delete a conversation and its runs. Returns deleted message count."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            connection.execute(
                "DELETE FROM runs WHERE conversation_id = ?",
                (conversation_id,),
            )
        return cursor.rowcount
