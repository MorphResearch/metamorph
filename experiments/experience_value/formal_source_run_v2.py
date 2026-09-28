"""Manifest-driven formal-source runner for Blocks 2--8 (and offline V1 checks).

This is an operational successor to ``formal_source_run``.  It deliberately
does not alter the V1 module or any historical Block 1 evidence.  All episode
selection comes from the frozen manifest and the frozen block definition;
predecessor snapshots are supplied as signed, runner-only provenance in the
block-scoped pending configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from llm.adapters import ProviderAdapter

from .clbench_database_exploration import DatabaseExplorationAdapter
from .live import PriceSheet, ToolOnlySmokeConfig, build_authorized_client, run_tool_only_episode
from .public_calibration_run import ALLOWED_TOOLS, FILE_TOOLS, NativeQueryTool, _offpeak_status, _provider_connectivity_preflight
from .public_viability_gate_run import _code_hashes, _empty_episode, _episode_report, _events
from .records import AuthorizationError, CostLedger, LiveAuthorization
from .runner import ExperimentRunner
from .workspace import Snapshot, hash_tree

ROOT = Path(__file__).resolve().parents[2]
FORMAL_RUNS_ROOT = ROOT / "artifacts/experience_value/formal_source"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _within(path: Path, root: Path) -> Path:
    resolved, allowed = path.resolve(), root.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise AuthorizationError("formal provenance path is outside its allowed runner-only root") from exc
    return resolved


def _source_item(position: int, token: str) -> dict[str, Any]:
    match = re.fullmatch(r"t(\d+)-(F0|U0|F1|U1)", token)
    if not match:
        raise AuthorizationError("invalid frozen manifest source token")
    task_id, condition = match.groups()
    return {
        "id": f"formal-{token.lower()}",
        "task_id": task_id,
        "task_index": int(task_id) - 1,
        "condition": condition,
        "manifest_position": position,
        "artifact_path": f"/memory/experience_{int(task_id) - 6:03d}.md",
    }


def _config_from_formal(formal: dict[str, Any]) -> ToolOnlySmokeConfig:
    request = formal["shared_execution"]
    return ToolOnlySmokeConfig(
        provider=formal["provider"], exact_model_id=formal["exact_model_id"], base_url=formal["base_url"],
        api_key_env=formal["api_key_env_name_only"], max_input_characters=0,
        max_input_tokens_per_request=request["max_input_tokens_per_request"],
        max_output_tokens_per_request=request["max_output_tokens_per_request"],
        max_requests_per_episode=request["max_main_model_decisions_per_episode"],
        max_tool_calls_per_episode=23, timeout_seconds=request["request_timeout_seconds"], retries=0,
        max_transport_retries=request["max_pre_response_transport_retries"], temperature=None,
        thinking_enabled=True, reasoning_effort="low", episode_timeout_seconds=request["episode_timeout_seconds"],
        max_file_return_bytes=32768, enforce_utf8_input_reservation=True,
        formal_input_cutoff_estimator=request["formal_input_cutoff"]["name"],
    )


def _required_predecessor(item: dict[str, Any], source: dict[str, Any]) -> tuple[str, str] | None:
    """Return immediate same-condition predecessor token, never a hand-built merge."""
    if item["condition"] not in {"F1", "U1"} or int(item["task_id"]) == min(source["formal_eligible"]["source_task_ids"]):
        return None
    predecessor_task = int(item["task_id"]) - 1
    if predecessor_task not in source["formal_eligible"]["source_task_ids"]:
        raise AuthorizationError("formal predecessor is not an eligible source task")
    return (f"t{predecessor_task:02d}-{item['condition']}", f"formal-t{predecessor_task:02d}-{item['condition'].lower()}")


def _load_predecessor(*, reference: dict[str, Any], item: dict[str, Any], pending: dict[str, Any]) -> Snapshot:
    """Verify a historical formal output and return its immutable snapshot.

    Every location comes from pending provenance, but every one is constrained
    to the runner's formal-record roots.  The provider never sees this metadata.
    """
    expected_token, expected_episode = _required_predecessor(item, json.loads((ROOT / pending["source_manifest"]["path"]).read_text())) or (None, None)
    if expected_token is None:
        raise AuthorizationError("an empty-memory condition supplied a predecessor")
    if reference.get("predecessor_token") != expected_token or reference.get("episode_id") != expected_episode:
        raise AuthorizationError("predecessor is not the immediate same-condition formal source")
    if reference.get("condition") != item["condition"] or int(reference.get("task_id", -1)) != int(item["task_id"]) - 1:
        raise AuthorizationError("predecessor condition/task mismatch")
    if reference.get("study_kind") != "formal_source_v1" or reference.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("predecessor is not an eligible formal primary-analysis source")
    if reference.get("formal_protocol_sha256") != pending["formal_protocol"]["sha256"] or reference.get("source_manifest_sha256") != pending["source_manifest"]["sha256"]:
        raise AuthorizationError("predecessor protocol/manifest lineage differs")

    run_id = str(reference.get("run_id", ""))
    if not re.fullmatch(r"e0-[0-9a-f]{32}", run_id):
        raise AuthorizationError("invalid formal predecessor run identity")
    run_root = _within(FORMAL_RUNS_ROOT / run_id, FORMAL_RUNS_ROOT)
    record_path = _within(ROOT / reference.get("record_path", ""), run_root)
    auth_path = _within(ROOT / reference.get("authorization_path", ""), ROOT / "experiments/experience_value")
    snapshot_id = str(reference.get("snapshot_id", ""))
    snapshot_path = _within(run_root / "frozen_snapshots" / snapshot_id, run_root / "frozen_snapshots")
    if not record_path.is_file() or not auth_path.is_file() or not snapshot_path.is_dir():
        raise AuthorizationError("required formal predecessor record, authorization, or snapshot is missing")

    record, authorization = json.loads(record_path.read_text()), json.loads(auth_path.read_text())
    if record.get("study_kind") != "formal_source_v1" or record.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("predecessor run record is not a formal source run")
    if authorization.get("study_kind") != "formal_source_v1" or authorization.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("predecessor authorization is not a formal primary-analysis source")
    if authorization.get("formal_protocol", {}).get("sha256") != pending["formal_protocol"]["sha256"] or authorization.get("source_manifest", {}).get("sha256") != pending["source_manifest"]["sha256"]:
        raise AuthorizationError("predecessor authorization lineage differs")
    if authorization.get("consumption_run_id") != run_id:
        raise AuthorizationError("predecessor authorization is not bound to the recorded run")

    episode = next((row for row in record.get("episodes", []) if row.get("episode_id") == expected_episode), None)
    if episode is None or episode.get("condition") != item["condition"] or str(episode.get("task_id")) != str(int(item["task_id"]) - 1):
        raise AuthorizationError("predecessor episode record differs")
    checks = episode.get("contamination_checks", {})
    if checks.get("development_source_mounted") is not False or checks.get("evaluator_reference_visible") is not False:
        raise AuthorizationError("predecessor contamination or evaluator-visibility check failed")
    provenance = next((row for row in episode.get("artifact_provenance", []) if row.get("path") == reference.get("artifact_path")), None)
    if provenance is None:
        raise AuthorizationError("predecessor artifact provenance is missing")
    if provenance.get("condition") != item["condition"] or provenance.get("source_episode") != expected_episode or provenance.get("evaluator_or_reference_visible") is not False:
        raise AuthorizationError("predecessor artifact provenance is ineligible")
    if provenance.get("snapshot_id") != snapshot_id or provenance.get("snapshot_hash") != reference.get("snapshot_hash"):
        raise AuthorizationError("predecessor snapshot identity/hash differs")
    if provenance.get("committed_file_sha256") != reference.get("artifact_sha256") or provenance.get("raw_visible_content_sha256") != reference.get("artifact_sha256"):
        raise AuthorizationError("predecessor artifact bytes do not match provenance")

    actual_hash, files = hash_tree(snapshot_path)
    if actual_hash != reference.get("snapshot_hash"):
        raise AuthorizationError("predecessor snapshot was altered after freeze")
    artifact = snapshot_path / str(reference.get("artifact_path", "")).lstrip("/").removeprefix("memory/")
    # Snapshot roots contain logical /memory contents, not an agent root.
    if not artifact.is_file() or sha(artifact) != reference.get("artifact_sha256"):
        raise AuthorizationError("predecessor artifact is absent or altered")
    if artifact.relative_to(snapshot_path).as_posix() not in files:
        raise AuthorizationError("predecessor artifact is not inside the frozen snapshot")
    return Snapshot(snapshot_id, snapshot_path, actual_hash, None, episode.get("attempt_id"), files)


def _resolve_parents(pending: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Snapshot | None]:
    references = pending.get("predecessor_references", {})
    parents: dict[str, Snapshot | None] = {}
    for item in items:
        needed = _required_predecessor(item, json.loads((ROOT / pending["source_manifest"]["path"]).read_text()))
        if needed is None:
            if item["id"] in references:
                raise AuthorizationError("empty-memory formal condition may not carry a predecessor")
            parents[item["id"]] = None
            continue
        reference = references.get(item["id"])
        if not isinstance(reference, dict):
            raise AuthorizationError("required immediate formal predecessor is missing before provider setup")
        parents[item["id"]] = _load_predecessor(reference=reference, item=item, pending=pending)
    if set(references) != {item["id"] for item in items if _required_predecessor(item, json.loads((ROOT / pending["source_manifest"]["path"]).read_text())) is not None}:
        raise AuthorizationError("pending predecessor reference set differs from this frozen block")
    return parents


def _load(pending_path: Path, authorization_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Snapshot | None], ToolOnlySmokeConfig, PriceSheet, dict[str, Any]]:
    pending, authorization = json.loads(pending_path.read_text()), json.loads(authorization_path.read_text())
    if pending.get("status") != "PENDING_FORMAL_SOURCE_BLOCK_V2_USER_SIGNOFF_NO_LIVE_CALLS" or pending.get("study_kind") != "formal_source_v1" or pending.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("formal source V2 pending scope is invalid")
    for field in ("formal_protocol", "source_manifest", "block_definition", "formal_pending"):
        ref = pending[field]
        if sha(ROOT / ref["path"]) != ref["sha256"]:
            raise AuthorizationError(f"{field} hash differs")
    formal = json.loads((ROOT / pending["formal_pending"]["path"]).read_text())
    source = json.loads((ROOT / pending["source_manifest"]["path"]).read_text())
    blocks = json.loads((ROOT / pending["block_definition"]["path"]).read_text())
    block = next((value for value in blocks["blocks"] if value["id"] == pending.get("block_id")), None)
    if block is None:
        raise AuthorizationError("block_id is not part of the frozen formal source blocks")
    positions = block.get("manifest_positions", [])
    if not positions or positions != list(range(positions[0], positions[0] + len(positions))):
        raise AuthorizationError("formal block positions must be a frozen contiguous block")
    tokens = [source["execution_order"][position - 1] for position in positions]
    if tokens != block.get("expected_tokens"):
        raise AuthorizationError("frozen block tokens differ from frozen source manifest")
    items = [_source_item(position, token) for position, token in zip(positions, tokens)]
    if any(int(item["task_id"]) not in source["formal_eligible"]["source_task_ids"] for item in items):
        raise AuthorizationError("non-formal source task entered a source block")
    if set(source["development_contacted_ids"]) & {int(item["task_id"]) for item in items}:
        raise AuthorizationError("development task entered formal block")
    frozen = authorization.get("frozen_pending_config", {})
    try:
        pending_relative_path = str(pending_path.resolve().relative_to(ROOT))
    except ValueError as exc:
        raise AuthorizationError("pending configuration must remain beneath the project root") from exc
    if frozen.get("path") != pending_relative_path or frozen.get("sha256") != sha(pending_path):
        raise AuthorizationError("authorization does not bind this V2 pending")
    expected_deps = _code_hashes() | {"entry": sha(Path(__file__))}
    if authorization.get("entry_code", {}).get("path") != "experiments/experience_value/formal_source_run_v2.py" or authorization.get("entry_code", {}).get("sha256") != sha(Path(__file__)) or authorization.get("code_dependencies") != expected_deps:
        raise AuthorizationError("authorization does not bind V2 code and dependencies")
    if authorization.get("block_definition", {}).get("block_id") != pending["block_id"] or authorization.get("block_definition", {}).get("allowed_manifest_positions") != positions or authorization.get("block_definition", {}).get("allowed_tokens") != tokens:
        raise AuthorizationError("authorization block scope differs from frozen pending")
    signed_predecessors = authorization.get("required_predecessors", {})
    if set(signed_predecessors) != set(pending.get("predecessor_references", {})):
        raise AuthorizationError("authorization predecessor set differs from frozen pending")
    for episode_id, reference in pending.get("predecessor_references", {}).items():
        signed = signed_predecessors.get(episode_id, {})
        for field in ("run_id", "snapshot_id", "snapshot_hash", "artifact_sha256"):
            if signed.get(field) != reference.get(field):
                raise AuthorizationError("authorization predecessor identity differs from frozen pending")
    parents = _resolve_parents(pending, items)  # All provenance checks precede any client construction.
    config = _config_from_formal(formal)
    price = pending["budget"]
    prices = PriceSheet(Decimal(price["input_cache_miss_usd_per_million"]), Decimal(price["output_usd_per_million"]), price["price_source"], price["price_checked_on"], Decimal(price["input_cache_hit_usd_per_million"]))
    if config.worst_case_request_cost(prices) * Decimal(price["max_provider_attempts"]) > Decimal(price["hard_cap_usd"]):
        raise AuthorizationError("block reservation exceeds hard cap")
    return pending, authorization, items, parents, config, prices, block


def _write(report: dict[str, Any], path: Path) -> None:
    lines = ["# Formal source block report", "", f"Status: **{report['status']}**", "", "`study_kind=formal_source_v1`", "", "`included_in_primary_analysis=true`", ""]
    for episode in report["episodes"]:
        lines.append(f"- pos {episode.get('manifest_position')}: task {episode['task_id']} {episode['condition']}; started={episode['started']}; ANSWER={episode['native_answer_submitted']}; correct={episode['correct']}; score={episode['native_score']}; attempts={episode['provider_attempts']}; SQL={episode['sql_queries']}; artifact={episode.get('artifact_paths')}; inheritance={episode.get('inheritance_source')}; stop={episode['main_stop_reason']}")
    lines += ["", f"- Next frozen manifest position: `{report['next_manifest_position']}`", f"- Attempts/responses: `{report['provider_attempts']}/{report['provider_responses']}`; cost: `{report['known_cost_estimate']}`; unknown billing: `{report['unknown_billing_attempts']}`", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _consume_after_dispatch(path: Path, events: list[dict[str, Any]], run_id: str, block_id: str) -> None:
    if not any(event.get("type") == "provider.request_started" for event in events):
        return
    payload = json.loads(path.read_text())
    if payload.get("real_model_requests_sent_under_this_authorization", 0):
        return
    payload.update(status=f"CONSUMED_{block_id.upper()}", real_model_requests_sent_under_this_authorization=1, consumption_run_id=run_id, consumed_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def execute(*, pending_path: Path, authorization_path: Path, output_root: Path, mode: str, adapter: ProviderAdapter | None = None, report_path: Path | None = None) -> Path:
    pending, authorization, items, parents, config, prices, block = _load(pending_path, authorization_path)
    if mode not in {"plan-only", "fake", "live"}:
        raise ValueError("mode")
    if mode == "live" and not (authorization.get("status") == f"AUTHORIZED_{pending['block_id'].upper()}" and authorization.get("live_requests_authorized") is True and authorization.get("real_model_requests_sent_under_this_authorization") == 0):
        raise AuthorizationError("formal V2 block requires an independent unused authorization")
    runner = ExperimentRunner(output_root)
    report_path = report_path or ROOT / "FORMAL_SOURCE_BLOCK_REPORT.md"
    if mode == "plan-only":
        return runner.records.write_json("formal_source_plan.json", {"provider_requests": 0, "block_id": pending["block_id"], "episodes": items, "next_manifest_position": block["next_position"]})
    report: dict[str, Any] = {"status": "RUNNING", "study_kind": "formal_source_v1", "included_in_primary_analysis": True, "block_id": pending["block_id"], "episodes": [], "provider_attempts": 0, "provider_responses": 0, "known_cost_estimate": "0", "unknown_billing_attempts": 0, "next_manifest_position": block["next_position"], "preflight": None, "time_window": None, "infrastructure_status": "NOT_APPLICABLE"}
    if mode == "live":
        window = _offpeak_status({"offpeak_window": {"timezone": "Asia/Shanghai", "start_local": "18:05:00", "end_local": "08:55:00", "minimum_remaining_seconds_for_new_episode": 1080}}, for_new_episode=True)
        report["time_window"] = window
        if not window["new_episode_allowed"]:
            report.update(status="WAITING_OFFPEAK", infrastructure_status="NOT_DISPATCHED")
        else:
            report["preflight"] = _provider_connectivity_preflight()
            if not report["preflight"]["ok"]:
                report.update(status="PRECHECK_FAILED", infrastructure_status="INVALID_INFRA_PRECHECK")
            else:
                try:
                    DatabaseExplorationAdapter.assert_real_litellm_available()
                except Exception:
                    report.update(status="INVALID_SYSTEM", infrastructure_status="INVALID_SYSTEM")
                else:
                    adapter = build_authorized_client(LiveAuthorization(True, pending["provider"], pending["model"], "USD", Decimal(pending["budget"]["hard_cap_usd"]), pending["budget"]["max_provider_attempts"], pending["budget"]["price_source"], max_episodes=len(items), episode_cap=len(items)), config).adapter
        if report["status"] != "RUNNING":
            report["episodes"] = [{**_empty_episode(item, report["status"]), "manifest_position": item["manifest_position"]} for item in items]
            _write(report, report_path)
            return runner.records.write_json("formal_source_block_run.json", report)
    if adapter is None:
        raise ValueError("fake requires adapter")
    ledger = CostLedger(LiveAuthorization(True, pending["provider"], pending["model"], "USD", Decimal(pending["budget"]["hard_cap_usd"]), pending["budget"]["max_provider_attempts"], pending["budget"]["price_source"], max_episodes=len(items), episode_cap=len(items)))
    upstream = ROOT / "benchmarks/continual-learning-bench"
    for index, item in enumerate(items):
        task = DatabaseExplorationAdapter(upstream_root=upstream, db_path=upstream / "data/database_exploration/products.db", questions_path=upstream / "data/database_exploration/questions.json", records=runner.records, seed=42, max_queries_per_question=15, task_index=item["task_index"], allow_no_model_import_shim=mode == "fake")
        view = task.reset()
        parent = parents[item["id"]]
        prepared = runner.prepare_task(item["condition"], "formal-source-v1", item["id"], parent=parent, task_text=view.prompt)
        query = NativeQueryTool(task)
        def submit(answer: str, _metrics: dict[str, Any]) -> None:
            if answer and not task.completed:
                task.submit_answer(answer)
        try:
            _answer, snapshot, metrics = run_tool_only_episode(prepared=prepared, manager=runner.manager, records=runner.records, database=query, adapter=adapter, ledger=ledger, config=config, prices=prices, transport_kind="fake_transport" if mode == "fake" else "live_provider", allowed_tool_names=ALLOWED_TOOLS, tool_call_limits={"query_sql": 15}, tool_call_group_limits={"file_operations": (FILE_TOOLS, 8)}, pre_request_check=(lambda: _offpeak_status({"offpeak_window": {"timezone": "Asia/Shanghai", "start_local": "18:05:00", "end_local": "08:55:00", "minimum_remaining_seconds_for_new_episode": 1080}})) if mode == "live" else None, stop_on_tool_limit_reached=True, terminal_only_after_tool_limit_names={"query_sql"}, enable_optional_consolidation=True, before_consolidation=submit, consolidation_mode="deterministic_experience_commit_v1", consolidation_artifact_path=item["artifact_path"], raw_source_label=item["id"])
        except Exception as exc:
            events = _events(runner.records.path, prepared.session.attempt_id)
            if mode == "live":
                _consume_after_dispatch(authorization_path, events, runner.run_id, pending["block_id"])
            row = _episode_report(item=item, view=view, prepared=prepared, task=task, query_tool=query, snapshot=None, metrics=None, events=events, native=None, exception_chain={"class": type(exc).__name__, "message": str(exc)})
            row.update(manifest_position=item["manifest_position"], inheritance_source=parent.snapshot_id if parent else None)
            report["episodes"].append(row)
            report["status"] = "INVALID_INFRA" if row["analysis_status"] == "INVALID_INFRA" else "INVALID_SYSTEM"
            report["episodes"] += [{**_empty_episode(rest, report["status"]), "manifest_position": rest["manifest_position"]} for rest in items[index + 1:]]
            break
        events = _events(runner.records.path, prepared.session.attempt_id)
        if mode == "live":
            _consume_after_dispatch(authorization_path, events, runner.run_id, pending["block_id"])
        native = task.evaluate_native() if task.completed else None
        row = _episode_report(item=item, view=view, prepared=prepared, task=task, query_tool=query, snapshot=snapshot, metrics=metrics, events=events, native=native)
        row.update(manifest_position=item["manifest_position"], raw_experience=metrics.get("raw_experience"), input_snapshot_hash=prepared.session.parent_snapshot_id, inheritance_source=parent.snapshot_id if parent else None, contamination_checks={"development_source_mounted": False, "evaluator_reference_visible": False})
        report["episodes"].append(row)
    report["provider_attempts"] = sum(row["provider_attempts"] for row in report["episodes"])
    report["provider_responses"] = sum(row["provider_responses"] for row in report["episodes"])
    report["known_cost_estimate"] = str(ledger.settled)
    report["unknown_billing_attempts"] = sum(row["billing_unknown"] for row in report["episodes"])
    report["status"] = "COMPLETED" if report["status"] == "RUNNING" else report["status"]
    _write(report, report_path)
    return runner.records.write_json("formal_source_block_run.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manifest-driven formal source runner V2")
    parser.add_argument("--pending", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value/formal_source"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--fake", action="store_true")
    mode.add_argument("--live", action="store_true")
    args = parser.parse_args()
    print(execute(pending_path=args.pending, authorization_path=args.authorization, output_root=args.output_root, mode="plan-only" if args.plan_only else "fake" if args.fake else "live"))


if __name__ == "__main__":
    main()
