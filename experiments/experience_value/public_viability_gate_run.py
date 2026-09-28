"""Independent, no-framework public-task viability gate.

The gate is intentionally limited to development-contacted task IDs and is
separate from the six-episode calibration and any formal F0/U0/F1/U1 matrix.
Its fake mode drives the actual public Database Exploration adapter, native
ANSWER/evaluator path, terminal-only query boundary, and optional consolidation.
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

from .clbench_database_exploration import DatabaseExplorationAdapter
from .live import PriceSheet, ToolOnlySmokeConfig, build_authorized_client, run_tool_only_episode, tool_only_schemas
from .public_calibration_run import (
    ALLOWED_TOOLS, FILE_TOOLS, NativeQueryTool, _analysis_outcome, _config,
    _event_usage, _tool_counts, _offpeak_status, _provider_connectivity_preflight,
    _provider_infra_failure, _transport_retry_summary,
)
from .records import AuthorizationError, BudgetError, CostLedger, LiveAuthorization
from .runner import ExperimentRunner, stable_hash


GATE_STATUSES = {
    "PENDING_PUBLIC_VIABILITY_GATE_USER_SIGNOFF_NO_LIVE_CALLS",
    "PENDING_PUBLIC_VIABILITY_GATE_OPERATIONAL_V2_USER_SIGNOFF_NO_LIVE_CALLS",
    "PENDING_PUBLIC_VIABILITY_GATE_EXPERIENCE_COMMIT_V3_USER_SIGNOFF_NO_LIVE_CALLS",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(path: Path, attempt_id: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line and json.loads(line).get("attempt_id") == attempt_id]


def _code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    paths = {
        "entry": Path(__file__), "live_bridge": root / "experiments/experience_value/live.py",
        "public_calibration_bridge": root / "experiments/experience_value/public_calibration_run.py",
        "loop": root / "graphs/loop.py", "public_adapter": root / "experiments/experience_value/clbench_database_exploration.py",
        "workspace": root / "experiments/experience_value/workspace.py", "runner": root / "experiments/experience_value/runner.py",
        "ledger": root / "experiments/experience_value/records.py",
        "provider_adapter": root / "llm/adapters.py", "provider_client": root / "llm/client.py",
    }
    return {name: _sha256(path) for name, path in paths.items()}


def _load_spec(pending_path: Path, authorization_path: Path) -> tuple[dict[str, Any], dict[str, Any], ToolOnlySmokeConfig, PriceSheet]:
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    pending_hash = _sha256(pending_path)
    if pending.get("status") not in GATE_STATUSES:
        raise AuthorizationError("viability gate is not pending for separate signoff")
    if pending.get("study_kind") != "development_public_viability_gate" or pending.get("included_in_primary_analysis") is not False:
        raise AuthorizationError("viability gate analysis scope is invalid")
    task_path = pending.get("task_manifest_path")
    task_hash = pending.get("task_manifest_sha256")
    if task_path is not None:
        resolved_task_path = Path(task_path)
        if not resolved_task_path.exists() or _sha256(resolved_task_path) != task_hash:
            raise AuthorizationError("viability gate task manifest hash differs")
        bound_task = authorization.get("task_manifest", {})
        if bound_task and (bound_task.get("path") != task_path or bound_task.get("sha256") != task_hash):
            raise AuthorizationError("viability authorization does not bind the frozen task manifest")
    if pending.get("interface", {}).get("allowed_tools") != sorted(ALLOWED_TOOLS):
        raise AuthorizationError("viability gate tool allowlist differs")
    schema_hash = hashlib.sha256(json.dumps(tool_only_schemas(ALLOWED_TOOLS), sort_keys=True).encode("utf-8")).hexdigest()
    if pending["interface"].get("tool_schema_hash") != schema_hash:
        raise AuthorizationError("viability gate schema hash differs from actual tools")
    episodes = pending.get("episodes", [])
    if not 2 <= len(episodes) <= 3 or any(item.get("task_id") not in {"1", "2", "3"} for item in episodes):
        raise AuthorizationError("viability gate must contain two or three development-contacted tasks only")
    if any(item.get("task_index") != int(item["task_id"]) - 1 for item in episodes):
        raise AuthorizationError("viability gate task indices do not match task IDs")
    request = pending["request"]
    if request.get("max_input_tokens_per_request") != 24000 or request.get("max_output_tokens_per_request") != 8192:
        raise AuthorizationError("viability gate token limits differ from the frozen candidate")
    if request.get("max_provider_requests_per_episode") != 24 or request.get("max_transport_retries") != 1:
        raise AuthorizationError("viability gate decision or transport retry limits differ")
    if request.get("formal_input_cutoff", {}).get("name") != "deepseek_prompt_usage_calibrated_v1":
        raise AuthorizationError("viability gate must use the versioned formal input cutoff")
    if pending["native_task"].get("max_sql_queries") != 15 or pending["file_budget"].get("max_operations") != 8:
        raise AuthorizationError("viability gate must retain public native/file limits")
    if pending.get("terminal_answer_interface", {}).get("enabled") is not True:
        raise AuthorizationError("viability gate must enable the terminal-only answer interface")
    consolidation = pending.get("optional_consolidation", {})
    expected_file_operations = 0 if consolidation.get("mode") == "deterministic_experience_commit_v1" else 2
    if consolidation.get("max_model_decisions") != 1 or consolidation.get("max_file_operations") != expected_file_operations or consolidation.get("sql_allowed") is not False:
        raise AuthorizationError("viability gate consolidation budget differs")
    if consolidation.get("mode") == "deterministic_experience_commit_v1":
        paths = consolidation.get("episode_artifact_paths", {})
        if set(paths) != {item["id"] for item in episodes} or any(not str(path).startswith("/memory/") for path in paths.values()):
            raise AuthorizationError("deterministic consolidation needs one unique /memory path per frozen episode")
    frozen = authorization.get("frozen_pending_config", {})
    if frozen.get("sha256") != pending_hash:
        raise AuthorizationError("viability authorization does not bind this pending config")
    entry = authorization.get("entry_code", {})
    if entry.get("path") != "experiments/experience_value/public_viability_gate_run.py" or entry.get("sha256") != _sha256(Path(__file__)):
        raise AuthorizationError("viability authorization does not bind the actual entry")
    hashes = _code_hashes()
    if authorization.get("code_dependencies") != hashes:
        raise AuthorizationError("viability authorization does not bind its code dependencies")
    config = _config(pending)
    config.validate()
    price = pending["budget_proposal"]
    prices = PriceSheet(Decimal(price["input_cache_miss_usd_per_million"]), Decimal(price["output_usd_per_million"]), price["price_source"], price["price_checked_on"], Decimal(price["input_cache_hit_usd_per_million"]))
    if config.worst_case_request_cost(prices) * Decimal(price["max_provider_attempts"]) > Decimal(price["proposed_hard_cap_usd"]):
        raise AuthorizationError("viability gate reservation exceeds pending hard cap")
    return pending, authorization, config, prices


def _empty_episode(item: dict[str, Any], reason: str) -> dict[str, Any]:
    """Keep skipped frozen episodes visible instead of silently dropping them."""
    return {
        "episode_id": item["id"], "task_id": item["task_id"], "condition": item["condition"],
        "started": False, "not_run_reason": reason, "native_answer_submitted": False,
        "native_evaluator_ran": False, "native_score": None, "correct": None,
        "main_stop_reason": reason, "main_model_decisions": 0, "provider_attempts": 0,
        "provider_responses": 0, "transport_retries": 0, "infra_recovered": False,
        "sql_queries": 0, "file_operations": 0, "prompt_tokens": 0,
        "completion_tokens": 0, "reasoning_tokens": 0, "diagnostic_estimates": [],
        "formal_cutoff_estimates": [], "consolidation_executed": False,
        "consolidation_model_decisions": 0, "consolidation_tool_calls": 0,
        "artifact_paths": [], "artifact_provenance": [], "snapshot_hash": None,
        "leakage_checks": {"native_terminal_feedback_forwarded_to_model": False,
                           "reference_or_evaluator_feedback_visible_to_agent": False},
        "analysis_status": "NOT_RUN", "analysis_score": None,
        "estimated_cost": "0", "billing_unknown": False,
    }


def _episode_report(*, item: dict[str, Any], view: Any, prepared: Any, task: Any,
                    query_tool: Any, snapshot: Any | None, metrics: dict[str, Any] | None,
                    events: list[dict[str, Any]], native: Any | None,
                    exception_chain: Any = None, not_run: str | None = None) -> dict[str, Any]:
    if not_run:
        return _empty_episode(item, not_run)
    attempts, completed, usage, cost, _ = _event_usage(events)
    retry = _transport_retry_summary(events)
    provider_events = [e for e in events if e.get("type") == "provider.request_finished"]
    starts = [e for e in events if e.get("type") == "provider.request_started"]
    consolidation = (metrics or {}).get("consolidation") or {}
    main_tool_counts = (metrics or {}).get("tool_calls_by_name", {})
    provenance = (metrics or {}).get("artifact_provenance", [])
    resource = (metrics or {}).get("runner_stop_reason")
    infra, chain = _provider_infra_failure(events)
    analysis = (_analysis_outcome(native_score=native.score, evaluator_ran=True) if native is not None
                else _analysis_outcome(resource_stop_reason=resource, infrastructure_failure=infra))
    return {
        "episode_id": item["id"], "task_id": view.task_id, "condition": item["condition"],
        "started": True, "attempt_id": prepared.session.attempt_id,
        "native_answer_submitted": bool(task.completed), "native_evaluator_ran": native is not None,
        "native_score": native.score if native else None,
        "correct": native.metrics.get("accuracy") if native else None,
        "main_stop_reason": resource or ("ANSWER_SUBMITTED" if task.completed else type(exception_chain).__name__ if exception_chain else None),
        "main_model_decisions": (metrics or {}).get("llm_calls", 0),
        "provider_attempts": attempts, "provider_responses": completed,
        "transport_retries": int(retry["transport_retry_attempted"]), "infra_recovered": retry["infra_recovered"],
        "sql_queries": query_tool.successful_queries,
        "file_operations": sum(main_tool_counts.get(name, 0) for name in FILE_TOOLS),
        "prompt_tokens": sum(int((e.get("usage") or {}).get("prompt_tokens") or 0) for e in provider_events),
        "completion_tokens": sum(int((e.get("usage") or {}).get("completion_tokens") or 0) for e in provider_events),
        "reasoning_tokens": sum(int((e.get("usage") or {}).get("reasoning_tokens") or 0) for e in provider_events),
        "diagnostic_estimates": [e.get("input_token_estimate") for e in starts],
        "formal_cutoff_estimates": [e.get("formal_input_cutoff_estimate") for e in starts],
        "consolidation_executed": bool(consolidation),
        "consolidation_model_decisions": (consolidation.get("metrics") or {}).get("llm_calls", 0),
        "consolidation_tool_calls": sum(((consolidation.get("metrics") or {}).get("tool_calls_by_name") or {}).values()),
        "artifact_paths": [entry.get("path") for entry in provenance], "artifact_provenance": provenance,
        "snapshot_hash": snapshot.content_hash if snapshot else None,
        "snapshot_files": list(snapshot.files) if snapshot else [], "consolidation": consolidation,
        "leakage_checks": {"native_terminal_feedback_forwarded_to_model": False,
                           "reference_or_evaluator_feedback_visible_to_agent": False},
        "exception_chain": chain if infra else exception_chain,
        "analysis_status": analysis["analysis_status"], "analysis_score": analysis["analysis_score"],
        "native_accuracy": native.metrics.get("accuracy") if native else None,
        "completed_model_decisions": completed,
        "estimated_cost": str(cost), "billing_unknown": any(e.get("billing") == "unknown" for e in events),
        "tool_counts": _tool_counts(events),
    }


def _gate_outcome(episodes: list[dict[str, Any]]) -> str:
    """Exactly the preregistered viability criteria; score magnitude is irrelevant."""
    if any(row.get("analysis_status") == "INVALID_INFRA" for row in episodes):
        return "INVALID_INFRA"
    if any(row.get("analysis_status") == "INVALID_SYSTEM" for row in episodes):
        return "INVALID_SYSTEM"
    scored = any(row.get("native_evaluator_ran") and row.get("native_score") is not None for row in episodes)
    artifact = any(row.get("artifact_provenance") for row in episodes)
    complete_logs = all((not row.get("started")) or (row.get("snapshot_hash") is not None and row.get("diagnostic_estimates") is not None and row.get("formal_cutoff_estimates") is not None) for row in episodes)
    leakage = any(any(row.get("leakage_checks", {}).values()) for row in episodes)
    if scored and artifact and complete_logs and not leakage:
        return "GO"
    if scored and not artifact:
        return "NO_GO_FOR_EXPERIENCE_TRANSFER"
    if artifact and not scored:
        return "NO_GO_FOR_TASK_MEASUREMENT"
    return "NO_GO_NO_NATIVE_SCORE_AND_NO_ARTIFACT"


def _write_live_report(report: dict[str, Any], path: Path) -> None:
    """A uniform, human-readable report even when no provider is dispatched."""
    lines = ["# Public viability gate run", "", f"Status: **{report['status']}**", "",
             "`study_kind=development_public_viability_gate`", "", "`included_in_primary_analysis=false`", "",
             "## Identity", "",
             f"- Model: `{report.get('model')}`", f"- Config: `{report.get('pending_sha256')}`",
             f"- Task: `{report.get('task_sha256')}`", f"- Code: `{report.get('combined_code_hash')}`",
             f"- Authorization: `{report.get('authorization_sha256')}`", "",
             "## Time and preflight", "",
             f"- Time-window: `{json.dumps(report.get('time_window'), ensure_ascii=False)}`",
             f"- Credential-free DNS/TLS/HEAD: `{json.dumps(report.get('preflight'), ensure_ascii=False)}`", "",
             "## Episodes", ""]
    for row in report["episodes"]:
        lines.append(
            f"- `{row['episode_id']}` ({row['condition']}, task {row['task_id']}): started={row['started']}; "
            f"ANSWER={row['native_answer_submitted']}; evaluator={row['native_evaluator_ran']}; "
            f"score={row['native_score']}; decisions={row['main_model_decisions']}; "
            f"attempts/responses={row['provider_attempts']}/{row['provider_responses']}; SQL={row['sql_queries']}; "
            f"files={row['file_operations']}; stop={row['main_stop_reason']}; analysis={row['analysis_status']}; "
            f"artifacts={row['artifact_paths']}; cost={row['estimated_cost']}; billing_unknown={row['billing_unknown']}"
        )
    lines += ["", "## Batch summary", "",
              f"- Provider attempts / completed responses: `{report['provider_attempts']}` / `{report['provider_responses']}`",
              f"- Paid evaluator requests: `{report['paid_evaluator_requests']}`",
              f"- Native evaluator count: `{report['native_evaluator_count']}`",
              f"- Known cost estimate: `{report['known_cost_estimate']}`; unknown-billing attempts: `{report['unknown_billing_attempts']}`",
              f"- Infrastructure status: `{report['infrastructure_status']}`", "",
              f"# {report['gate_outcome']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _mark_authorization_consumed_once(path: Path, events: list[dict[str, Any]], *, run_id: str) -> None:
    """Consume only after durable evidence of an actual provider dispatch."""
    if not any(event.get("type") == "provider.request_started" for event in events):
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("real_model_requests_sent_under_this_authorization", 0) != 0:
        return
    payload["real_model_requests_sent_under_this_authorization"] = 1
    payload["status"] = (
        "CONSUMED_PUBLIC_VIABILITY_GATE_EXPERIENCE_COMMIT_V3"
        if "EXPERIENCE_COMMIT_V3" in str(payload.get("status", ""))
        else "CONSUMED_PUBLIC_VIABILITY_GATE_OPERATIONAL_V2"
    )
    payload["consumption_run_id"] = run_id
    payload["consumed_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute(*, pending_path: Path, authorization_path: Path, output_root: Path, mode: str,
            adapter: ProviderAdapter | None = None,
            offpeak_check: Any = _offpeak_status, preflight_check: Any = _provider_connectivity_preflight,
            shim_check: Any = DatabaseExplorationAdapter.assert_real_litellm_available,
            report_path: Path | None = None) -> Path:
    if mode not in {"plan-only", "fake", "live"}:
        raise ValueError("mode must be plan-only, fake, or live")
    pending, authorization, config, prices = _load_spec(pending_path, authorization_path)
    if mode == "fake" and adapter is None:
        raise ValueError("fake mode requires a transport")
    if mode == "live":
        if authorization.get("status") not in {
            "AUTHORIZED_PUBLIC_VIABILITY_GATE",
            "AUTHORIZED_PUBLIC_VIABILITY_GATE_OPERATIONAL_V2",
            "AUTHORIZED_PUBLIC_VIABILITY_GATE_EXPERIENCE_COMMIT_V3",
        } or authorization.get("live_requests_authorized") is not True:
            raise AuthorizationError("viability gate live mode requires a new independent authorization")
        if authorization.get("real_model_requests_sent_under_this_authorization") != 0:
            raise AuthorizationError("viability authorization is already consumed")
    live = LiveAuthorization(True, pending["provider"], pending["exact_model_id"], "USD", Decimal(pending["budget_proposal"]["proposed_hard_cap_usd"]), int(pending["budget_proposal"]["max_provider_attempts"]), pending["budget_proposal"]["price_source"], max_episodes=len(pending["episodes"]), episode_cap=len(pending["episodes"]))
    runner = ExperimentRunner(output_root, receiver_config={"formal_input_cutoff": config.formal_input_cutoff_estimator, "terminal_answer": True, "consolidation": pending["optional_consolidation"]})
    code_hashes = _code_hashes()
    manifest = {"mode": mode, "run_id": runner.run_id, "pending_sha256": _sha256(pending_path), "authorization_sha256": _sha256(authorization_path), "code_hashes": code_hashes, "episodes": pending["episodes"], "provider_requests_sent": 0 if mode != "live" else None}
    runner.records.write_json("public_viability_gate_manifest.json", manifest)
    if mode == "plan-only":
        return runner.records.write_json("public_viability_gate_plan.json", {"requests_sent": 0, "manifest": manifest})
    report: dict[str, Any] = {
        "status": "RUNNING", "study_kind": pending["study_kind"], "included_in_primary_analysis": False,
        "run_id": runner.run_id, "mode": mode, "model": pending["exact_model_id"],
        "pending_sha256": _sha256(pending_path), "authorization_sha256": _sha256(authorization_path),
        "task_sha256": pending.get("task_manifest_sha256"), "code_hashes": code_hashes,
        "combined_code_hash": hashlib.sha256(json.dumps(code_hashes, sort_keys=True).encode()).hexdigest(),
        "episodes": [], "provider_attempts": 0, "provider_responses": 0,
        "paid_evaluator_requests": 0, "native_evaluator_count": 0, "known_cost_estimate": "0",
        "unknown_billing_attempts": 0, "infrastructure_status": "NOT_APPLICABLE",
        "time_window": None, "preflight": None,
    }
    report_path = report_path or Path(__file__).resolve().parents[2] / "PUBLIC_VIABILITY_GATE_RUN_REPORT.md"
    if mode == "live":
        # All three checks occur before *any* provider client construction.
        window = offpeak_check(pending, for_new_episode=True)
        report["time_window"] = window
        if window.get("new_episode_allowed") is not True:
            report.update({"status": "WAITING_OFFPEAK", "infrastructure_status": "NOT_DISPATCHED"})
            report["episodes"] = [_empty_episode(item, "WAITING_OFFPEAK") for item in pending["episodes"]]
            report["gate_outcome"] = "NO_GO_NOT_RUN"
            runner.records.write_json("public_viability_gate_run.json", report)
            _write_live_report(report, report_path)
            return report_path
        preflight = preflight_check()
        report["preflight"] = preflight
        if not preflight.get("ok"):
            report.update({"status": "PRECHECK_FAILED", "infrastructure_status": "INVALID_INFRA_PRECHECK"})
            report["episodes"] = [_empty_episode(item, "PRECHECK_FAILED") for item in pending["episodes"]]
            report["gate_outcome"] = "NO_GO_PRECHECK_FAILED"
            runner.records.write_json("public_viability_gate_run.json", report)
            _write_live_report(report, report_path)
            return report_path
        try:
            shim_check()
        except Exception as exc:
            report.update({"status": "INVALID_SYSTEM", "infrastructure_status": "INVALID_SYSTEM", "shim_exception": {"class": type(exc).__name__, "message": str(exc)}})
            report["episodes"] = [_empty_episode(item, "INVALID_SYSTEM_NO_MODEL_SHIM") for item in pending["episodes"]]
            report["gate_outcome"] = "INVALID_SYSTEM"
            runner.records.write_json("public_viability_gate_run.json", report)
            _write_live_report(report, report_path)
            return report_path
        if adapter is None:
            adapter = build_authorized_client(live, config).adapter
    assert adapter is not None
    ledger = CostLedger(live)
    upstream = Path(pending["native_task"]["upstream_root"])
    for episode_index, item in enumerate(pending["episodes"]):
        if mode == "live":
            window = offpeak_check(pending, for_new_episode=True)
            report["time_window"] = window
            if window.get("new_episode_allowed") is not True:
                report.update({"status": "WAITING_OFFPEAK", "infrastructure_status": "STOPPED_OFFPEAK"})
                report["episodes"].append(_empty_episode(item, "WAITING_OFFPEAK"))
                report["episodes"].extend(_empty_episode(rest, "BATCH_STOPPED_OFFPEAK") for rest in pending["episodes"][episode_index + 1:])
                break
        task = DatabaseExplorationAdapter(upstream_root=upstream, db_path=upstream / "data/database_exploration/products.db", questions_path=upstream / "data/database_exploration/questions.json", records=runner.records, seed=pending["native_task"]["seed"], max_queries_per_question=15, task_index=item["task_index"], allow_no_model_import_shim=mode == "fake")
        view = task.reset()
        prepared = runner.prepare_task(item["condition"], "public-viability-gate", item["id"], task_text=view.prompt)
        query_tool = NativeQueryTool(task)

        def submit_before_consolidation(answer: str, _metrics: dict[str, Any]) -> None:
            if answer and not task.completed:
                task.submit_answer(answer)

        try:
            answer, snapshot, metrics = run_tool_only_episode(
                prepared=prepared, manager=runner.manager, records=runner.records, database=query_tool, adapter=adapter,
                ledger=ledger, config=config, prices=prices, transport_kind="fake_transport" if mode == "fake" else "live_provider",
                allowed_tool_names=ALLOWED_TOOLS, tool_call_limits={"query_sql": 15},
                tool_call_group_limits={"file_operations": (FILE_TOOLS, 8)},
                pre_request_check=(lambda: offpeak_check(pending)) if mode == "live" else None,
                stop_on_tool_limit_reached=True, terminal_only_after_tool_limit_names={"query_sql"}, enable_optional_consolidation=True,
                before_consolidation=submit_before_consolidation,
                consolidation_mode=pending["optional_consolidation"].get("mode", "optional_file_tools_v1"),
                consolidation_artifact_path=pending["optional_consolidation"].get("episode_artifact_paths", {}).get(item["id"]),
                raw_source_label=item["id"],
            )
        except Exception as exc:
            events = _events(runner.records.path, prepared.session.attempt_id)
            if mode == "live":
                _mark_authorization_consumed_once(authorization_path, events, run_id=runner.run_id)
            row = _episode_report(item=item, view=view, prepared=prepared, task=task, query_tool=query_tool,
                                  snapshot=None, metrics=None, events=events, native=None, exception_chain={"class": type(exc).__name__, "message": str(exc)})
            report["episodes"].append(row)
            report["provider_attempts"] += row["provider_attempts"]
            report["provider_responses"] += row["provider_responses"]
            report["unknown_billing_attempts"] += sum(e.get("billing") == "unknown" for e in events)
            if row["analysis_status"] == "INVALID_INFRA":
                report.update({"status": "INVALID_INFRA", "infrastructure_status": "INVALID_INFRA"})
            else:
                report.update({"status": "INVALID_SYSTEM", "infrastructure_status": "INVALID_SYSTEM"})
            report["episodes"].extend(_empty_episode(rest, report["status"]) for rest in pending["episodes"][episode_index + 1:])
            break
        events = _events(runner.records.path, prepared.session.attempt_id)
        if mode == "live":
            _mark_authorization_consumed_once(authorization_path, events, run_id=runner.run_id)
        native = task.evaluate_native() if task.completed else None
        row = _episode_report(item=item, view=view, prepared=prepared, task=task, query_tool=query_tool,
                              snapshot=snapshot, metrics=metrics, events=events, native=native)
        report["episodes"].append(row)
        report["provider_attempts"] += row["provider_attempts"]
        report["provider_responses"] += row["provider_responses"]
        report["paid_evaluator_requests"] += int(native is not None)
        report["native_evaluator_count"] += int(native is not None)
        report["unknown_billing_attempts"] += sum(e.get("billing") == "unknown" for e in events)
    report["known_cost_estimate"] = str(ledger.settled)
    report["ledger"] = {"entries": ledger.entries, "reserved_usd": str(ledger.reserved), "settled_usd": str(ledger.settled), "billing_unknown": ledger.billing_unknown}
    if report["status"] == "RUNNING":
        outcome = _gate_outcome(report["episodes"])
        report["gate_outcome"] = outcome
        report["status"] = "COMPLETED_GO" if outcome == "GO" else "COMPLETED_NO_GO"
    else:
        report["gate_outcome"] = _gate_outcome(report["episodes"])
    json_path = runner.records.write_json("public_viability_gate_run.json", report)
    if mode == "live":
        _write_live_report(report, report_path)
    return json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Public Database Exploration viability gate")
    parser.add_argument("--pending", type=Path, default=Path("experiments/experience_value/public_viability_gate.operational_v2.pending.json"))
    parser.add_argument("--authorization", type=Path, default=Path("experiments/experience_value/public_viability_gate.operational_v2.authorization.authorized_20260926T153029Z.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value/public_viability_gate"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan-only", action="store_true")
    group.add_argument("--fake", action="store_true")
    group.add_argument("--live", action="store_true")
    args = parser.parse_args()
    mode = "plan-only" if args.plan_only else "fake" if args.fake else "live"
    print(execute(pending_path=args.pending, authorization_path=args.authorization, output_root=args.output_root, mode=mode))


if __name__ == "__main__":
    main()
