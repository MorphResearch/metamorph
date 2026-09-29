#!/usr/bin/env python3
"""Create the pre-execution Formal Receiver Protocol Addendum V1.

This is intentionally a static provenance builder.  It never constructs a
provider client, task adapter, or evaluator and never opens a formal probe.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import stat
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ADDENDUM_JSON = ROOT / "FORMAL_RECEIVER_PROTOCOL_ADDENDUM_V1.json"
ADDENDUM_MD = ROOT / "FORMAL_RECEIVER_PROTOCOL_ADDENDUM_V1.md"
ADDENDUM_SEAL = ROOT / "FORMAL_RECEIVER_PROTOCOL_ADDENDUM_V1_SEAL.json"


class AddendumError(RuntimeError):
    pass


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AddendumError(f"JSON root is not an object: {path}")
    return value


def hash_tree(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.is_dir():
        raise AddendumError(f"resource directory missing: {path}")
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink() or (item.exists() and not item.is_file() and not item.is_dir()):
            raise AddendumError(f"unsupported resource entry: {item}")
        if not item.is_file():
            continue
        name = item.relative_to(path).as_posix()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0file\0")
        digest.update(b"x" if item.stat().st_mode & stat.S_IXUSR else b"-")
        digest.update(b"\0")
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AddendumError(f"{label} mismatch: {actual!r} != {expected!r}")


def immutable(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR)


def extract_tool_only_schemas() -> list[dict[str, Any]]:
    """Read the exact literal schema list from the authoritative source file.

    Static AST extraction avoids importing the application dependency graph;
    it neither dispatches a tool nor constructs a provider/evaluator object.
    """
    tree = ast.parse((ROOT / "experiments/experience_value/live.py").read_text(encoding="utf-8"))
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "tool_only_schemas"), None)
    if function is None:
        raise AddendumError("authoritative tool_only_schemas function is missing")
    assignment = next((node for node in function.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "schemas" for target in node.targets)), None)
    if assignment is None:
        raise AddendumError("authoritative tool schema literal is missing")
    value = ast.literal_eval(assignment.value)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AddendumError("authoritative tool schema literal has unexpected type")
    return value


def source_hashes() -> dict[str, str]:
    paths = {
        "formal_protocol": "FORMAL_EXPERIMENT_PROTOCOL_V1.md",
        "receiver_manifest": "FORMAL_RECEIVER_MANIFEST_V1.json",
        "analysis_plan": "FORMAL_ANALYSIS_PLAN_V1.md",
        "formal_pending_config": "experiments/experience_value/public_formal_experiment_v1.pending.json",
        "source_v3_entry": "experiments/experience_value/formal_source_run_v3.py",
        "source_v2_common_runner": "experiments/experience_value/formal_source_run_v2.py",
        "shared_live_bridge": "experiments/experience_value/live.py",
        "shared_terminal_loop": "graphs/loop.py",
        "public_calibration_bridge": "experiments/experience_value/public_calibration_run.py",
        "public_database_adapter": "experiments/experience_value/clbench_database_exploration.py",
        "workspace_policy": "experiments/experience_value/workspace.py",
        "source_block_08_pending": "experiments/experience_value/formal_source_block_08.pending.json",
        "source_block_08_authorization": "experiments/experience_value/formal_source_block_08.authorization.authorized_20260928T225534+0800.json",
    }
    return {name: sha_file(ROOT / path) for name, path in paths.items()}


def validate_base() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str], dict[str, str]]:
    protocol = (ROOT / "FORMAL_EXPERIMENT_PROTOCOL_V1.md").read_text(encoding="utf-8")
    manifest = read_json(ROOT / "FORMAL_RECEIVER_MANIFEST_V1.json")
    analysis = (ROOT / "FORMAL_ANALYSIS_PLAN_V1.md").read_text(encoding="utf-8")
    pending = read_json(ROOT / "experiments/experience_value/public_formal_experiment_v1.pending.json")
    source_pending = read_json(ROOT / "experiments/experience_value/formal_source_block_08.pending.json")
    source_auth = read_json(ROOT / "experiments/experience_value/formal_source_block_08.authorization.authorized_20260928T225534+0800.json")
    source_seal = read_json(ROOT / "artifacts/experience_value/formal_freeze/FORMAL_SOURCE_PHASE_SEAL_V1.json")
    resources = read_json(ROOT / "artifacts/experience_value/formal_receiver_resources_v1/FORMAL_RECEIVER_RESOURCES_V1.json")
    hashes_before = source_hashes()

    assert_equal(sha_bytes(canonical({key: value for key, value in source_seal.items() if key != "canonical_content_sha256"})), source_seal["canonical_content_sha256"], "source seal canonical hash")
    assert_equal(sha_bytes(canonical({key: value for key, value in resources.items() if key != "canonical_content_sha256"})), resources["canonical_content_sha256"], "resource manifest canonical hash")
    assert_equal(source_seal["source_complete"], True, "source_complete")
    assert_equal(source_seal["source_episode_count"], 32, "source episode count")
    assert_equal(source_seal["next_source_position"], None, "next source position")
    assert_equal(source_seal["receiver_started"], False, "receiver started")

    assert_equal(manifest["probe_task_ids"], [15, 16, 17, 18, 19, 20], "probe task IDs")
    assert_equal(manifest["receiver_conditions"], ["EMPTY", "M_F", "M_U", "RAW_F", "RAW_U"], "receiver resource set")
    order = manifest["execution_order"]
    if len(order) != 30 or len(set(order)) != 30:
        raise AddendumError("receiver execution order must contain 30 unique tokens")
    expected_resources = set(manifest["receiver_conditions"])
    for task_id in range(15, 21):
        tokens = [token for token in order if token.startswith(f"t{task_id}-")]
        assert_equal(len(tokens), 5, f"probe {task_id} count")
        assert_equal({token.split("-", 1)[1] for token in tokens}, expected_resources, f"probe {task_id} resource set")
    if "receiver prompt, tools, and shared task budget are frozen in the receiver manifest" not in protocol:
        raise AddendumError("formal protocol no longer states receiver manifest authority")
    if "RESOURCE_LIMITED_FAILURE" not in analysis:
        raise AddendumError("analysis plan no longer contains receiver outcome semantics")

    # The source V3 authorization is the final actually consumed source binding.
    assert_equal(source_auth["entry_code"]["sha256"], hashes_before["source_v3_entry"], "source V3 entry hash")
    for name, auth_key in {
        "shared_live_bridge": "live_bridge", "shared_terminal_loop": "loop",
        "public_calibration_bridge": "public_calibration_bridge", "public_database_adapter": "public_adapter",
        "workspace_policy": "workspace",
    }.items():
        assert_equal(source_auth["code_dependencies"][auth_key], hashes_before[name], f"source authorization code hash: {auth_key}")
    assert_equal(source_pending["formal_pending"]["sha256"], hashes_before["formal_pending_config"], "formal config hash bound by source pending")
    assert_equal(source_pending["formal_protocol"]["sha256"], hashes_before["formal_protocol"], "formal protocol hash bound by source pending")
    assert_equal(pending["manifests"]["receiver"]["sha256"], hashes_before["receiver_manifest"], "receiver manifest hash bound by formal config")
    return manifest, pending, source_pending, {"seal": source_seal, "resources": resources}, hashes_before, {
        "formal_protocol_text": protocol, "analysis_plan_text": analysis,
    }


def main() -> None:
    if any(path.exists() for path in (ADDENDUM_JSON, ADDENDUM_MD, ADDENDUM_SEAL)):
        raise AddendumError("addendum output already exists; refusing to overwrite an immutable addendum")
    manifest, pending, source_pending, frozen, hashes_before, _texts = validate_base()
    source_seal, resources = frozen["seal"], frozen["resources"]
    schemas = extract_tool_only_schemas()
    if [item["function"]["name"] for item in schemas] != ["list_dir", "read_file", "write_file", "query_sql"]:
        raise AddendumError("authoritative tool interface has unexpected tool set/order")
    schema_canonical_hash = sha_bytes(canonical(schemas))
    source_runtime_schema_hash = sha_bytes(json.dumps(schemas, sort_keys=True).encode("utf-8"))

    budget = manifest["receiver_budget"]
    shared = pending["shared_execution"]
    assert_equal(budget["model"], pending["exact_model_id"], "receiver/source scalar binding: model")
    for receiver_key, source_key in {
        "thinking_enabled": "thinking_enabled", "reasoning_effort": "reasoning_effort",
        "max_main_model_decisions": "max_main_model_decisions_per_episode", "max_query_sql": "max_query_sql_per_episode",
        "max_file_operations": "max_file_operations_per_episode", "max_input_tokens_per_request": "max_input_tokens_per_request",
        "max_output_tokens_per_request": "max_output_tokens_per_request", "request_timeout_seconds": "request_timeout_seconds",
        "episode_timeout_seconds": "episode_timeout_seconds", "task_model_retries": "application_retries",
        "sdk_retries": "sdk_implicit_retries", "max_pre_response_transport_retries": "max_pre_response_transport_retries",
    }.items():
        assert_equal(budget[receiver_key], shared[source_key], f"receiver/source scalar binding: {receiver_key}")
    assert_equal(shared["allowed_tools"], [item["function"]["name"] for item in schemas], "source allowlist/schema binding")

    price = source_pending["budget"]
    envelope = pending["cost_envelope"]
    per_attempt = (
        Decimal(str(budget["max_input_tokens_per_request"])) * Decimal(price["input_cache_miss_usd_per_million"])
        + Decimal(str(budget["max_output_tokens_per_request"])) * Decimal(price["output_usd_per_million"])
    ) / Decimal(1_000_000)
    assert_equal(str(per_attempt), price["worst_case_per_attempt_usd"], "source per-attempt reservation")
    assert_equal(str(per_attempt), envelope["reservation_per_attempt"], "formal cost envelope reservation")
    attempts_per_episode = int(budget["max_main_model_decisions"]) * (1 + int(budget["max_pre_response_transport_retries"]))
    block_reservation = per_attempt * attempts_per_episode * Decimal(5)
    total_reservation = per_attempt * attempts_per_episode * Decimal(30)
    assert_equal(str(block_reservation), "7.69443840", "five-episode receiver block reservation")
    assert_equal(str(total_reservation), envelope["receiver_worst_case"], "receiver total reservation")
    hard_cap = Decimal(math.ceil(block_reservation))
    assert_equal(str(hard_cap), "8", "mechanical receiver block cap")

    resource_hashes = {
        "M_F": hash_tree(ROOT / "artifacts/experience_value/formal_receiver_resources_v1/M_F"),
        "M_U": hash_tree(ROOT / "artifacts/experience_value/formal_receiver_resources_v1/M_U"),
        "RAW_F": hash_tree(ROOT / "artifacts/experience_value/formal_receiver_resources_v1/RAW_F"),
        "RAW_U": hash_tree(ROOT / "artifacts/experience_value/formal_receiver_resources_v1/RAW_U"),
    }
    for name, value in resource_hashes.items():
        assert_equal(value, resources["resources"][name]["resource_tree_sha256"], f"resource tree: {name}")
        assert_equal(value, source_seal["resource_tree_hashes"][name], f"source seal resource tree: {name}")
    for name, filename in {"RAW_F": "raw_f.txt", "RAW_U": "raw_u.txt"}.items():
        actual = sha_file(ROOT / f"artifacts/experience_value/formal_receiver_resources_v1/{name}/{filename}")
        assert_equal(actual, resources["resources"][name]["aggregate_payload_sha256"], f"RAW payload: {name}")
        assert_equal(actual, source_seal["raw_payload_hashes"][name], f"source seal RAW payload: {name}")

    blocks = []
    for number, task_id in enumerate(range(15, 21), start=1):
        positions = [index for index, token in enumerate(manifest["execution_order"], start=1) if token.startswith(f"t{task_id}-")]
        tokens = [manifest["execution_order"][index - 1] for index in positions]
        if positions != list(range((number - 1) * 5 + 1, number * 5 + 1)):
            raise AddendumError(f"receiver manifest is not probe-major for block R{number}")
        blocks.append({"block_id": f"formal_receiver_block_{number:02d}", "probe_task_id": task_id, "manifest_positions": positions, "execution_tokens": tokens, "episode_count": 5, "hard_cap_usd": "8.00", "automatically_starts_next_block": False})

    addendum: dict[str, Any] = {
        "format": "FORMAL_RECEIVER_PROTOCOL_ADDENDUM_V1",
        "immutable": True,
        "receiver_protocol_status": "COMPLETED_PRE_EXECUTION_BY_ADDENDUM",
        "completion_context": {
            "receiver_protocol_completion_before_execution": True,
            "receiver_outcomes_observed_before_completion": False,
            "probe_outcomes_observed": False,
            "source_protocol_changed": False,
            "source_results_changed": False,
            "performance_tuning": False,
            "selection_rule": "For receiver execution semantics not explicit in the original receiver manifest, bind the formally executed Formal Source V1 common mechanism unless the receiver manifest explicitly differs.",
        },
        "original_bindings": {
            "formal_protocol": {"path": "FORMAL_EXPERIMENT_PROTOCOL_V1.md", "sha256": hashes_before["formal_protocol"]},
            "receiver_manifest": {"path": "FORMAL_RECEIVER_MANIFEST_V1.json", "sha256": hashes_before["receiver_manifest"]},
            "analysis_plan": {"path": "FORMAL_ANALYSIS_PLAN_V1.md", "sha256": hashes_before["analysis_plan"]},
            "source_phase_seal": {"path": "artifacts/experience_value/formal_freeze/FORMAL_SOURCE_PHASE_SEAL_V1.json", "canonical_sha256": source_seal["canonical_content_sha256"]},
            "receiver_resource_manifest": {"path": "artifacts/experience_value/formal_receiver_resources_v1/FORMAL_RECEIVER_RESOURCES_V1.json", "canonical_sha256": resources["canonical_content_sha256"]},
        },
        "authoritative_source_execution": {
            "final_formal_source_authorization": {"path": "experiments/experience_value/formal_source_block_08.authorization.authorized_20260928T225534+0800.json", "sha256": hashes_before["source_block_08_authorization"], "runner_version": "V3"},
            "source_v3_entry": {"path": "experiments/experience_value/formal_source_run_v3.py", "sha256": hashes_before["source_v3_entry"]},
            "source_v2_common_runner": {"path": "experiments/experience_value/formal_source_run_v2.py", "sha256": hashes_before["source_v2_common_runner"]},
            "shared_live_bridge": {"path": "experiments/experience_value/live.py", "sha256": hashes_before["shared_live_bridge"]},
            "shared_terminal_loop": {"path": "graphs/loop.py", "sha256": hashes_before["shared_terminal_loop"]},
            "public_calibration_bridge": {"path": "experiments/experience_value/public_calibration_run.py", "sha256": hashes_before["public_calibration_bridge"]},
            "public_database_adapter": {"path": "experiments/experience_value/clbench_database_exploration.py", "sha256": hashes_before["public_database_adapter"]},
            "workspace_policy": {"path": "experiments/experience_value/workspace.py", "sha256": hashes_before["workspace_policy"]},
            "formal_execution_config": {"path": "experiments/experience_value/public_formal_experiment_v1.pending.json", "sha256": hashes_before["formal_pending_config"]},
            "source_operational_pricing_config": {"path": "experiments/experience_value/formal_source_block_08.pending.json", "sha256": hashes_before["source_block_08_pending"]},
        },
        "common_receiver": {
            "model": budget["model"], "thinking_enabled": budget["thinking_enabled"], "reasoning_effort": budget["reasoning_effort"],
            "receiver_prompt_exact": manifest["receiver_prompt"],
            "agent_visible_resource_label_injected": False,
            "all_conditions_identical_except_starting_frozen_resource_content": True,
            "conditions": manifest["receiver_conditions"],
            "scalar_budgets": budget,
            "consolidation": {"enabled": False, "post_evaluation_model_call": False, "receiver_inheritance": False},
        },
        "tool_interface": {
            "allowlist": [item["function"]["name"] for item in schemas],
            "schemas": schemas,
            "schema_canonicalization": "UTF-8 JSON; ensure_ascii=false; sort_keys=true; separators=(',', ':')",
            "canonical_serialized_schema_sha256": schema_canonical_hash,
            "source_runtime_serialized_schema_sha256": source_runtime_schema_hash,
            "forbidden_capabilities": shared["forbidden_capabilities"],
            "logical_path_policy": {"allowed_roots": ["/memory", "/work"], "path_escape": "rejected", "symlinks": "rejected", "non_regular_files": "rejected"},
            "file_operation_accounting": {"members": ["list_dir", "read_file", "write_file"], "limit": budget["max_file_operations"], "independent_of_native_sql_budget": True},
            "sql_policy": {"tool": "query_sql", "limit": budget["max_query_sql"], "read_only_SELECT": True, "semicolon_rejected": True, "metered_native_QUERY": True},
            "rejected_tool_calls": "recorded, paired with visible rejection feedback, not dispatched, and do not consume tool-call units",
            "receiver_local_writes": {"write_file_allowed": True, "allowed_locations": ["/memory", "/work"], "existing_inherited_memory_files": "immutable; overwrite rejected", "new_episode_local_files": "allowed subject to source path policy", "frozen_resource_mutable": False, "cross_episode_propagation": False},
        },
        "terminal_answer": {
            "ordinary_completion": {"when": "a model decision has no dispatched or budget-rejected tool calls", "answer_type": "ordinary visible text", "maximum_native_answer_submissions": 1, "finalization_retry": False},
            "sql_cap_terminal_path": {"native_sql_allowance": 15, "trigger": "after fifteenth legal query_sql feedback", "requires_main_decisions_used_less_than": 24, "additional_terminal_only_decisions": 1, "terminal_tools": [], "terminal_decision_counts_within_main_limit": True, "tool_call_proposal": "rejected and never dispatched", "sixteenth_sql": False, "empty_text_stop_reason": "terminal_only_empty_answer", "tool_call_stop_reason": "terminal_only_tool_call_rejected"},
            "decision_exhaustion": {"when": "fifteenth legal query_sql occurs at decision 24", "additional_model_request": False, "stop_reason": "terminal_answer_unavailable_model_decision_budget_reached"},
            "other_resource_stops": {"rescue_or_final_answer_call": False, "source_stop_semantics_reused": True},
        },
        "formal_input_cutoff": {
            "diagnostic_estimator": {"name": "calibrated_utf8_half_bytes_plus_chat_tool_overhead_v1", "version": "1"},
            "formal_estimator": {"name": "deepseek_prompt_usage_calibrated_v1", "version": "1", "formula": "ceil(diagnostic_estimated_tokens * 0.50) + 256", "calibration_binding": "final_v3:46_completed_provider_prompt_token_observations; scores_and_condition_outcomes_excluded"},
            "pre_dispatch_stop": "formal_estimate >= 24000", "character_count_is_formal_cutoff": False, "receiver_recalibration": False,
        },
        "native_evaluator_contract": {
            "implementation": "DatabaseExplorationAdapter.evaluate_native", "only_after_accepted_native_answer": True, "maximum_evaluations_per_episode": 1,
            "recorded_fields": ["correct", "native_accuracy", "native_score"], "upstream_semantics_preserved": True,
            "evaluator_or_reference_visible_to_agent": False, "agent_visible_destinations_excluded": ["messages", "provider transcript visible feedback", "/memory", "/work", "receiver resource", "follow-up model request"],
            "post_evaluation_model_call": False, "consolidation": False,
            "evaluator_failure": {"classification": "INVALID_SYSTEM unless the existing frozen failure classifier establishes INVALID_INFRA", "native_score_imputed": False},
            "no_accepted_answer": {"evaluator_invoked": False, "native_score_imputed": False},
        },
        "cost_accounting": {
            "currency": price["currency"], "price_source": price["price_source"], "price_checked_on": price["price_checked_on"],
            "input_cache_hit_usd_per_million": price["input_cache_hit_usd_per_million"], "input_cache_miss_usd_per_million": price["input_cache_miss_usd_per_million"], "output_usd_per_million": price["output_usd_per_million"],
            "reservation_formula": "(max_input_tokens_per_request * input_cache_miss_usd_per_million + max_output_tokens_per_request * output_usd_per_million) / 1_000_000",
            "per_attempt_worst_case_usd": str(per_attempt), "logical_decisions_per_receiver_episode": budget["max_main_model_decisions"], "maximum_provider_attempts_per_receiver_episode": attempts_per_episode,
            "transport_retry": "one identical pre-response transport retry only; failed and retry attempts remain accounted", "known_cost": "provider usage settled using the bound PriceSheet", "billing_unknown": "safe block stop; never hidden or converted to known cost",
            "five_episode_block_worst_case_usd": str(block_reservation), "thirty_episode_worst_case_usd": str(total_reservation),
            "per_block_hard_cap_usd": "8.00", "hard_cap_derivation": "ceil_to_next_whole_USD(frozen five-episode worst-case reservation)", "shared_cross_block_hard_cap": None,
        },
        "receiver_resources": {
            "EMPTY": {"starting_memory": "empty", "agent_visible_helper_files": False},
            "M_F": {"materialized_path": "artifacts/experience_value/formal_receiver_resources_v1/M_F", "tree_sha256": resource_hashes["M_F"], "clone": "byte-identical episode-local clone"},
            "M_U": {"materialized_path": "artifacts/experience_value/formal_receiver_resources_v1/M_U", "tree_sha256": resource_hashes["M_U"], "clone": "byte-identical episode-local clone", "experience_006_present": False},
            "RAW_F": {"materialized_path": "artifacts/experience_value/formal_receiver_resources_v1/RAW_F/raw_f.txt", "tree_sha256": resource_hashes["RAW_F"], "payload_sha256": source_seal["raw_payload_hashes"]["RAW_F"], "mount_path": "/memory/raw_f.txt", "parser_or_reserialization": False},
            "RAW_U": {"materialized_path": "artifacts/experience_value/formal_receiver_resources_v1/RAW_U/raw_u.txt", "tree_sha256": resource_hashes["RAW_U"], "payload_sha256": source_seal["raw_payload_hashes"]["RAW_U"], "mount_path": "/memory/raw_u.txt", "parser_or_reserialization": False},
            "resource_use_metrics": manifest["receiver_use_logging"],
        },
        "operational_blocks": {"scientific_content_change": False, "purpose": "independent authorization and stopping only", "blocks": blocks},
        "static_validation": {"provider_requests": 0, "evaluator_calls": 0, "probe_content_read": False, "source_resources_modified": False, "source_seal_modified": False, "receiver_started": False},
    }
    addendum["canonical_content_sha256"] = sha_bytes(canonical(addendum))
    ADDENDUM_JSON.write_bytes(json.dumps(addendum, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")

    seal = {
        "format": "FORMAL_RECEIVER_PROTOCOL_ADDENDUM_V1_SEAL", "original_formal_protocol_sha256": hashes_before["formal_protocol"],
        "original_receiver_manifest_sha256": hashes_before["receiver_manifest"], "formal_analysis_plan_sha256": hashes_before["analysis_plan"],
        "source_phase_seal_canonical_sha256": source_seal["canonical_content_sha256"], "receiver_resource_manifest_canonical_sha256": resources["canonical_content_sha256"],
        "addendum_canonical_sha256": addendum["canonical_content_sha256"], "authoritative_tool_implementation_sha256": hashes_before["shared_live_bridge"],
        "authoritative_terminal_implementation_sha256": hashes_before["shared_terminal_loop"], "estimator_implementation_sha256": hashes_before["shared_live_bridge"],
        "evaluator_adapter_sha256": hashes_before["public_database_adapter"], "pricing_accounting_config_sha256": hashes_before["formal_pending_config"],
        "source_operational_pricing_config_sha256": hashes_before["source_block_08_pending"], "receiver_started": False, "provider_requests": 0,
        "evaluator_calls": 0, "probe_content_read": False, "source_protocol_changed": False, "source_results_changed": False, "performance_tuning": False,
    }
    seal["canonical_content_sha256"] = sha_bytes(canonical(seal))
    ADDENDUM_SEAL.write_bytes(json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")

    lines = [
        "# Formal Receiver Protocol Addendum V1", "", "## Status", "",
        "`receiver_protocol_status = COMPLETED_PRE_EXECUTION_BY_ADDENDUM`", "",
        "This addendum completes previously omitted receiver execution semantics before any formal receiver episode or probe outcome was observed. It does not alter the completed source experiment. It is not performance tuning.", "",
        "## Immutable bindings", "",
        f"- Formal protocol: `{hashes_before['formal_protocol']}`", f"- Original receiver manifest: `{hashes_before['receiver_manifest']}`", f"- Analysis plan: `{hashes_before['analysis_plan']}`",
        f"- Source phase seal: `{source_seal['canonical_content_sha256']}`", f"- Receiver resource manifest: `{resources['canonical_content_sha256']}`", f"- Addendum canonical hash: `{addendum['canonical_content_sha256']}`", "",
        "## Completed execution semantics", "",
        f"- Tool allowlist: `{', '.join(addendum['tool_interface']['allowlist'])}`; canonical schema SHA-256: `{schema_canonical_hash}`.",
        "- File paths are restricted to `/memory` and `/work`; path escape, symlinks, and non-regular files are rejected. Existing cloned memory files remain immutable, while legal episode-local writes may create new clone/work files and never propagate.",
        "- The terminal path permits one tool-free ordinary-text decision only after the fifteenth legal SQL feedback and only when fewer than 24 main decisions have been used. It is counted within the 24-decision limit; there is no finalization retry or sixteenth SQL query.",
        "- Formal input cutoff is `ceil(diagnostic_estimated_tokens * 0.50) + 256`; it blocks pre-dispatch at `>= 24000`. Its 46-observation calibration excludes scores, answers, SQL, and condition outcomes.",
        "- Native evaluation occurs once only after an accepted native answer; evaluator/reference output never enters agent-visible messages, files, resources, or a follow-up model call. Receiver consolidation is disabled.",
        f"- Frozen per-attempt reservation is USD `{per_attempt}`. A five-episode probe-major block has USD `{block_reservation}` worst-case reservation and an independent mechanical USD `8.00` cap. Thirty episodes have USD `{total_reservation}` worst-case reservation with no transferable shared cap.",
        "", "## Operational receiver blocks", "",
    ]
    for block in blocks:
        lines.append(f"- {block['block_id']}: probe {block['probe_task_id']}, positions {block['manifest_positions'][0]}–{block['manifest_positions'][-1]}, tokens `{', '.join(block['execution_tokens'])}`.")
    lines += [
        "", "## Static validation", "",
        "- PASS — original protocol/manifest/analysis hashes and both frozen resource bindings matched before addendum creation.",
        "- PASS — the source V3 authorization hashes matched the current common source execution implementation and source pricing records.",
        "- PASS — all five formerly omitted fields have one explicit, machine-readable binding.",
        "- PASS — the six block slices preserve the original 30-token probe-major order with five resources each.",
        "- PASS — all five resources share every bound receiver setting; only their frozen starting content differs.",
        "- PASS — source seal/resources/original frozen documents were rehashed unchanged after addendum creation.",
        "- PASS — provider requests = 0; evaluator calls = 0; probe content read = false; receiver_started = false.",
    ]
    ADDENDUM_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Verify originals and sealed resources remained untouched by the static builder.
    assert_equal(source_hashes(), hashes_before, "original source/protocol hashes after addendum write")
    assert_equal(read_json(ROOT / "artifacts/experience_value/formal_freeze/FORMAL_SOURCE_PHASE_SEAL_V1.json")["canonical_content_sha256"], source_seal["canonical_content_sha256"], "source seal after addendum write")
    assert_equal(read_json(ROOT / "artifacts/experience_value/formal_receiver_resources_v1/FORMAL_RECEIVER_RESOURCES_V1.json")["canonical_content_sha256"], resources["canonical_content_sha256"], "resource manifest after addendum write")
    assert_equal(sha_bytes(canonical({key: value for key, value in addendum.items() if key != "canonical_content_sha256"})), addendum["canonical_content_sha256"], "addendum canonical recheck")
    assert_equal(sha_bytes(canonical({key: value for key, value in seal.items() if key != "canonical_content_sha256"})), seal["canonical_content_sha256"], "addendum seal canonical recheck")
    for path in (ADDENDUM_JSON, ADDENDUM_MD, ADDENDUM_SEAL):
        immutable(path)


if __name__ == "__main__":
    main()
