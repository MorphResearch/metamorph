"""Run a small, offline BrowseComp-Plus smoke evaluation for Metamorph.

The runner intentionally exposes only a local FTS5 retriever over the fixed
BrowseComp-Plus corpus.  It is suitable for validating DAG execution,
budgeting, causal audits, and telemetry before a full official evaluation.
It is *not* a replacement for the official BM25/Qwen-judge leaderboard setup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pyarrow.parquet as pq
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Settings
from graphs.agent import run_agent
from llm.client import build_client
from multiagent.models import BudgetPolicy
from multiagent.orchestrator import MultiAgentOrchestrator
from state.events import EventLogger
from tools.base import TOOL_REGISTRY, register


class BrowseCompSearchInput(BaseModel):
    """Search only the local fixed BrowseComp-Plus corpus."""

    query: str = Field(..., min_length=1, max_length=2_000, description="检索词")
    max_results: int = Field(5, ge=1, le=20, description="返回文档数量")


class LocalCorpusSearch:
    """FTS5 retrieval with per-task telemetry and bounded document snippets."""

    def __init__(self, index_path: Path, snippet_chars: int = 1_400) -> None:
        self.index_path = index_path
        self.snippet_chars = snippet_chars
        self.call_count = 0
        self.retrieved_docids: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _match_query(query: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9]+", query.lower())[:24]
        if not tokens:
            raise ValueError("query has no searchable terms")
        return " OR ".join(f'"{token}"' for token in tokens)

    def search(self, query: str, max_results: int = 5) -> str:
        match = self._match_query(query)
        max_results = min(8, max_results)
        with sqlite3.connect(f"file:{self.index_path}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT docid, url, substr(text, 1, ?) AS snippet "
                "FROM documents WHERE documents MATCH ? "
                "ORDER BY bm25(documents) LIMIT ?",
                (self.snippet_chars, match, max_results),
            ).fetchall()
        with self._lock:
            self.call_count += 1
            self.retrieved_docids.update(str(row[0]) for row in rows)
        return json.dumps(
            [
                {"docid": row[0], "url": row[1], "text": row[2]}
                for row in rows
            ],
            ensure_ascii=False,
        )


class Telemetry:
    """Collect all LLM calls, including ablations and causal replays."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tool_calls = 0
        self.latency_seconds = 0.0

    def add(self, metrics: dict[str, Any]) -> None:
        with self._lock:
            self.calls += 1
            self.total_tokens += int(metrics.get("total_tokens", 0) or 0)
            self.prompt_tokens += int(metrics.get("prompt_tokens", 0) or 0)
            self.completion_tokens += int(metrics.get("completion_tokens", 0) or 0)
            self.tool_calls += int(metrics.get("tool_calls", 0) or 0)
            self.latency_seconds += float(metrics.get("latency_seconds", 0.0) or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.calls,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tool_calls": self.tool_calls,
            "sum_role_latency_seconds": round(self.latency_seconds, 6),
        }


def _corpus_files(corpus_dir: Path) -> list[Path]:
    files = sorted((corpus_dir / "data").glob("*.parquet"))
    if len(files) != 7:
        raise RuntimeError(f"expected 7 corpus parquet files, found {len(files)}")
    return files


