"""Frozen three-episode file positive-control runner.

This is deliberately separate from ``live_smoke_run``: it reads the PC pending
configuration and its recorded authorization, maps their fields without changing
their meaning, and runs only PC-SOURCE, PC-MEMORY, and PC-EMPTY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from llm.adapters import ProviderAdapter

from .fixture import classify_local_fixture_result, create_atomic_file_io_fixture, create_local_fixture, score_local_fixture_answer
from .live import PriceSheet, ToolOnlySmokeConfig, build_authorized_client, run_tool_only_episode, tool_only_schemas
from .records import AuthorizationError, BudgetError, CostLedger, LiveAuthorization
from .runner import ExperimentRunner, PreparedTask, stable_hash
from .workspace import Snapshot, hash_tree


SOURCE_PROMPT_PREFIX = "This is the labeled PC-SOURCE engineering positive control."
PROBE_PROMPT_PREFIX = "This is a fresh E* probe session."
EXPECTED_EPISODES = (
    (1, "pc_source_optional_filename", "PC-SOURCE", "EMPTY"),
    (2, "pc_probe_memory", "E*", "PC_SOURCE_FROZEN_CLONE"),
    (3, "pc_probe_empty", "E*", "EMPTY"),
)
ALLOWED_TOOLS = ["list_dir", "read_file", "write_file", "query_sql"]


def _tool_schema_hash(allowed_names: set[str] | None = None) -> str:
    return hashlib.sha256(json.dumps(tool_only_schemas(allowed_names), sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PositiveControlSpec:
    pending: dict[str, Any]
    tasks_markdown: str
    authorization: dict[str, Any]
    pending_hash: str
    tasks_hash: str
    authorization_hash: str
    config: ToolOnlySmokeConfig
    prices: PriceSheet
    live_authorization: LiveAuthorization


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _config(raw: dict[str, Any]) -> ToolOnlySmokeConfig:
    request = raw["request"]
    if request.get("sdk_implicit_retries") != 0:
        raise AuthorizationError("positive control requires SDK implicit retries to be zero")
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
    budget = raw["budget_proposal"]
    return PriceSheet(
        Decimal(budget["input_cache_miss_usd_per_million"]), Decimal(budget["output_usd_per_million"]),
        budget["price_source"], budget["price_checked_on"],
    )


def load_spec(pending_path: Path, tasks_path: Path, authorization_path: Path) -> PositiveControlSpec:
    """Read all frozen PC inputs and reject mismatches before client construction."""
    pending, authorization = _load_json(pending_path), _load_json(authorization_path)
    tasks = tasks_path.read_text(encoding="utf-8")
    pending_hash, tasks_hash, authorization_hash = _sha256(pending_path), _sha256(tasks_path), _sha256(authorization_path)
    recorded = authorization.get("frozen_pending_config", {})
    if recorded.get("sha256") != pending_hash:
        raise AuthorizationError("pending configuration SHA-256 differs from the recorded authorization")
    auth = authorization.get("authorization", {})
    if authorization.get("status") != "AUTHORIZED_BUT_NOT_EXECUTED_CONFIGURATION_MISMATCH":
        raise AuthorizationError("authorization record is not the unconsumed PC authorization")
    if auth.get("live_requests_authorized_only_if_frozen_configuration_and_positive_control_entry_match") is not True:
        raise AuthorizationError("authorization does not permit a matching positive-control entry")
    if auth.get("real_model_requests_sent_under_this_authorization") != 0:
        raise AuthorizationError("recorded PC authorization is already consumed")
    if auth.get("formal_48_plus_30_batch_authorized") is not False:
        raise AuthorizationError("authorization scope is wider than the fixed positive control")
    for key in ("study_kind", "included_in_primary_analysis", "provider", "exact_model_id", "base_url", "api_key_env_name_only", "interface", "request", "episodes", "source_failure_rule", "probe_isolation", "budget_proposal"):
        if authorization.get(key) != pending.get(key):
            raise AuthorizationError(f"authorization and pending configuration differ at {key}")
    if pending.get("status") != "PENDING_USER_SIGNOFF_NO_LIVE_CALLS":
        raise AuthorizationError("pending configuration was changed")
    if pending.get("study_kind") != "engineering_positive_control" or pending.get("included_in_primary_analysis") is not False:
        raise AuthorizationError("positive-control analysis scope is invalid")
    if pending["interface"].get("allowed_tools") != ALLOWED_TOOLS:
        raise AuthorizationError("PC tool allowlist differs from the frozen allowlist")
    if pending["interface"].get("tool_schema_hash") != _tool_schema_hash():
        raise AuthorizationError("PC tool schema hash differs from the actual restricted schema")
    if any(name not in pending["interface"].get("forbidden_capabilities", []) for name in ("python", "bash", "shell", "eval", "import", "arbitrary_code", "web")):
        raise AuthorizationError("PC forbidden-capability list is incomplete")
    actual_episode_shape = [(item.get("order"), item.get("id"), item.get("condition"), item.get("initial_memory")) for item in pending.get("episodes", [])]
    if tuple(actual_episode_shape) != EXPECTED_EPISODES:
        raise AuthorizationError("PC episode selection/order differs from the frozen three episodes")
    if "PC-SOURCE" not in tasks or "PC-MEMORY" not in tasks or "PC-EMPTY" not in tasks or "list_dir" not in tasks:
        raise AuthorizationError("frozen task manifest is incomplete")
    config, prices = _config(pending), _prices(pending)
    config.validate()
    budget = pending["budget_proposal"]
    worst = config.worst_case_request_cost(prices)
    if str(worst) != budget["worst_case_per_request_usd"]:
        raise AuthorizationError("frozen per-request reservation does not match mapped request limits")
    if config.max_requests_per_episode * len(EXPECTED_EPISODES) != budget["max_provider_requests"]:
        raise AuthorizationError("frozen batch request count differs from three episode limits")
    hard_cap = Decimal(budget["proposed_hard_cap_usd"])
    if worst * Decimal(budget["max_provider_requests"]) != Decimal(budget["worst_case_total_usd"]) or worst * Decimal(budget["max_provider_requests"]) > hard_cap:
        raise BudgetError("fixed PC reservation does not fit the hard cap")
    live_auth = LiveAuthorization(
        authorized=True, provider=pending["provider"], exact_model_id=pending["exact_model_id"],
        currency=budget["currency"], hard_cap=hard_cap, max_requests=budget["max_provider_requests"],
        price_basis=budget["reservation_basis"], max_episodes=len(EXPECTED_EPISODES),
    )
    live_auth.validate()
    return PositiveControlSpec(pending, tasks, authorization, pending_hash, tasks_hash, authorization_hash, config, prices, live_auth)


def _code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    paths = {
        "entry": Path(__file__), "live_bridge": root / "experiments" / "experience_value" / "live.py",
        "runner": root / "experiments" / "experience_value" / "runner.py",
        "workspace": root / "experiments" / "experience_value" / "workspace.py",
        "fixture": root / "experiments" / "experience_value" / "fixture.py",
        "records": root / "experiments" / "experience_value" / "records.py",
        "loop": root / "graphs" / "loop.py", "adapter": root / "llm" / "adapters.py",
    }
    return {name: _sha256(path) for name, path in paths.items()}


def _receiver_config(spec: PositiveControlSpec) -> dict[str, Any]:
    config = spec.config
    return {
        "provider": config.provider, "model": config.exact_model_id, "base_url": config.base_url,
        "thinking_enabled": config.thinking_enabled, "reasoning_effort": config.reasoning_effort,
        "temperature": config.temperature, "max_input_tokens": config.max_input_tokens_per_request,
        "max_output_tokens": config.max_output_tokens_per_request, "timeout_seconds": config.timeout_seconds,
        "application_retries": config.retries, "sdk_implicit_retries": 0,
        "max_requests_per_episode": config.max_requests_per_episode, "max_tools_per_episode": config.max_tool_calls_per_episode,
        "allowed_tools": ALLOWED_TOOLS,
    }


def _prepare(runner: ExperimentRunner, episode: dict[str, Any], parent: Snapshot | None = None) -> PreparedTask:
    condition = episode["condition"]
    session = runner.manager.start_task(condition=condition, replicate="pc", task_id=episode["id"], parent=parent)
    prefix = SOURCE_PROMPT_PREFIX if condition == "PC-SOURCE" else PROBE_PROMPT_PREFIX
    # The two probe strings intentionally contain neither task ID nor source path/content.
    prompt = f"{prefix}\n\nTask: {episode['instruction']}"
    prepared = PreparedTask(session, prompt, _tool_schema_hash(), stable_hash(_receiver_config_from_runner(runner)))
    runner.records.emit(
        "task.prepared", attempt_id=session.attempt_id, condition=condition, task_id=episode["id"],
        conversation_id=session.conversation_id, parent_snapshot_id=session.parent_snapshot_id,
        prompt_hash=stable_hash(prompt), tool_schema_hash=prepared.tool_schema_hash,
        request_config_hash=prepared.request_config_hash,
    )
    return prepared


def _receiver_config_from_runner(runner: ExperimentRunner) -> dict[str, Any]:
    return dict(runner.receiver_config)


def _events(path: Path, attempt_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line and json.loads(line).get("attempt_id") == attempt_id]


def evaluate_terminal_result_v2(
    *, answer: str, raw_answer_correct: bool | None, metrics: dict[str, Any], events: list[dict[str, Any]],
    max_requests: int, max_tools: int,
) -> dict[str, Any]:
    """Separate meaning, protocol, resource state, and actual authorization bounds.

    This deliberately does not rewrite the historical strict result layer, whose
    ``tool_budget_exhausted`` interpretation remains in existing reports.
    """
    requests = len([event for event in events if event["type"] == "provider.request_finished"])
    dispatched = [event for event in events if event["type"] == "tool.completed"]
    feedback_ids = {event.get("tool_call_id") for event in events if event["type"] == "tool.feedback_appended"}
    missing_feedback = [event.get("tool_call_id") for event in dispatched if event.get("tool_call_id") not in feedback_ids]
    rejected = [event.get("tool_call_id") for event in events if event["type"] == "tool.rejected"]
    looks_unexecuted = "tool_calls" in answer.lower() and "invoke" in answer.lower()
    tools_reached = metrics.get("tool_calls", 0) >= max_tools
    request_exceeded = requests > max_requests
    tool_exceeded = len(dispatched) > max_tools
    protocol_valid = bool(answer.strip()) and not looks_unexecuted and not missing_feedback and not rejected
    authorization_exceeded = request_exceeded or tool_exceeded
    return {
        "raw_answer_correct": raw_answer_correct,
        "answer_format_and_interaction_protocol_valid": protocol_valid,
        "unexecuted_tool_text_detected": looks_unexecuted,
        "unpaired_tool_feedback_ids": missing_feedback,
        "rejected_over_limit_tool_call_ids": rejected,
        "tool_limit_reached": tools_reached,
        "actual_requests": requests,
        "actual_dispatched_tools": len(dispatched),
        "authorization_range_exceeded": authorization_exceeded,
        "normal_termination": metrics.get("runner_stop_reason") == "model_finished",
        "resource_limited_termination": metrics.get("runner_stop_reason") == "tool_budget_exhausted",
        "joint_pass_v2": raw_answer_correct is True and protocol_valid and not authorization_exceeded,
    }


def _tool_counts(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts = {name: {"proposed": 0, "dispatched": 0, "succeeded": 0, "failed": 0} for name in ALLOWED_TOOLS}
    for event in events:
        name = event.get("tool")
        if name not in counts:
            continue
        if event["type"] == "tool.proposed":
            counts[name]["proposed"] += 1
        elif event["type"] == "tool.completed":
            counts[name]["dispatched"] += 1
            counts[name]["succeeded" if event.get("result", {}).get("ok") else "failed"] += 1
    return counts


def _artifact_details(snapshot: Snapshot) -> list[dict[str, Any]]:
    return [{"path": relative, "bytes": (snapshot.path / relative).stat().st_size, "sha256": _sha256(snapshot.path / relative)} for relative in snapshot.files]


def _score(episode: dict[str, Any], answer: str, stop_reason: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if episode["condition"] == "PC-SOURCE":
        score = {"scored": False, "correct": None, "reference_kind": "artifact_positive_control_no_answer_key"}
    else:
        score = score_local_fixture_answer("local_fixture_estimate_coastal_mean", answer)
    return score, classify_local_fixture_result(answer, stop_reason, score)


def _episode_evidence(
    *, runner: ExperimentRunner, episode: dict[str, Any], prepared: PreparedTask, database: Any,
    answer: str, snapshot: Snapshot, metrics: dict[str, Any], source_snapshot: Snapshot | None,
) -> dict[str, Any]:
    events = _events(runner.records.path, prepared.session.attempt_id)
    providers = [event for event in events if event["type"] == "provider.request_finished"]
    reads = [event for event in events if event["type"] == "agent.file_read"]
    listings = [event for event in events if event["type"] == "agent.dir_list"]
    score, validity = _score(episode, answer, metrics.get("runner_stop_reason"))
    source_files = set(source_snapshot.files) if source_snapshot else set()
    sql_feedback_before_write: list[dict[str, Any]] = []
    latest_sql: dict[str, Any] | None = None
    for event in events:
        if event["type"] == "tool.completed" and event.get("tool") == "query_sql":
            latest_sql = {"tool_call_id": event.get("tool_call_id"), "ok": event.get("result", {}).get("ok"), "result": event.get("result")}
        if event["type"] == "agent.file_write":
            sql_feedback_before_write.append({"path": event.get("path"), "preceding_sql_feedback": latest_sql})
    return {
        "episode": episode["order"], "episode_id": episode["id"], "condition": episode["condition"],
        "initial_memory": episode["initial_memory"], "attempt_id": prepared.session.attempt_id,
        "conversation_id": prepared.session.conversation_id, "prompt": prepared.prompt,
        "prompt_hash": stable_hash(prepared.prompt), "request_config_hash": prepared.request_config_hash,
        "model_requests": len(providers), "usage_by_request": [event.get("usage") for event in providers],
        "cost_by_request": [event.get("billed_cost_estimate") for event in providers],
        "finish_reasons": [event.get("stop_reason") for event in providers], "tool_counts": _tool_counts(events),
        "file_reads_succeeded": len(reads), "directory_listings_succeeded": len(listings),
        "sql_queries_completed": database.successful_queries, "sql_queries_failed": database.failed_queries,
        "final_answer": answer, "task_score": score, "final_answer_validity": validity,
        "terminal_assessment_v2": evaluate_terminal_result_v2(
            answer=answer, raw_answer_correct=score.get("correct"), metrics=metrics, events=events,
            max_requests=runner.receiver_config["max_requests_per_episode"], max_tools=runner.receiver_config["max_tools_per_episode"],
        ),
        "runner_stop_reason": metrics.get("runner_stop_reason"), "metrics": metrics,
        "output_snapshot_hash": snapshot.content_hash, "output_snapshot_files": list(snapshot.files),
        "source_artifacts": _artifact_details(snapshot) if episode["condition"] == "PC-SOURCE" else [],
        "source_write_sql_feedback_provenance": sql_feedback_before_write if episode["condition"] == "PC-SOURCE" else [],
        "memory_read_source_artifact_paths": [event.get("path") for event in reads if event.get("path", "").removeprefix("/memory/") in source_files],
        "empty_listing_observed": any(event.get("path") == "/memory" and event.get("returned") == 0 for event in listings),
    }


def _ledger_summary(ledger: CostLedger) -> dict[str, Any]:
    unknown = [entry for entry in ledger.entries if entry["status"] == "billing_unknown"]
    return {
        "reserved_usd": str(ledger.reserved), "settled_conservative_cache_miss_estimate_usd": str(ledger.settled),
        "unknown_billing_request_count": len(unknown), "actual_provider_invoice_available": False,
    }


def _prior_live_run_exists(output_root: Path, authorization_hash: str) -> bool:
    for manifest in Path(output_root).glob("*/research_records/file_positive_control_run_manifest.json"):
        try:
            prior = _load_json(manifest)
        except (OSError, json.JSONDecodeError):
            continue
        if prior.get("mode") == "live" and prior.get("authorization_record_sha256") == authorization_hash:
            return True
    return False


def execute(
    *, pending_path: Path, tasks_path: Path, authorization_path: Path, output_root: Path,
    mode: str, adapter: ProviderAdapter | None = None,
) -> Path:
    """Execute one parsed PC batch in plan-only, fake, or explicit live mode."""
    if mode not in {"plan-only", "fake", "live"}:
        raise ValueError("mode must be plan-only, fake, or live")
    spec = load_spec(pending_path, tasks_path, authorization_path)
    if mode == "fake" and adapter is None:
        raise ValueError("fake mode requires an injected fake transport adapter")
    if mode == "live" and adapter is not None:
        raise ValueError("live mode constructs the configured provider adapter itself")
    if mode == "live" and _prior_live_run_exists(output_root, spec.authorization_hash):
        raise AuthorizationError("this authorization is already bound to a prior live PC run")
    receiver_config = _receiver_config(spec)
    runner = ExperimentRunner(output_root, receiver_config=receiver_config)
    code_hashes = _code_hashes()
    manifest = {
        "study_kind": "engineering_positive_control", "included_in_primary_analysis": False, "mode": mode,
        "run_id": runner.run_id, "generated_at": datetime.now(timezone.utc).isoformat(),
        "pending_path": str(pending_path), "pending_sha256": spec.pending_hash,
        "tasks_path": str(tasks_path), "tasks_sha256": spec.tasks_hash,
        "authorization_path": str(authorization_path), "authorization_record_sha256": spec.authorization_hash,
        "receiver_config": receiver_config, "receiver_config_hash": stable_hash(receiver_config),
        "code_hashes": code_hashes, "combined_code_hash": stable_hash(code_hashes),
        "episodes": spec.pending["episodes"], "request_reservation_usd": str(spec.config.worst_case_request_cost(spec.prices)),
        "batch_reservation_usd": str(spec.config.worst_case_request_cost(spec.prices) * spec.live_authorization.max_requests),
        "hard_cap_usd": str(spec.live_authorization.hard_cap), "no_code_execution_calls": True,
    }
    runner.records.write_json("file_positive_control_run_manifest.json", manifest)
    if mode == "plan-only":
        runner.records.write_json("file_positive_control_plan.json", {"requests_sent": 0, "episodes": spec.pending["episodes"], "mode": mode})
        return runner.records.root / "file_positive_control_plan.json"
    if mode == "live":
        client = build_authorized_client(spec.live_authorization, spec.config)
        if not isinstance(client.adapter, ProviderAdapter):
            raise RuntimeError("configured client did not provide a provider adapter")
        adapter = client.adapter
    assert adapter is not None
    ledger = CostLedger(spec.live_authorization)
    report: dict[str, Any] = {
        "status": "RUNNING", "study_kind": "engineering_positive_control", "included_in_primary_analysis": False,
        "mode": mode, "run_id": runner.run_id, "manifest": manifest, "episodes": [], "provider_requests_sent": 0,
        "no_code_execution_calls": True, "fourth_episode_started": False,
    }
    source_snapshot: Snapshot | None = None
    source_hash_before_probes: str | None = None
    try:
        source_episode = spec.pending["episodes"][0]
        source_prepared = _prepare(runner, source_episode)
        source_db = create_local_fixture(runner.root / "tool_service" / "episode-1", max_queries=spec.config.max_tool_calls_per_episode)
        source_answer, source_snapshot, source_metrics = run_tool_only_episode(
            prepared=source_prepared, manager=runner.manager, records=runner.records, database=source_db, adapter=adapter,
            ledger=ledger, config=spec.config, prices=spec.prices, transport_kind="live_provider" if mode == "live" else "fake_transport",
        )
        source_hash_before_probes = hash_tree(source_snapshot.path)[0]
        source_evidence = _episode_evidence(runner=runner, episode=source_episode, prepared=source_prepared, database=source_db,
                                            answer=source_answer, snapshot=source_snapshot, metrics=source_metrics, source_snapshot=None)
        source_evidence.update({"actual_model_id": spec.config.exact_model_id, "source_artifact_nonempty": bool(source_snapshot.files),
                                "positive_control_status": "MET" if source_snapshot.files else "POSITIVE_CONTROL_NOT_MET"})
        report["episodes"].append(source_evidence)
        for episode, parent in ((spec.pending["episodes"][1], source_snapshot), (spec.pending["episodes"][2], runner.manager.empty_snapshot())):
            prepared = _prepare(runner, episode, parent)
            database = create_local_fixture(runner.root / "tool_service" / f"episode-{episode['order']}", max_queries=spec.config.max_tool_calls_per_episode)
            answer, snapshot, metrics = run_tool_only_episode(
                prepared=prepared, manager=runner.manager, records=runner.records, database=database, adapter=adapter,
                ledger=ledger, config=spec.config, prices=spec.prices, transport_kind="live_provider" if mode == "live" else "fake_transport",
            )
            evidence = _episode_evidence(runner=runner, episode=episode, prepared=prepared, database=database,
                                         answer=answer, snapshot=snapshot, metrics=metrics, source_snapshot=source_snapshot)
            evidence.update({"actual_model_id": spec.config.exact_model_id, "parent_snapshot_hash": parent.content_hash,
                             "parent_snapshot_unchanged": hash_tree(parent.path)[0] == parent.content_hash})
            report["episodes"].append(evidence)
    except Exception as exc:  # preserve a partial run; no retry or fourth episode.
        report.update({"status": "STOPPED", "stop_reason": type(exc).__name__, "error": str(exc)})
    report["provider_requests_sent"] = len(ledger.entries)
    report["ledger"] = ledger.entries
    report["ledger_summary"] = _ledger_summary(ledger)
    report["billing_unknown"] = ledger.billing_unknown
    if source_snapshot is not None:
        report["source_snapshot_hash_before_probes"] = source_hash_before_probes
        report["source_snapshot_unchanged_after_all_probes"] = hash_tree(source_snapshot.path)[0] == source_snapshot.content_hash
    if report["status"] == "RUNNING":
        report["status"] = "COMPLETED" if len(report["episodes"]) == 3 else "STOPPED"
    report_path = runner.root / "FILE_POSITIVE_CONTROL_RUN_REPORT.md"
    report_path.write_text("# FILE POSITIVE CONTROL RUN REPORT\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")
    return report_path


def load_atomic_spec(pending_path: Path, tasks_path: Path, authorization_path: Path) -> PositiveControlSpec:
    """Load the separately authorized atomic file-I/O control without touching PC data."""
    pending, authorization = _load_json(pending_path), _load_json(authorization_path)
    tasks = tasks_path.read_text(encoding="utf-8")
    pending_hash, tasks_hash, authorization_hash = _sha256(pending_path), _sha256(tasks_path), _sha256(authorization_path)
    if authorization.get("frozen_pending_config", {}).get("sha256") != pending_hash:
        raise AuthorizationError("atomic pending configuration SHA-256 differs from its authorization record")
    if authorization.get("frozen_task_manifest", {}).get("sha256") != tasks_hash:
        raise AuthorizationError("atomic task-manifest SHA-256 differs from its authorization record")
    if pending.get("status") != "PENDING_INDEPENDENT_USER_SIGNOFF_NO_LIVE_CALLS":
        raise AuthorizationError("atomic pending configuration was changed")
    if authorization.get("status") not in {"PENDING_INDEPENDENT_USER_SIGNOFF_NO_LIVE_CALLS", "AUTHORIZED_FOR_EXACT_TWO_ATOMIC_FILE_IO_EPISODES"}:
        raise AuthorizationError("atomic authorization status is invalid")
    if pending.get("study_kind") != "engineering_atomic_file_io_control" or pending.get("included_in_primary_analysis") is not False:
        raise AuthorizationError("atomic control analysis scope is invalid")
    if authorization.get("study_kind") != pending["study_kind"] or authorization.get("included_in_primary_analysis") is not False:
        raise AuthorizationError("atomic authorization scope differs from the pending control")
    expected = [(1, "pc_atomic_write", "PC-WRITE"), (2, "pc_atomic_read", "PC-READ")]
    actual = [(item.get("order"), item.get("id"), item.get("condition")) for item in pending.get("episodes", [])]
    if actual != expected:
        raise AuthorizationError("atomic control must contain only PC-WRITE followed by PC-READ")
    if pending["episodes"][0].get("allowed_tools") != ["query_sql", "write_file"] or pending["episodes"][1].get("allowed_tools") != ["list_dir", "read_file"]:
        raise AuthorizationError("atomic per-episode tool boundaries differ from the control")
    if "SELECT payload FROM io_probe" not in pending["episodes"][0].get("instruction", "") or "BLOCKED_SOURCE_ARTIFACT" not in pending.get("source_failure_rule", ""):
        raise AuthorizationError("atomic task or source-failure rule differs from the frozen control")
    config, prices = _config(pending), _prices(pending)
    config.validate()
    budget = pending["budget_proposal"]
    worst = config.worst_case_request_cost(prices)
    if str(worst) != budget["worst_case_per_request_usd"] or budget["max_provider_requests"] != 12:
        raise AuthorizationError("atomic reservation mapping is inconsistent")
    if worst * Decimal(12) != Decimal(budget["worst_case_total_usd"]) or Decimal(budget["worst_case_total_usd"]) > Decimal(budget["proposed_hard_cap_usd"]):
        raise BudgetError("atomic reservation exceeds its proposed cap")
    if authorization.get("provider") != pending["provider"] or authorization.get("exact_model_id") != pending["exact_model_id"]:
        raise AuthorizationError("atomic authorization model differs from the pending configuration")
    if authorization.get("real_model_requests_sent_under_this_authorization") != 0:
        raise AuthorizationError("atomic authorization has already been consumed")
    if authorization.get("max_episodes") != 2 or authorization.get("max_provider_requests") != 12 or authorization.get("hard_cap_usd") != budget["proposed_hard_cap_usd"]:
        raise AuthorizationError("atomic authorization bounds differ from the frozen configuration")
    live_authorization = LiveAuthorization(True, pending["provider"], pending["exact_model_id"], budget["currency"], Decimal(budget["proposed_hard_cap_usd"]), 12, budget["price_source"], max_episodes=2)
    return PositiveControlSpec(pending, tasks, authorization, pending_hash, tasks_hash, authorization_hash, config, prices, live_authorization)


def _prepare_atomic(runner: ExperimentRunner, episode: dict[str, Any], parent: Snapshot | None = None) -> PreparedTask:
    session = runner.manager.start_task(condition=episode["condition"], replicate="atomic-io", task_id=episode["id"], parent=parent)
    # Neither prompt contains a runtime marker, source file name, or source conversation.
    prompt = f"This is the {episode['condition']} engineering file-I/O control.\n\nTask: {episode['instruction']}"
    allowed = set(episode["allowed_tools"])
    prepared = PreparedTask(session, prompt, _tool_schema_hash(allowed), stable_hash(_receiver_config_from_runner(runner)))
    runner.records.emit("task.prepared", attempt_id=session.attempt_id, condition=episode["condition"], task_id=episode["id"],
                        conversation_id=session.conversation_id, parent_snapshot_id=session.parent_snapshot_id,
                        prompt_hash=stable_hash(prompt), tool_schema_hash=prepared.tool_schema_hash,
                        request_config_hash=prepared.request_config_hash)
    return prepared


def _source_saved_exact_marker(snapshot: Snapshot, marker: str, events: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    query_feedback_has_marker = any(event.get("tool") == "query_sql" and marker in event.get("result", {}).get("output", "") for event in events if event["type"] == "tool.completed")
    exact = [relative for relative in snapshot.files if (snapshot.path / relative).read_text(encoding="utf-8", errors="replace") == marker]
    return bool(query_feedback_has_marker and exact), exact


def execute_atomic(
    *, pending_path: Path, tasks_path: Path, authorization_path: Path, output_root: Path,
    mode: str, adapter: ProviderAdapter | None = None,
) -> Path:
    """Run the two-episode atomic control; live mode remains blocked until separately signed."""
    if mode not in {"plan-only", "fake", "live"}:
        raise ValueError("mode must be plan-only, fake, or live")
    spec = load_atomic_spec(pending_path, tasks_path, authorization_path)
    if mode == "live" and (spec.authorization.get("status") != "AUTHORIZED_FOR_EXACT_TWO_ATOMIC_FILE_IO_EPISODES" or spec.authorization.get("live_requests_authorized") is not True):
        raise AuthorizationError("atomic live execution requires a new independently signed authorization")
    if mode == "live" and _prior_atomic_live_run_exists(output_root, spec.authorization_hash):
        raise AuthorizationError("this atomic authorization is already bound to a prior live run")
    if mode == "fake" and adapter is None:
        raise ValueError("atomic fake mode requires an injected fake adapter")
    receiver_config = _receiver_config(spec)
    runner = ExperimentRunner(output_root, receiver_config=receiver_config)
    manifest = {
        "study_kind": "engineering_atomic_file_io_control", "included_in_primary_analysis": False,
        "mode": mode, "run_id": runner.run_id, "pending_sha256": spec.pending_hash, "tasks_sha256": spec.tasks_hash,
        "authorization_record_sha256": spec.authorization_hash, "receiver_config": receiver_config,
        "code_hashes": _code_hashes(), "episodes": spec.pending["episodes"],
        "request_reservation_usd": str(spec.config.worst_case_request_cost(spec.prices)),
        "batch_reservation_usd": str(spec.config.worst_case_request_cost(spec.prices) * 12), "hard_cap_usd": "0.20",
        "no_code_execution_calls": True,
    }
    runner.records.write_json("atomic_file_io_control_manifest.json", manifest)
    if mode == "plan-only":
        return runner.records.write_json("atomic_file_io_control_plan.json", {"requests_sent": 0, "episodes": spec.pending["episodes"]})
    if mode == "live":
        client = build_authorized_client(spec.live_authorization, spec.config)
        if not isinstance(client.adapter, ProviderAdapter):
            raise RuntimeError("configured atomic client did not provide an adapter")
        adapter = client.adapter
    assert adapter is not None
    ledger = CostLedger(spec.live_authorization)
    report: dict[str, Any] = {"status": "RUNNING", "study_kind": "engineering_atomic_file_io_control", "included_in_primary_analysis": False,
                              "mode": mode, "run_id": runner.run_id, "manifest": manifest, "episodes": [], "provider_requests_sent": 0,
                              "no_code_execution_calls": True}
    source_snapshot: Snapshot | None = None
    try:
        write_episode, read_episode = spec.pending["episodes"]
        write_prepared = _prepare_atomic(runner, write_episode)
        write_db, marker = create_atomic_file_io_fixture(runner.root / "tool_service" / "pc-write", max_queries=spec.config.max_tool_calls_per_episode)
        answer, source_snapshot, metrics = run_tool_only_episode(prepared=write_prepared, manager=runner.manager, records=runner.records,
            database=write_db, adapter=adapter, ledger=ledger, config=spec.config, prices=spec.prices,
            transport_kind="live_provider" if mode == "live" else "fake_transport", allowed_tool_names=set(write_episode["allowed_tools"]))
        write_events = _events(runner.records.path, write_prepared.session.attempt_id)
        saved, paths = _source_saved_exact_marker(source_snapshot, marker, write_events)
        report["episodes"].append({"episode_id": write_episode["id"], "condition": "PC-WRITE", "attempt_id": write_prepared.session.attempt_id,
            "prompt_hash": stable_hash(write_prepared.prompt), "marker_was_absent_from_prompt": marker not in write_prepared.prompt,
            "model_requests": len([e for e in write_events if e["type"] == "provider.request_finished"]), "tool_counts": _tool_counts(write_events),
            "sql_feedback_contained_marker": any(marker in e.get("result", {}).get("output", "") for e in write_events if e["type"] == "tool.completed" and e.get("tool") == "query_sql"),
            "source_saved_exact_marker": saved, "source_marker_paths": paths, "source_snapshot_hash": source_snapshot.content_hash,
            "final_answer": answer, "metrics": metrics, "stop_reason": metrics.get("runner_stop_reason")})
        if not saved:
            report["episodes"].append({"episode_id": read_episode["id"], "condition": "PC-READ", "status": "BLOCKED_SOURCE_ARTIFACT", "model_requests": 0,
                                       "reason": spec.pending["source_failure_rule"]})
        else:
            read_prepared = _prepare_atomic(runner, read_episode, source_snapshot)
            read_db, _ = create_atomic_file_io_fixture(runner.root / "tool_service" / "pc-read", max_queries=spec.config.max_tool_calls_per_episode)
            read_answer, read_snapshot, read_metrics = run_tool_only_episode(prepared=read_prepared, manager=runner.manager, records=runner.records,
                database=read_db, adapter=adapter, ledger=ledger, config=spec.config, prices=spec.prices,
                transport_kind="live_provider" if mode == "live" else "fake_transport", allowed_tool_names=set(read_episode["allowed_tools"]))
            read_events = _events(runner.records.path, read_prepared.session.attempt_id)
            read_paths = [e.get("path") for e in read_events if e["type"] == "agent.file_read"]
            report["episodes"].append({"episode_id": read_episode["id"], "condition": "PC-READ", "attempt_id": read_prepared.session.attempt_id,
                "prompt_hash": stable_hash(read_prepared.prompt), "marker_was_absent_from_initial_prompt": marker not in read_prepared.prompt,
                "source_filename_was_absent_from_initial_prompt": all(path not in read_prepared.prompt for path in paths),
                "model_requests": len([e for e in read_events if e["type"] == "provider.request_finished"]), "tool_counts": _tool_counts(read_events),
                "read_source_paths": read_paths, "returned_exact_marker": read_answer.strip() == marker,
                "source_snapshot_unchanged": hash_tree(source_snapshot.path)[0] == source_snapshot.content_hash,
                "final_answer": read_answer, "metrics": read_metrics, "stop_reason": read_metrics.get("runner_stop_reason"),
                "output_snapshot_hash": read_snapshot.content_hash})
    except Exception as exc:
        report.update({"status": "STOPPED", "stop_reason": type(exc).__name__, "error": str(exc)})
    report["provider_requests_sent"] = len(ledger.entries)
    report["ledger"] = ledger.entries
    report["ledger_summary"] = _ledger_summary(ledger)
    report["billing_unknown"] = ledger.billing_unknown
    if report["status"] == "RUNNING":
        report["status"] = "COMPLETED"
    report_path = runner.root / "ATOMIC_FILE_IO_CONTROL_RUN_REPORT.md"
    report_path.write_text("# ATOMIC FILE I/O CONTROL RUN REPORT\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")
    return report_path


def _prior_atomic_live_run_exists(output_root: Path, authorization_hash: str) -> bool:
    for manifest in Path(output_root).glob("*/research_records/atomic_file_io_control_manifest.json"):
        try:
            prior = _load_json(manifest)
        except (OSError, json.JSONDecodeError):
            continue
        if prior.get("mode") == "live" and prior.get("authorization_record_sha256") == authorization_hash:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run only the frozen three-episode file positive control")
    parser.add_argument("--pending", type=Path, default=Path("experiments/experience_value/file_positive_control.pending.json"))
    parser.add_argument("--tasks", type=Path, default=Path("experiments/experience_value/file_positive_control.tasks.md"))
    parser.add_argument("--authorization", type=Path, default=Path("experiments/experience_value/file_positive_control.authorized_20260921T111831Z.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--atomic-plan-only", action="store_true")
    mode.add_argument("--atomic-live", action="store_true")
    args = parser.parse_args()
    if args.atomic_plan_only or args.atomic_live:
        print(execute_atomic(
            pending_path=Path("experiments/experience_value/atomic_file_io_control.pending.json"),
            tasks_path=Path("experiments/experience_value/atomic_file_io_control.tasks.md"),
            authorization_path=Path(
                "experiments/experience_value/atomic_file_io_control.authorization.pending.json"
                if args.atomic_plan_only else "experiments/experience_value/atomic_file_io_control.authorization.authorized_20260921T123757Z.json"
            ),
            output_root=args.output_root, mode="plan-only" if args.atomic_plan_only else "live",
        ))
        return
    selected_mode = "plan-only" if args.plan_only else "live"
    print(execute(pending_path=args.pending, tasks_path=args.tasks, authorization_path=args.authorization,
                  output_root=args.output_root, mode=selected_mode))


if __name__ == "__main__":
    main()
