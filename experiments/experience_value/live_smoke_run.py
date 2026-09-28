"""Execute exactly the signed three-episode local E0 engineering smoke.

This module has no command that selects a model, increases a budget, or adds
episodes.  It reads only the explicit signed configuration file and uses the
existing provider client after its authorization is validated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from llm.adapters import ProviderAdapter

from .fixture import classify_local_fixture_result, create_local_fixture, score_local_fixture_answer
from .live import PriceSheet, ToolOnlySmokeConfig, build_authorized_client, run_tool_only_episode
from .records import BudgetError, CostLedger, LiveAuthorization
from .runner import ExperimentRunner, stable_hash
from .workspace import Snapshot, hash_tree


PRACTICE_TEXT = (
    "Use query_sql to inspect the synthetic SQLite fixture. Report which cluster is "
    "associated with the north region and which cluster is associated with the south "
    "region. You may save concise reusable evidence in /memory if you decide it is useful."
)
PROBE_TEXT = (
    "Use the permitted tools to determine the mean observation value for the coastal "
    "cluster. State a number and a brief basis."
)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _authorization(raw: dict[str, Any]) -> LiveAuthorization:
    auth = raw["authorization"]
    return LiveAuthorization(
        authorized=auth["authorized"], provider=raw["provider"], exact_model_id=raw["exact_model_id"],
        currency=auth["currency"], hard_cap=Decimal(auth["hard_cap_usd"]), max_requests=auth["max_provider_requests"],
        price_basis=auth["price_basis"], max_episodes=auth["max_episodes"],
    )


def _config(raw: dict[str, Any]) -> ToolOnlySmokeConfig:
    request = raw["request"]
    return ToolOnlySmokeConfig(
        provider=raw["provider"], exact_model_id=raw["exact_model_id"], base_url=raw["base_url"],
        api_key_env=raw["api_key_env_name_only"], max_input_characters=request["max_input_characters"],
        max_input_tokens_per_request=request["max_input_tokens_per_request"],
        max_output_tokens_per_request=request["max_output_tokens_per_request"],
        max_requests_per_episode=request["max_provider_requests_per_episode"],
        max_tool_calls_per_episode=request["max_tool_calls_per_episode"], timeout_seconds=request["timeout_seconds"],
        retries=request["automatic_retries"], temperature=request["temperature"],
        thinking_enabled=request["thinking_enabled"], reasoning_effort=request["reasoning_effort"],
    )


def _prices(raw: dict[str, Any]) -> PriceSheet:
    price = raw["budget"]
    return PriceSheet(
        Decimal(price["input_cache_miss_usd_per_million"]), Decimal(price["output_usd_per_million"]),
        price["price_source"], price["price_checked_on"],
    )


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _episode_evidence(records_path: Path, attempt_id: str, database: Any, answer: str, task_id: str, metrics: dict[str, Any], snapshot: Snapshot) -> dict[str, Any]:
    entries = [item for item in _events(records_path) if item.get("attempt_id") == attempt_id]
    writes = [item for item in entries if item["type"] == "agent.file_write"]
    reads = [item for item in entries if item["type"] == "agent.file_read"]
    sql = [item for item in entries if item["type"] == "agent.sql_query"]
    provider = [item for item in entries if item["type"] == "provider.request_finished"]
    prior_sql_feedback: list[dict[str, Any]] = []
    write_provenance: list[dict[str, Any]] = []
    for item in entries:
        if item["type"] == "tool.completed" and item.get("tool") == "query_sql":
            prior_sql_feedback.append({"step": item.get("step"), "sql": item.get("arguments", {}).get("sql"), "ok": item.get("result", {}).get("ok")})
        if item["type"] == "agent.file_write":
            write_provenance.append({"path": item.get("path"), "actual_sql_feedback_preceding_write": prior_sql_feedback[-1] if prior_sql_feedback else None})
    score = score_local_fixture_answer(task_id, answer)
    return {
        "attempt_id": attempt_id,
        "model_requests": len(provider), "file_writes": len(writes), "file_reads": len(reads),
        "sql_queries_completed": database.successful_queries, "sql_queries_failed": database.failed_queries,
        "final_answer": answer, "task_score": score,
        "result_interpretation": classify_local_fixture_result(answer, metrics.get("runner_stop_reason"), score),
        "finish_reasons": [item.get("stop_reason") for item in provider],
        "runner_stop_reason": metrics.get("runner_stop_reason"), "metrics": metrics,
        "usage_by_request": [item.get("usage") for item in provider],
        "cost_by_request": [item.get("billed_cost_estimate") for item in provider],
        "artifact_files_written": [item.get("path") for item in writes],
        "artifact_files_read": [item.get("path") for item in reads],
        "artifact_write_provenance": write_provenance,
        "output_snapshot_hash": snapshot.content_hash, "output_snapshot_files": list(snapshot.files),
    }


def _ledger_summary(ledger: CostLedger) -> dict[str, Any]:
    unknown = [entry for entry in ledger.entries if entry["status"] == "billing_unknown"]
    return {
        "reserved_usd": str(ledger.reserved), "settled_conservative_cache_miss_estimate_usd": str(ledger.settled),
        "unknown_billing_request_count": len(unknown),
        "non_charge_conservative_reservation_difference_usd": str(ledger.reserved - ledger.settled),
        "actual_provider_invoice_available": False,
    }


def _mark_unstarted_episodes(report: dict[str, Any], episodes: list[dict[str, Any]], reason: str) -> None:
    started = {item["episode"] for item in report["episodes"]}
    for item in episodes:
        if item["order"] not in started:
            report["episodes"].append({
                "episode": item["order"], "condition": item["condition"], "initial_memory": item["memory"],
                "status": "NOT_RUN", "reason": reason,
            })


def execute(config_path: Path, output_root: Path) -> Path:
    raw = _load(config_path)
    authorization, config, prices = _authorization(raw), _config(raw), _prices(raw)
    authorization.validate(); config.validate()
    if raw.get("status") != "AUTHORIZED_FOR_EXACT_THREE_EPISODES":
        raise ValueError("configuration is not the signed three-episode authorization")
    if raw["study_kind"] != "engineering_smoke" or raw["included_in_primary_analysis"] is not False:
        raise ValueError("live smoke scope is invalid")
    episodes = raw["episodes"]
    if len(episodes) != 3 or [item["order"] for item in episodes] != [1, 2, 3]:
        raise ValueError("the signed configuration must contain exactly the fixed three episodes")
    if config.worst_case_request_cost(prices) * authorization.max_requests > authorization.hard_cap:  # type: ignore[operator]
        raise BudgetError("worst-case signed request reservation exceeds the hard cap")

    config_hash = _sha256_path(config_path)
    receiver_config = {
        "provider": config.provider, "model": config.exact_model_id, "base_url": config.base_url,
        "thinking_enabled": config.thinking_enabled, "reasoning_effort": config.reasoning_effort,
        "max_tokens": config.max_output_tokens_per_request, "timeout_seconds": config.timeout_seconds,
        "max_requests": config.max_requests_per_episode, "max_tools": config.max_tool_calls_per_episode,
        "retries": config.retries,
    }
    runner = ExperimentRunner(output_root, receiver_config=receiver_config)
    ledger = CostLedger(authorization)
    report: dict[str, Any] = {
        "status": "RUNNING", "generated_at": datetime.now(timezone.utc).isoformat(), "study_kind": "engineering_smoke",
        "included_in_primary_analysis": False, "authorization_config": str(config_path), "authorization_config_hash": config_hash,
        "worst_case_per_request_usd": str(config.worst_case_request_cost(prices)),
        "worst_case_all_18_requests_usd": str(config.worst_case_request_cost(prices) * authorization.max_requests),
        "hard_cap_usd": str(authorization.hard_cap), "episodes": [], "provider_requests_sent": 0,
        "no_code_execution_calls": True, "fourth_episode_started": False,
    }
    runner.records.write_json("live_smoke_run_manifest.json", {"config": raw, "config_hash": config_hash, "receiver_config_hash": stable_hash(receiver_config)})

    # This merely constructs the existing SDK client.  The first network call
    # occurs inside episode 1 after the first reservation.
    try:
        client = build_authorized_client(authorization, config)
    except Exception as exc:
        _mark_unstarted_episodes(report, episodes, f"precheck_{type(exc).__name__}")
        report.update({"status": "PRECHECK_BLOCKED", "stop_reason": type(exc).__name__, "ledger": ledger.entries, "ledger_summary": _ledger_summary(ledger), "billing_unknown": False})
        return _write_report(output_root, report)
    adapter = client.adapter
    if not isinstance(adapter, ProviderAdapter):
        raise RuntimeError("configured client did not provide a provider adapter")

    source = runner.prepare_task("U1", "live-smoke-20260921", episodes[0]["id"], task_text=PRACTICE_TEXT)
    source_db = create_local_fixture(runner.root / "tool_service" / "episode-1", max_queries=config.max_tool_calls_per_episode)
    try:
        source_answer, source_snapshot, source_metrics = run_tool_only_episode(
            prepared=source, manager=runner.manager, records=runner.records, database=source_db, adapter=adapter,
            ledger=ledger, config=config, prices=prices, transport_kind="live_provider",
        )
        source_hash_before_probes = hash_tree(source_snapshot.path)[0]
        evidence = _episode_evidence(runner.records.path, source.session.attempt_id, source_db, source_answer, episodes[0]["id"], source_metrics, source_snapshot)
        evidence.update({"episode": 1, "condition": "U1", "initial_memory": "EMPTY", "source_snapshot_hash_before_probes": source_hash_before_probes})
        evidence.update({"actual_model_id": config.exact_model_id, "provider_config_hash": config_hash})
        report["episodes"].append(evidence)
    except Exception as exc:  # provider error or uncertain billing stops later episodes
        report["episodes"].append({"episode": 1, "condition": "U1", "initial_memory": "EMPTY", "status": "FAILED_OR_STOPPED", "error_type": type(exc).__name__})
        _mark_unstarted_episodes(report, episodes, f"episode_1_{type(exc).__name__}")
        report.update({"status": "STOPPED", "stop_reason": type(exc).__name__, "provider_requests_sent": len(ledger.entries), "ledger": ledger.entries, "ledger_summary": _ledger_summary(ledger), "billing_unknown": ledger.billing_unknown})
        return _write_report(output_root, report)

    for order, parent in ((2, source_snapshot), (3, runner.manager.empty_snapshot())):
        task = episodes[order - 1]
        prepared = runner.prepare_receiver_task(task["id"], PROBE_TEXT, parent)
        database = create_local_fixture(runner.root / "tool_service" / f"episode-{order}", max_queries=config.max_tool_calls_per_episode)
        try:
            answer, output, metrics = run_tool_only_episode(
                prepared=prepared, manager=runner.manager, records=runner.records, database=database, adapter=adapter,
                ledger=ledger, config=config, prices=prices, transport_kind="live_provider",
            )
            evidence = _episode_evidence(runner.records.path, prepared.session.attempt_id, database, answer, task["id"], metrics, output)
            evidence.update({"episode": order, "condition": "E*", "initial_memory": task["memory"], "parent_snapshot_hash": parent.content_hash, "parent_snapshot_unchanged": hash_tree(parent.path)[0] == parent.content_hash})
            evidence.update({"actual_model_id": config.exact_model_id, "provider_config_hash": config_hash})
            report["episodes"].append(evidence)
        except Exception as exc:
            report["episodes"].append({"episode": order, "condition": "E*", "initial_memory": task["memory"], "status": "FAILED_OR_STOPPED", "error_type": type(exc).__name__})
            report.update({"status": "STOPPED", "stop_reason": type(exc).__name__})
            break
    if report.get("status") == "STOPPED":
        _mark_unstarted_episodes(report, episodes, report.get("stop_reason", "stopped"))
    report.update({"provider_requests_sent": len(ledger.entries), "ledger": ledger.entries, "ledger_summary": _ledger_summary(ledger), "billing_unknown": ledger.billing_unknown, "status": "COMPLETED" if len(report["episodes"]) == 3 else "STOPPED"})
    if report["episodes"]:
        report["episodes"][0]["source_snapshot_unchanged_after_all_probes"] = hash_tree(source_snapshot.path)[0] == source_snapshot.content_hash
    return _write_report(output_root, report)


def _write_report(output_root: Path, report: dict[str, Any]) -> Path:
    path = Path(output_root).resolve().parents[1] / "LIVE_SMOKE_REPORT.md"
    lines = ["# LIVE SMOKE REPORT", "", "```json", json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run only the signed E0 DeepSeek local tool-only smoke")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value"))
    args = parser.parse_args()
    print(execute(args.config, args.output_root))


if __name__ == "__main__":
    main()