def build_index(corpus_dir: Path, index_path: Path, rebuild: bool) -> int:
    """Build a reproducible SQLite FTS5 index without exposing corpus text."""

    if index_path.exists() and not rebuild:
        try:
            with sqlite3.connect(index_path) as connection:
                row = connection.execute("SELECT value FROM metadata WHERE key = 'document_count'").fetchone()
        except sqlite3.Error:
            row = None
        if row:
            return int(row[0])

    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        index_path.unlink()
    files = _corpus_files(corpus_dir)
    count = 0
    with sqlite3.connect(index_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("CREATE VIRTUAL TABLE documents USING fts5(docid UNINDEXED, text, url UNINDEXED, tokenize='porter unicode61')")
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for parquet_path in files:
            table = pq.ParquetFile(parquet_path)
            for batch in table.iter_batches(batch_size=256, columns=["docid", "text", "url"]):
                columns = batch.to_pydict()
                rows = zip(columns["docid"], columns["text"], columns["url"])
                connection.executemany("INSERT INTO documents (docid, text, url) VALUES (?, ?, ?)", rows)
                count += batch.num_rows
            connection.commit()
        connection.execute("INSERT INTO metadata (key, value) VALUES ('document_count', ?)", (str(count),))
        connection.commit()
    return count


@contextmanager
def isolated_benchmark_tool(searcher: LocalCorpusSearch) -> Iterator[None]:
    """Disable all non-benchmark tools for a fair fixed-corpus run."""

    original = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()
    register("browsecomp_search", BrowseCompSearchInput, searcher.search)
    try:
        yield
    finally:
        TOOL_REGISTRY.clear()
        TOOL_REGISTRY.update(original)


def load_queries(dataset_path: Path, limit: int) -> list[dict[str, Any]]:
    with dataset_path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    if len(rows) != 830:
        raise RuntimeError(f"expected 830 benchmark queries, found {len(rows)}")
    return rows[:limit]


def run_one(
    *,
    query: dict[str, Any],
    searcher: LocalCorpusSearch,
    settings: Settings,
    run_root: Path,
    max_turns: int,
    max_causal_audits: int,
    token_budget: int,
    max_completion_tokens: int,
) -> dict[str, Any]:
    query_id = str(query["query_id"])
    client = build_client(settings.provider, settings.model_name, settings.base_url, settings.api_key_env)
    telemetry = Telemetry()
    event_dir = run_root / "events" / query_id
    logger = EventLogger(event_dir)
    task = (
        "这是 BrowseComp-Plus 的固定语料研究任务。只能使用 browsecomp_search，"
        "不得使用外部知识或假设可访问互联网。基于检索证据给出简洁答案；"
        "证据不足时明确说明不确定性。\n\n问题：\n"
        + str(query["query"])
    )

    def run_role(prompt: str, agent_id: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        role_id = agent_id.rsplit(".", 1)[-1]
        can_retrieve = role_id in {"researcher", "critic"}
        answer = run_agent(
            client=client.client,
            model_name=client.model_name,
            messages=[{"role": "user", "content": prompt}],
            logger=EventLogger(event_dir / "agents" / agent_id),
            data_dir=run_root / "metamorph_state",
            workspace_root=PROJECT_ROOT,
            max_turns=1 if role_id == "synthesizer" else max_turns,
            adapter=client.adapter,
            metrics=metrics,
            allowed_tool_names={"browsecomp_search"} if can_retrieve else set(),
            max_tool_calls=1 if can_retrieve else 0,
        )
        telemetry.add(metrics)
        return {"answer": answer, "metrics": metrics}

    started = time.perf_counter()
    policy = BudgetPolicy(
        max_causal_audits=max_causal_audits,
        max_total_tokens=token_budget,
        max_completion_tokens=max_completion_tokens,
    )
    with isolated_benchmark_tool(searcher):
        result = MultiAgentOrchestrator(
            runner=run_role,
            data_dir=run_root / "metamorph_state",
            logger=logger,
            max_parallelism=3,
            budget_policy=policy,
            enable_evaluator=False,
        ).run(task, source_run=query_id)
    wall_seconds = time.perf_counter() - started
    return {
        "query_id": query_id,
        "tool_call_counts": {"browsecomp_search": searcher.call_count},
        "status": "completed" if result.get("answer") else "failed",
        "retrieved_docids": sorted(searcher.retrieved_docids),
        "result": [{"type": "output_text", "output": result.get("answer", "")}],
        "metadata": {
            "provider": client.provider,
            "model": client.model_name,
            "runner": "metamorph-local-fts-smoke",
            "telemetry": telemetry.to_dict(),
            "wall_latency_seconds": round(wall_seconds, 6),
            "contribution_report": result.get("contribution_report", {}),
            "causal_audits": result.get("causal_audits", []),
            "lesson_admissions": result.get("lesson_admissions", []),
            "budget_ledger": result.get("budget_ledger", {}),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline BrowseComp-Plus smoke runner for Metamorph")
    parser.add_argument("--benchmark-dir", type=Path, default=PROJECT_ROOT / "benchmarks" / "browsecomp-plus")
    parser.add_argument("--sample-size", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--max-causal-audits", type=int, default=1)
    parser.add_argument("--token-budget", type=int, default=80_000)
    parser.add_argument("--max-completion-tokens", type=int, default=2_048)
    parser.add_argument("--rebuild-index", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    benchmark_dir = args.benchmark_dir.resolve()
    corpus_dir = benchmark_dir / "data" / "corpus"
    dataset_path = benchmark_dir / "data" / "browsecomp_plus_decrypted.jsonl"
    index_path = benchmark_dir / "data" / "browsecomp_plus_fts.sqlite"
    run_root = benchmark_dir / "runs" / f"metamorph-local-fts-smoke-{time.strftime('%Y%m%d-%H%M%S')}"
    run_root.mkdir(parents=True, exist_ok=True)
    document_count = build_index(corpus_dir, index_path, args.rebuild_index)
    queries = load_queries(dataset_path, args.sample_size)
    settings = Settings.from_environment(data_dir=run_root / "metamorph_state")
    if settings.provider != "deepseek":
        raise RuntimeError(f"expected METAMORPH_PROVIDER=deepseek, got {settings.provider!r}")
    os.environ["METAMORPH_MAX_OUTPUT_TOKENS"] = str(args.max_completion_tokens)

    summaries: list[dict[str, Any]] = []
    for query in queries:
        searcher = LocalCorpusSearch(index_path)
        output = run_one(
            query=query,
            searcher=searcher,
            settings=settings,
            run_root=run_root,
            max_turns=args.max_turns,
            max_causal_audits=args.max_causal_audits,
            token_budget=args.token_budget,
            max_completion_tokens=args.max_completion_tokens,
        )
        output_path = run_root / f"{output['query_id']}.json"
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        telemetry = output["metadata"]["telemetry"]
        summaries.append({
            "status": output["status"],
            "llm_calls": telemetry["llm_calls"],
            "total_tokens": telemetry["total_tokens"],
            "tool_calls": telemetry["tool_calls"],
            "retrieved_docs": len(output["retrieved_docids"]),
            "wall_latency_seconds": output["metadata"]["wall_latency_seconds"],
        })
    summary = {
        "sample_size": len(summaries),
        "document_count": document_count,
        "index": str(index_path),
        "run_dir": str(run_root),
        "judge": "not run; use the official Qwen3-32B judge only for the final evaluation",
        "aggregate": {
            "completed": sum(item["status"] == "completed" for item in summaries),
            "llm_calls": sum(item["llm_calls"] for item in summaries),
            "total_tokens": sum(item["total_tokens"] for item in summaries),
            "tool_calls": sum(item["tool_calls"] for item in summaries),
            "retrieved_docs": sum(item["retrieved_docs"] for item in summaries),
            "wall_latency_seconds": round(sum(item["wall_latency_seconds"] for item in summaries), 6),
        },
    }
    (run_root / "smoke_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
