"""A tiny, synthetic SQLite engineering fixture behind a metered service."""

from __future__ import annotations

import sqlite3
import re
import secrets
from dataclasses import dataclass
from pathlib import Path


class QueryRejected(PermissionError):
    pass


@dataclass
class MeteredSQLite:
    database_path: Path
    max_queries: int
    successful_queries: int = 0
    failed_queries: int = 0
    blocked_queries: int = 0

    def query(self, sql: str) -> list[tuple[object, ...]]:
        normalized = sql.strip()
        forbidden = (";", "attach", "detach", "pragma", "load_extension", "vacuum", "begin", "commit")
        if not normalized.lower().startswith("select") or any(word in normalized.lower() for word in forbidden):
            self.failed_queries += 1
            raise QueryRejected("only one read-only SELECT statement is permitted")
        if self.successful_queries + self.failed_queries >= self.max_queries:
            self.blocked_queries += 1
            raise QueryRejected("query budget exhausted")
        connection = sqlite3.connect(f"file:{self.database_path}?mode=ro&immutable=1", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(normalized).fetchall()
        except sqlite3.Error:
            self.failed_queries += 1
            raise
        finally:
            connection.close()
        self.successful_queries += 1
        return rows

    @property
    def total_queries(self) -> int:
        return self.successful_queries + self.failed_queries


def create_local_fixture(service_root: Path, max_queries: int = 8) -> MeteredSQLite:
    """Create non-sensitive synthetic data; answer keys stay out of agent roots."""
    service_root.mkdir(parents=True, exist_ok=True)
    database_path = service_root / "fixture.sqlite"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS regions (region TEXT PRIMARY KEY, cluster TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (sample_id INTEGER PRIMARY KEY, region TEXT NOT NULL, value INTEGER NOT NULL);
            DELETE FROM regions; DELETE FROM observations;
            INSERT INTO regions VALUES ('north', 'alpine'), ('south', 'coastal');
            INSERT INTO observations(region, value) VALUES ('north', 11), ('north', 17), ('south', 5), ('south', 7);
            """
        )
        connection.commit()
    finally:
        connection.close()
    return MeteredSQLite(database_path=database_path, max_queries=max_queries)


def create_atomic_file_io_fixture(service_root: Path, max_queries: int = 6, marker: str | None = None) -> tuple[MeteredSQLite, str]:
    """Create a one-row, per-run file-I/O control fixture outside agent paths."""
    service_root.mkdir(parents=True, exist_ok=True)
    database_path = service_root / "atomic_io.sqlite"
    marker = marker or f"atomic-io-{secrets.token_urlsafe(24)}"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript("CREATE TABLE IF NOT EXISTS io_probe (payload TEXT NOT NULL); DELETE FROM io_probe;")
        connection.execute("INSERT INTO io_probe(payload) VALUES (?)", (marker,))
        connection.commit()
    finally:
        connection.close()
    return MeteredSQLite(database_path=database_path, max_queries=max_queries), marker


def score_local_fixture_answer(task_id: str, answer: str) -> dict[str, object]:
    """Runner-only deterministic scoring for the two synthetic smoke tasks.

    This evaluator is never mounted at an agent path and is not a benchmark
    scorer.  It labels only the observed final answer; it does not rewrite it
    or decide whether an observed memory artifact was useful.
    """
    normalized = answer.lower()
    if task_id == "local_fixture_u1_practice_region_cluster":
        required = ("north", "alpine", "south", "coastal")
        return {"scored": True, "correct": all(value in normalized for value in required), "reference_kind": "local_fixture_only"}
    if task_id == "local_fixture_estimate_coastal_mean":
        numbers = [float(value) for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", normalized)]
        return {"scored": True, "correct": any(abs(value - 6.0) < 1e-9 for value in numbers), "reference_kind": "local_fixture_only"}
    return {"scored": False, "correct": None, "reference_kind": "unknown_task"}


def classify_local_fixture_result(answer: str, runner_stop_reason: str | None, score: dict[str, object]) -> dict[str, object]:
    """Keep a runner return, evaluator execution, and task success distinct."""
    looks_like_unexecuted_tool_text = "tool_calls" in answer and "invoke" in answer
    answer_accepted = bool(answer) and runner_stop_reason != "tool_budget_exhausted" and not looks_like_unexecuted_tool_text
    return {
        "runner_returned_nonempty_text": bool(answer),
        "runner_stop_reason": runner_stop_reason,
        "unexecuted_tool_text_detected": looks_like_unexecuted_tool_text,
        "answer_accepted_as_task_answer": answer_accepted,
        "evaluator_executed": score.get("scored") is True,
        "task_correct": score.get("correct") if answer_accepted else False,
    }
