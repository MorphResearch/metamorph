"""Live orchestration entry for the sealed Formal Receiver V1 protocol.

V2 adds authorization, off-peak/preflight, dispatch, and block stopping only.
It imports every scientific binding from V1 and never rewrites frozen inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from llm.adapters import AdapterResponse, ProviderAdapter

from . import formal_receiver_run as v1
from .clbench_database_exploration import DatabaseExplorationAdapter
from .live import build_authorized_client, run_tool_only_episode
from .public_calibration_run import ALLOWED_TOOLS, FILE_TOOLS, _offpeak_status, _provider_connectivity_preflight
from .public_viability_gate_run import _events
from .records import AuthorizationError, BudgetError, CostLedger, LiveAuthorization
from .runner import ExperimentRunner

ROOT = Path(__file__).resolve().parents[2]
PENDING_STATUS = "PENDING_FORMAL_RECEIVER_BLOCK_R1_V2_USER_SIGNOFF_NO_LIVE_CALLS"
AUTHORIZED_STATUS = "AUTHORIZED_FORMAL_RECEIVER_BLOCK_01_V2"
OFFPEAK_RULE = {"offpeak_window": {"timezone": "Asia/Shanghai", "start_local": "18:05:00", "end_local": "08:55:00", "minimum_remaining_seconds_for_new_episode": 1080}}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuthorizationError("JSON object required")
    return value


def _r1(bindings: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plan, blocks = v1.execution_plan(bindings), v1.block_definition(bindings, v1.execution_plan(bindings))
    block = blocks["blocks"][0]
    rows = [row for row in plan["episodes"] if row["receiver_block_id"] == block["block_id"]]
    if block["block_id"] != "formal_receiver_block_01" or [row["frozen_token"] for row in rows] != block["execution_tokens"] or len(rows) != 5:
        raise AuthorizationError("frozen R1 definition differs")
    return rows, block


def _base_pending(bindings: dict[str, Any]) -> dict[str, Any]:
    rows, block = _r1(bindings)
    refs = {
        "formal_protocol": bindings["addendum"]["original_bindings"]["formal_protocol"],
        "receiver_manifest": bindings["addendum"]["original_bindings"]["receiver_manifest"],
        "analysis_plan": bindings["addendum"]["original_bindings"]["analysis_plan"],
        "source_seal": bindings["addendum"]["original_bindings"]["source_phase_seal"],
        "resource_manifest": bindings["addendum"]["original_bindings"]["receiver_resource_manifest"],
        "addendum": {"path": v1.ADDENDUM.name, "sha256": sha(v1.ADDENDUM)},
        "addendum_seal": {"path": v1.ADDENDUM_SEAL.name, "sha256": sha(v1.ADDENDUM_SEAL)},
        "execution_plan": {"path": v1.PLAN.name, "sha256": sha(v1.PLAN)},
        "block_definition": {"path": v1.BLOCKS.name, "sha256": sha(v1.BLOCKS)},
    }
    return {"status": PENDING_STATUS, "study_kind": "formal_receiver_v1", "live_requests_authorized": False, "runner_scientific_diff_from_sealed_receiver_protocol": "NONE", "block_id": block["block_id"], "allowed_manifest_positions": block["manifest_positions"], "allowed_tokens": block["execution_tokens"], "episodes": rows, "hard_cap_usd": "8.00", "five_episode_worst_case_reservation_usd": "7.69443840", "bindings": refs, "entry_code": {"path": "experiments/experience_value/formal_receiver_run_v2.py", "sha256": sha(Path(__file__))}, "tool_schema_canonical_sha256": bindings["tool_schema_hash"], "provider_requests": 0, "evaluator_calls": 0, "probe_content_read": False}


def write_pending_files(bindings: dict[str, Any], directory: Path = ROOT / "experiments/experience_value") -> tuple[Path, Path]:
    pending = _base_pending(bindings)
    pending_path = directory / "formal_receiver_block_01.v2.pending.json"
    auth_path = directory / "formal_receiver_block_01.v2.authorization.pending.json"
    pending_path.write_text(json.dumps(pending, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    auth_path.write_text(json.dumps({"status": "PENDING_NO_LIVE_AUTHORIZATION", "live_requests_authorized": False, "block_id": pending["block_id"], "pending_sha256": sha(pending_path), "entry_code": pending["entry_code"], "hard_cap_usd": "8.00", "provider_requests": 0, "evaluator_calls": 0, "probe_content_read": False}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pending_path, auth_path


def _validate_live(*, pending_path: Path, authorization_path: Path, bindings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    pending, authorization = _load_json(pending_path), _load_json(authorization_path)
    rows, block = _r1(bindings)
    if pending.get("status") != PENDING_STATUS or pending.get("live_requests_authorized") is not False:
        raise AuthorizationError("pending is not an unused V2 R1 pending")
    if pending.get("entry_code", {}).get("sha256") != sha(Path(__file__)):
        raise AuthorizationError("runner V2 hash differs before provider setup")
    if pending.get("block_id") != block["block_id"] or pending.get("allowed_manifest_positions") != block["manifest_positions"] or pending.get("allowed_tokens") != block["execution_tokens"] or pending.get("episodes") != rows:
        raise AuthorizationError("pending R1 scope differs from frozen plan")
    if pending.get("hard_cap_usd") != "8.00" or pending.get("tool_schema_canonical_sha256") != bindings["tool_schema_hash"]:
        raise AuthorizationError("pending hard cap or tool hash differs")
    for key, ref in pending.get("bindings", {}).items():
        expected = ref.get("sha256", ref.get("canonical_sha256"))
        path = ROOT / ref["path"]
        actual = sha(path) if "sha256" in ref else v1.canonical({k: v for k, v in _load_json(path).items() if k != "canonical_content_sha256"})
        if actual != expected:
            raise AuthorizationError(f"pending frozen binding differs: {key}")
    if authorization.get("status") != AUTHORIZED_STATUS or authorization.get("live_requests_authorized") is not True:
        raise AuthorizationError("authorization is unsigned, superseded, or wrong status")
    if authorization.get("pending_sha256") != sha(pending_path) or authorization.get("entry_code", {}).get("sha256") != sha(Path(__file__)):
        raise AuthorizationError("authorization pending or runner binding differs")
    if authorization.get("block_id") != block["block_id"] or authorization.get("allowed_tokens") != block["execution_tokens"] or authorization.get("hard_cap_usd") != "8.00":
        raise AuthorizationError("authorization scope differs")
    if authorization.get("real_model_requests_sent_under_this_authorization", 0) != 0 or authorization.get("authorization_consumed") is True:
        raise AuthorizationError("authorization is already consumed")
    return pending, authorization, rows


def _consume(path: Path) -> None:
    payload = _load_json(path)
    if payload.get("authorization_consumed"):
        raise AuthorizationError("authorization already consumed")
    payload.update(status="CONSUMED_FORMAL_RECEIVER_BLOCK_01_V2", authorization_consumed=True, real_model_requests_sent_under_this_authorization=1)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class _ConsumingAdapter(ProviderAdapter):
    def __init__(self, delegate: ProviderAdapter, authorization_path: Path):
        self.delegate, self.authorization_path, self.consumed = delegate, authorization_path, False

    def stream(self, **_kwargs: Any):
        raise TypeError("configured completion path")

    def complete_configured(self, **kwargs: Any) -> AdapterResponse:
        if not self.consumed:
            _consume(self.authorization_path)
            self.consumed = True
        return self.delegate.complete_configured(**kwargs)


def _default_task(task_id: int, records: Any) -> DatabaseExplorationAdapter:
    upstream = ROOT / "benchmarks/continual-learning-bench"
    return DatabaseExplorationAdapter(upstream_root=upstream, db_path=upstream / "data/database_exploration/products.db", questions_path=upstream / "data/database_exploration/questions.json", records=records, seed=42, max_queries_per_question=15, task_index=task_id - 1, allow_no_model_import_shim=False)


def execute(*, pending_path: Path, authorization_path: Path | None, output_root: Path, mode: str, adapter: ProviderAdapter | None = None, task_factory: Callable[[int, Any], Any] | None = None, preflight: Callable[[], dict[str, Any]] | None = None, offpeak: Callable[..., dict[str, Any]] | None = None) -> Path:
    bindings = v1.verify_frozen_bindings()
    if mode == "plan-only":
        rows, block = _r1(bindings)
        out = Path(output_root) / "formal_receiver_v2_plan.json"; out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"provider_requests": 0, "block_id": block["block_id"], "episodes": rows}, indent=2) + "\n", encoding="utf-8")
        return out
    if mode != "live" or authorization_path is None:
        raise AuthorizationError("V2 requires --plan-only or --live with authorization")
    pending, authorization, rows = _validate_live(pending_path=pending_path, authorization_path=authorization_path, bindings=bindings)
    result = (preflight or _provider_connectivity_preflight)()
    if not result.get("ok"):
        out = Path(output_root) / "formal_receiver_v2_block_report.json"; out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"status": "INVALID_INFRA_PRECHECK", "provider_requests": 0, "authorization_consumed": False, "preflight": result}, indent=2) + "\n", encoding="utf-8")
        return out
    offpeak_check = offpeak or _offpeak_status
    window = offpeak_check(OFFPEAK_RULE, for_new_episode=True)
    if not window.get("new_episode_allowed"):
        out = Path(output_root) / "formal_receiver_v2_block_report.json"; out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"status": "WAITING_OFFPEAK", "provider_requests": 0, "authorization_consumed": False, "time_window": window}, indent=2) + "\n", encoding="utf-8")
        return out
    config, prices = v1.receiver_config(bindings)
    if adapter is None:
        DatabaseExplorationAdapter.assert_real_litellm_available()
        adapter = build_authorized_client(LiveAuthorization(True, "deepseek", config.exact_model_id, "USD", Decimal("8.00"), 240, prices.source, max_episodes=5, episode_cap=5), config).adapter
    runner = ExperimentRunner(output_root, receiver_config=bindings["addendum"]["common_receiver"])
    ledger = CostLedger(LiveAuthorization(True, "deepseek", config.exact_model_id, "USD", Decimal("8.00"), 240, prices.source, max_episodes=5, episode_cap=5))
    wrapped = _ConsumingAdapter(adapter, authorization_path)
    factory = task_factory or _default_task
    report: dict[str, Any] = {"status": "RUNNING", "block_id": pending["block_id"], "episodes": [], "provider_requests": 0, "evaluator_calls": 0, "probe_content_read": False, "next_block": "NOT_STARTED"}
    for row in rows:
        source = v1._source_snapshot(row["resource_id"], runner, bindings); source_before = v1._resource_tree(source.path)
        task = factory(row["probe_task_id"], runner.records)
        view = task.reset()
        if str(view.task_id) != str(row["probe_task_id"]):
            raise AuthorizationError("public task ID differs from frozen R1")
        prepared = runner.prepare_receiver_task(str(row["probe_task_id"]), view.prompt, source)
        accepted = {"value": False}
        def submit(answer: str, _metrics: dict[str, Any]) -> None:
            if answer and not task.completed and not accepted["value"]:
                task.submit_answer(answer); accepted["value"] = True
        try:
            _answer, snapshot, metrics = run_tool_only_episode(prepared=prepared, manager=runner.manager, records=runner.records, database=task, adapter=wrapped, ledger=ledger, config=config, prices=prices, transport_kind="live_provider", allowed_tool_names=set(ALLOWED_TOOLS), tool_call_limits={"query_sql": 15}, tool_call_group_limits={"file_operations": (set(FILE_TOOLS), 8)}, pre_request_check=lambda: offpeak_check(OFFPEAK_RULE), stop_on_tool_limit_reached=True, terminal_only_after_tool_limit_names={"query_sql"}, enable_optional_consolidation=False, before_consolidation=submit)
        except Exception as exc:
            report.update(status="INVALID_INFRA" if isinstance(exc, (BudgetError, TimeoutError, ConnectionError)) else "INVALID_SYSTEM", stop_reason=type(exc).__name__)
            break
        native = task.evaluate_native() if accepted["value"] else None
        correct, score = v1._native_summary(native) if native is not None else (None, None)
        events = _events(runner.records.path, prepared.session.attempt_id)
        report["episodes"].append({**row, "episode_id": prepared.session.attempt_id, "native_answer_submitted": accepted["value"], "correct": correct, "native_score": score, "analysis_status": "EVALUATED_NATIVE" if native is not None else "RESOURCE_LIMITED_FAILURE", "main_stop_reason": metrics.get("runner_stop_reason"), "sql_queries": metrics.get("tool_calls_by_name", {}).get("query_sql", 0), "model_decisions": metrics.get("llm_calls"), "sealed_resource_unchanged": source_before == v1._resource_tree(source.path), "evaluator_reference_visible": False, "post_evaluation_model_calls": 0, "consolidation": False})
    report["provider_requests"] = 1 if wrapped.consumed else 0
    report["evaluator_calls"] = sum(row["native_answer_submitted"] for row in report["episodes"])
    if report["status"] == "RUNNING": report["status"] = "COMPLETED" if len(report["episodes"]) == 5 else "INVALID_SYSTEM"
    out = runner.records.write_json("formal_receiver_v2_block_report.json", report)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Formal Receiver V2 live entry")
    group = parser.add_mutually_exclusive_group(required=True); group.add_argument("--plan-only", action="store_true"); group.add_argument("--live", action="store_true")
    parser.add_argument("--pending", type=Path, required=True); parser.add_argument("--authorization", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts/experience_value/formal_receiver_v2")
    args = parser.parse_args()
    print(execute(pending_path=args.pending, authorization_path=args.authorization, output_root=args.output_root, mode="plan-only" if args.plan_only else "live"))


if __name__ == "__main__": main()
