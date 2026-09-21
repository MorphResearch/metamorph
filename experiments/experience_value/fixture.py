"""A tiny, synthetic SQLite engineering fixture behind a metered service."""

from __future__ import annotations

import sqlite3
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

