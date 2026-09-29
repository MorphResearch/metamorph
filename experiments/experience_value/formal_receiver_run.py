"""Sealed-protocol Formal Receiver V1 runner.

This entry has three deliberately separated modes.  ``plan-only`` reads no
public task. ``fake`` accepts only injected synthetic transport/task objects
for offline wiring tests. ``live`` is refused unless a separate future
authorization explicitly enables it.  The entry never modifies a frozen
source, resource, manifest, or addendum.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from llm.adapters import ProviderAdapter

from .clbench_database_exploration import DatabaseExplorationAdapter
from .live import PriceSheet, ToolOnlySmokeConfig, build_authorized_client, run_tool_only_episode, tool_only_schemas
from .public_calibration_run import ALLOWED_TOOLS, FILE_TOOLS
from .public_viability_gate_run import _code_hashes, _events
from .records import AuthorizationError, CostLedger, LiveAuthorization
from .runner import ExperimentRunner
from .workspace import Snapshot, hash_tree

ROOT = Path(__file__).resolve().parents[2]
ADDENDUM = ROOT / "FORMAL_RECEIVER_PROTOCOL_ADDENDUM_V1.json"
ADDENDUM_SEAL = ROOT / "FORMAL_RECEIVER_PROTOCOL_ADDENDUM_V1_SEAL.json"
MANIFEST = ROOT / "FORMAL_RECEIVER_MANIFEST_V1.json"
RESOURCES = ROOT / "artifacts/experience_value/formal_receiver_resources_v1/FORMAL_RECEIVER_RESOURCES_V1.json"
SOURCE_SEAL = ROOT / "artifacts/experience_value/formal_freeze/FORMAL_SOURCE_PHASE_SEAL_V1.json"
PLAN = ROOT / "FORMAL_RECEIVER_EXECUTION_PLAN_V1.json"
BLOCKS = ROOT / "FORMAL_RECEIVER_BLOCKS_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuthorizationError(f"JSON object required: {path}")
    return value


def _resource_tree(path: Path) -> str:
    return hash_tree(path)[0]


def verify_frozen_bindings() -> dict[str, Any]:
    """Check every sealed input before constructing a client or task object."""
    addendum, seal, manifest, resources, source_seal = map(_json, (ADDENDUM, ADDENDUM_SEAL, MANIFEST, RESOURCES, SOURCE_SEAL))
    if canonical({k: v for k, v in addendum.items() if k != "canonical_content_sha256"}) != addendum["canonical_content_sha256"]:
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: addendum canonical hash")
    if addendum["canonical_content_sha256"] != "96b033729af9768b6a5ebe6fe2c2a1436f13270161b8f2370dc2b3a7960c95e7":
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: unexpected addendum identity")
    if canonical({k: v for k, v in seal.items() if k != "canonical_content_sha256"}) != seal.get("canonical_content_sha256"):
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: addendum seal canonical hash")
    if seal.get("canonical_content_sha256") != "7653b1fe3f6719f3524fdcf11b79a31820b94b6f96a0a4bdc81c8aa9f7a87427" or seal.get("addendum_canonical_sha256") != addendum["canonical_content_sha256"]:
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: addendum seal")
    if any(seal.get(field) != expected for field, expected in {"receiver_started": False, "provider_requests": 0, "evaluator_calls": 0, "probe_content_read": False}.items()):
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: addendum pre-execution state")
    for key, ref in addendum["original_bindings"].items():
        path = ROOT / ref["path"]
        actual = canonical({k: v for k, v in _json(path).items() if k != "canonical_content_sha256"}) if "canonical_sha256" in ref else sha(path)
        expected = ref.get("canonical_sha256", ref.get("sha256"))
        if actual != expected:
            raise AuthorizationError(f"FROZEN_BINDING_MISMATCH: {key}")
    for key, ref in addendum["authoritative_source_execution"].items():
        if sha(ROOT / ref["path"]) != ref["sha256"]:
            raise AuthorizationError(f"FROZEN_BINDING_MISMATCH: authoritative {key}")
    if source_seal.get("source_complete") is not True or source_seal.get("source_episode_count") != 32 or source_seal.get("receiver_started") is not False:
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: source phase state")
    if manifest["execution_order"] != [token for block in addendum["operational_blocks"]["blocks"] for token in block["execution_tokens"]]:
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: receiver order")
    for resource_id in ("M_F", "M_U", "RAW_F", "RAW_U"):
        path = ROOT / addendum["receiver_resources"][resource_id]["materialized_path"]
        if path.is_file():
            path = path.parent
        actual = _resource_tree(path)
        if actual != addendum["receiver_resources"][resource_id]["tree_sha256"] or actual != resources["resources"][resource_id]["resource_tree_sha256"]:
            raise AuthorizationError(f"FROZEN_BINDING_MISMATCH: resource {resource_id}")
    for resource_id, filename in (("RAW_F", "raw_f.txt"), ("RAW_U", "raw_u.txt")):
        actual = sha(ROOT / "artifacts/experience_value/formal_receiver_resources_v1" / resource_id / filename)
        if actual != addendum["receiver_resources"][resource_id]["payload_sha256"]:
            raise AuthorizationError(f"FROZEN_BINDING_MISMATCH: {resource_id} payload")
    schemas = tool_only_schemas(ALLOWED_TOOLS)
    schema_hash = canonical(schemas)
    if schema_hash != addendum["tool_interface"]["canonical_serialized_schema_sha256"]:
        raise AuthorizationError("TOOL_SCHEMA_BINDING_MISMATCH")
    return {"addendum": addendum, "manifest": manifest, "resources": resources, "source_seal": source_seal, "tool_schema_hash": schema_hash}


def receiver_config(bindings: dict[str, Any]) -> tuple[ToolOnlySmokeConfig, PriceSheet]:
    addendum = bindings["addendum"]
    b = addendum["common_receiver"]["scalar_budgets"]
    cost = addendum["cost_accounting"]
    config = ToolOnlySmokeConfig(
        provider="deepseek", exact_model_id=b["model"], base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY",
        max_input_characters=0, max_input_tokens_per_request=b["max_input_tokens_per_request"], max_output_tokens_per_request=b["max_output_tokens_per_request"],
        max_requests_per_episode=b["max_main_model_decisions"], max_tool_calls_per_episode=b["max_query_sql"] + b["max_file_operations"], timeout_seconds=b["request_timeout_seconds"], retries=0,
        max_transport_retries=b["max_pre_response_transport_retries"], temperature=None, thinking_enabled=b["thinking_enabled"], reasoning_effort=b["reasoning_effort"],
        episode_timeout_seconds=b["episode_timeout_seconds"], max_file_return_bytes=32768, enforce_utf8_input_reservation=True,
        formal_input_cutoff_estimator=addendum["formal_input_cutoff"]["formal_estimator"]["name"],
    )
    prices = PriceSheet(Decimal(cost["input_cache_miss_usd_per_million"]), Decimal(cost["output_usd_per_million"]), cost["price_source"], cost["price_checked_on"], Decimal(cost["input_cache_hit_usd_per_million"]))
    if config.worst_case_request_cost(prices) != Decimal(cost["per_attempt_worst_case_usd"]):
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: price reservation")
    if config.worst_case_request_cost(prices) * Decimal(48 * 5) != Decimal(cost["five_episode_block_worst_case_usd"]):
        raise AuthorizationError("FROZEN_BINDING_MISMATCH: block reservation")
    return config, prices


def execution_plan(bindings: dict[str, Any]) -> dict[str, Any]:
    manifest, addendum = bindings["manifest"], bindings["addendum"]
    block_by_position = {position: block["block_id"] for block in addendum["operational_blocks"]["blocks"] for position in block["manifest_positions"]}
    episodes = []
    for position, token in enumerate(manifest["execution_order"], 1):
        task, resource = token.removeprefix("t").split("-", 1)
        episodes.append({"receiver_manifest_position": position, "frozen_token": token, "probe_task_id": int(task), "resource_id": resource, "receiver_block_id": block_by_position[position]})
    if len(episodes) != 30 or len({row["frozen_token"] for row in episodes}) != 30:
        raise AuthorizationError("receiver plan is not exactly 30 unique episodes")
    if {row["probe_task_id"] for row in episodes} != set(range(15, 21)) or any(sum(row["probe_task_id"] == task for row in episodes) != 5 for task in range(15, 21)):
        raise AuthorizationError("receiver plan probe coverage differs")
    return {"format": "FORMAL_RECEIVER_EXECUTION_PLAN_V1", "source_manifest_sha256": sha(MANIFEST), "episodes": episodes, "provider_requests": 0, "probe_content_read": False}


def block_definition(bindings: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    blocks = bindings["addendum"]["operational_blocks"]["blocks"]
    planned = {row["receiver_manifest_position"]: row["frozen_token"] for row in plan["episodes"]}
    for block in blocks:
        if [planned[position] for position in block["manifest_positions"]] != block["execution_tokens"] or block["episode_count"] != 5:
            raise AuthorizationError("receiver operational block differs from sealed addendum")
    return {"format": "FORMAL_RECEIVER_BLOCKS_V1", "addendum_canonical_sha256": bindings["addendum"]["canonical_content_sha256"], "blocks": blocks}


def write_plan_and_blocks(bindings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = execution_plan(bindings)
    blocks = block_definition(bindings, plan)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    BLOCKS.write_text(json.dumps(blocks, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan, blocks


def _source_snapshot(resource_id: str, runner: ExperimentRunner, bindings: dict[str, Any]) -> Snapshot:
    if resource_id == "EMPTY":
        empty = runner.root / "sealed_empty_resource"
        empty.mkdir(exist_ok=False)
        digest, files = hash_tree(empty)
        if files:
            raise AuthorizationError("EMPTY must have zero files")
        return Snapshot("sealed-empty", empty, digest, None, None, files)
    configured = ROOT / bindings["addendum"]["receiver_resources"][resource_id]["materialized_path"]
    path = configured.parent if configured.is_file() else configured
    digest, files = hash_tree(path)
    expected = bindings["addendum"]["receiver_resources"][resource_id]["tree_sha256"]
    if digest != expected:
        raise AuthorizationError(f"FROZEN_BINDING_MISMATCH: resource {resource_id} before clone")
    return Snapshot(f"sealed-{resource_id.lower()}", path, digest, None, None, files)


def _resource_evidence(events: list[dict[str, Any]], resource_id: str, session: Any) -> dict[str, Any]:
    resource_paths = {f"/memory/{name}" for name in session.immutable_memory_files}
    proposed = [event for event in events if event["type"] == "tool.proposed"]
    dispatched = [event for event in events if event["type"] == "tool.completed"]
    reads = [event for event in dispatched if event.get("tool") == "read_file" and event.get("arguments", {}).get("path") in resource_paths]
    return {
        "resource_present": resource_id != "EMPTY", "resource_file_count": len(session.immutable_memory_files),
        "resource_bytes": sum((session.memory_root / name).stat().st_size for name in session.immutable_memory_files),
        "list_dir_proposed": sum(event.get("tool") == "list_dir" for event in proposed), "list_dir_dispatched": sum(event.get("tool") == "list_dir" for event in dispatched),
        "read_file_proposed": sum(event.get("tool") == "read_file" for event in proposed), "read_file_dispatched": sum(event.get("tool") == "read_file" for event in dispatched),
        "write_file_proposed": sum(event.get("tool") == "write_file" for event in proposed), "write_file_dispatched": sum(event.get("tool") == "write_file" for event in dispatched),
        "files_read": [event["arguments"]["path"] for event in reads], "read_byte_counts": [len(str(event.get("result", {}).get("output", "")).encode("utf-8")) for event in reads],
        "resource_content_entered_model_context": bool(reads), "resource_used": bool(reads),
    }


def _native_summary(result: Any) -> tuple[bool | None, Any]:
    metrics = getattr(result, "metrics", {}) or {}
    return metrics.get("correct", metrics.get("accuracy")), getattr(result, "score", metrics.get("score"))


def execute_block(*, bindings: dict[str, Any], block_id: str, output_root: Path, mode: str, adapter: ProviderAdapter | None = None, task_factory: Callable[[int, Any], Any] | None = None) -> Path:
    """Run one block only; caller chooses synthetic fake or separately authorized live."""
    plan, blocks = execution_plan(bindings), block_definition(bindings, execution_plan(bindings))
    block = next((b for b in blocks["blocks"] if b["block_id"] == block_id), None)
    if block is None or mode not in {"fake", "live", "plan-only"}:
        raise ValueError("unknown block or mode")
    items = [row for row in plan["episodes"] if row["receiver_block_id"] == block_id]
    if mode == "plan-only":
        out = Path(output_root) / "formal_receiver_plan_only.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"provider_requests": 0, "episodes": items}, indent=2) + "\n", encoding="utf-8")
        return out
    if mode == "live":
        raise AuthorizationError("unsigned live receiver execution is forbidden before provider setup")
    if adapter is None or task_factory is None:
        raise AuthorizationError("fake mode requires injected synthetic adapter and task factory")
    config, prices = receiver_config(bindings)
    runner = ExperimentRunner(output_root, receiver_config=bindings["addendum"]["common_receiver"])
    report: dict[str, Any] = {"status": "RUNNING", "mode": "offline_fake", "block_id": block_id, "episodes": [], "formal_provider_requests": 0, "formal_native_evaluator_calls": 0, "synthetic_evaluator_invocations": 0, "next_block": "NOT_STARTED", "probe_content_read": False}
    for row in items:
        resource_id = row["resource_id"]
        source = _source_snapshot(resource_id, runner, bindings)
        source_before = _resource_tree(source.path)
        task = task_factory(row["probe_task_id"], runner.records)
        # In fake mode task text is synthetic and never asks a public adapter to reset.
        prepared = runner.prepare_receiver_task(str(row["probe_task_id"]), task.synthetic_prompt, source)
        clone_pre_hash = hash_tree(prepared.session.memory_root)[0]
        authorization = LiveAuthorization(True, "synthetic-offline", config.exact_model_id, "USD", Decimal("8.00"), 48, "synthetic test only", max_episodes=5, episode_cap=5)
        ledger = CostLedger(authorization)
        accepted = {"value": False}
        def submit(answer: str, _metrics: dict[str, Any]) -> None:
            if answer and not accepted["value"]:
                task.submit_answer(answer)
                accepted["value"] = True
        answer, snapshot, metrics = run_tool_only_episode(
            prepared=prepared, manager=runner.manager, records=runner.records, database=task, adapter=adapter, ledger=ledger, config=config, prices=prices,
            transport_kind="synthetic_offline", allowed_tool_names=set(ALLOWED_TOOLS), tool_call_limits={"query_sql": 15},
            tool_call_group_limits={"file_operations": (set(FILE_TOOLS), 8)}, stop_on_tool_limit_reached=True, terminal_only_after_tool_limit_names={"query_sql"},
            enable_optional_consolidation=False, before_consolidation=submit,
        )
        correct = score = None
        if accepted["value"]:
            correct, score = _native_summary(task.evaluate_native())
            report["synthetic_evaluator_invocations"] += 1
        events = _events(runner.records.path, prepared.session.attempt_id)
        source_after = _resource_tree(source.path)
        evidence = _resource_evidence(events, resource_id, prepared.session)
        report["episodes"].append({
            **row, "episode_id": prepared.session.attempt_id, "run_id": runner.run_id, "resource_source_hash": source.content_hash,
            "clone_pre_run_hash": clone_pre_hash, "clone_post_run_hash": snapshot.content_hash, "clone_equality_on_start": clone_pre_hash == source.content_hash,
            "sealed_resource_unchanged": source_before == source_after, "native_answer_submitted": accepted["value"], "correct": correct, "native_accuracy": correct, "native_score": score,
            "analysis_status": "EVALUATED_NATIVE" if accepted["value"] else "RESOURCE_LIMITED_FAILURE", "main_stop_reason": metrics.get("runner_stop_reason"),
            "sql_queries": metrics.get("tool_calls_by_name", {}).get("query_sql", 0), "file_operations": sum(metrics.get("tool_calls_by_name", {}).get(name, 0) for name in FILE_TOOLS),
            "model_decisions": metrics.get("llm_calls"), "provider_attempts": len(ledger.entries), "provider_responses": metrics.get("llm_calls"), "billing_unknown": ledger.billing_unknown,
            "evaluator_ran": accepted["value"], "evaluator_reference_visible": False, "post_evaluation_model_calls": 0, "consolidation": False, "resource_use": evidence,
        })
    report["status"] = "COMPLETED_OFFLINE_FAKE" if len(report["episodes"]) == 5 else "INVALID_SYSTEM"
    report["synthetic_transport_requests"] = len(getattr(adapter, "requests", []))
    path = runner.records.write_json("formal_receiver_block_report.json", report)
    return path


def pending_payloads(bindings: dict[str, Any], plan: dict[str, Any], blocks: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    r1 = blocks["blocks"][0]
    references = {
        "formal_protocol": bindings["addendum"]["original_bindings"]["formal_protocol"], "receiver_manifest": bindings["addendum"]["original_bindings"]["receiver_manifest"],
        "analysis_plan": bindings["addendum"]["original_bindings"]["analysis_plan"], "source_seal": bindings["addendum"]["original_bindings"]["source_phase_seal"],
        "resource_manifest": bindings["addendum"]["original_bindings"]["receiver_resource_manifest"],
        "addendum": {"path": ADDENDUM.name, "sha256": sha(ADDENDUM)}, "addendum_seal": {"path": ADDENDUM_SEAL.name, "sha256": sha(ADDENDUM_SEAL)},
        "execution_plan": {"path": PLAN.name, "sha256": sha(PLAN)}, "block_definition": {"path": BLOCKS.name, "sha256": sha(BLOCKS)},
    }
    dependencies = _code_hashes()
    dependencies.pop("entry", None)
    dependencies["receiver_runner"] = sha(Path(__file__))
    shared = bindings["addendum"]["authoritative_source_execution"]
    payload = {"status": "PENDING_FORMAL_RECEIVER_BLOCK_R1_USER_SIGNOFF_NO_LIVE_CALLS", "study_kind": "formal_receiver_v1", "live_requests_authorized": False, "block_id": r1["block_id"], "allowed_manifest_positions": r1["manifest_positions"], "allowed_tokens": r1["execution_tokens"], "hard_cap_usd": "8.00", "bindings": references, "entry_code": {"path": "experiments/experience_value/formal_receiver_run.py", "sha256": sha(Path(__file__))}, "code_dependencies": dependencies, "shared_runtime_bindings": {"tool_schema_canonical_sha256": bindings["tool_schema_hash"], "shared_loop": shared["shared_terminal_loop"], "provider_estimator_pricing": shared["shared_live_bridge"], "native_evaluator": shared["public_database_adapter"], "workspace": shared["workspace_policy"]}, "provider_requests": 0, "evaluator_calls": 0, "probe_content_read": False}
    auth = {"status": "PENDING_NO_LIVE_AUTHORIZATION", "study_kind": "formal_receiver_v1", "live_requests_authorized": False, "block_id": r1["block_id"], "allowed_tokens": r1["execution_tokens"], "hard_cap_usd": "8.00", "pending_sha256": None, "provider_requests": 0, "evaluator_calls": 0, "probe_content_read": False}
    return payload, auth


def write_pending(bindings: dict[str, Any], plan: dict[str, Any], blocks: dict[str, Any]) -> tuple[Path, Path]:
    pending, auth = pending_payloads(bindings, plan, blocks)
    base = ROOT / "experiments/experience_value"
    pending_path, auth_path = base / "formal_receiver_block_01.pending.json", base / "formal_receiver_block_01.authorization.pending.json"
    pending_path.write_text(json.dumps(pending, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    auth["pending_sha256"] = sha(pending_path)
    auth_path.write_text(json.dumps(auth, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pending_path, auth_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Formal Receiver V1; default is non-live planning only")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if not args.plan_only:
        parser.error("only --plan-only is available without a separate future authorization")
    bindings = verify_frozen_bindings()
    write_plan_and_blocks(bindings)
    print("provider_requests=0; probe_content_read=false")


if __name__ == "__main__":
    main()
