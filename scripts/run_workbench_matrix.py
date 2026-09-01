"""Run a reproducible WorkBench routing matrix.

The default four arms are S0, Complex-only, Adaptive, and Oracle.  The legacy
S1-S4 conditions remain available for ablations via ``--conditions``. S3 uses
a read-only causal shadow phase because replaying a mutating action in the same
WorkBench sandbox would contaminate the official state score.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Settings
from llm.client import build_client
from scripts.run_workbench_smoke import (
    _extract_json_object,
    _is_write_tool,
    _merge_metrics,
    _run_phase,
    _validate_handoff,
    workbench_tools,
)
from multiagent.routing import (
    LEGACY_CONDITIONS,
    ROUTING_CONDITIONS,
    load_oracle_labels,
    task_features,
)


CONDITIONS = {**ROUTING_CONDITIONS, **LEGACY_CONDITIONS}
ROUTING_ARMS = tuple(ROUTING_CONDITIONS)
LEGACY_ARMS = tuple(LEGACY_CONDITIONS)


class RouterDecision(BaseModel):
    """The planner's pre-execution route decision."""

    route: Literal["single_agent", "complex"]
    complexity: Literal["simple", "complex", "uncertain"] = "uncertain"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    predicted_steps: int = Field(default=1, ge=1)
    reason: str = ""


def _task_spec(value: str) -> tuple[str, int]:
    domain, separator, index = value.partition(":")
    if not separator or not index.isdigit():
        raise argparse.ArgumentTypeError("task must use DOMAIN:INDEX, e.g. calendar:0")
    return domain, int(index)


def _parse_router_decision(text: str) -> RouterDecision | None:
    payload = _extract_json_object(text)
    if payload is None:
        return None
    try:
        return RouterDecision.model_validate(payload)
    except Exception:  # noqa: BLE001 - invalid router output is handled conservatively
        return None


def _router_prompt(task: str, *, tool_names: list[str], features: dict[str, Any]) -> str:
    return (
        "You are a task-complexity router. Do not execute tools and do not solve the task. "
        "Choose whether a normal single-agent loop is sufficient or whether the bounded "
        "planner/executor/verifier/replay controller is justified. Use COMPLEX when the task "
        "has conditional dependencies, multiple records/tools, ordering constraints, bulk edits, "
        "or meaningful recovery/verification risk. Be conservative when uncertain. Return exactly "
        "one JSON object and no markdown with this schema: "
        '{"route":"single_agent|complex","complexity":"simple|complex|uncertain",'
        '"confidence":0.0,"predicted_steps":1,"reason":"..."}.\n\n'
        f"AVAILABLE TOOL NAMES (for estimating breadth only): {json.dumps(tool_names, ensure_ascii=False)}\n"
        f"OBSERVABLE TASK FEATURES (not gold outcome): {json.dumps(features, ensure_ascii=False)}\n"
        "TASK:\n" + task
    )


def run_one(
    *,
    workbench_dir: Path,
    domain: str,
    task_index: int,
    condition: str,
    model_name: str,
    max_turns: int,
    max_tool_calls: int,
    token_budget: int,
    max_latency_seconds: float,
    allow_write: bool,
    lesson_file: Path | None,
    oracle_labels: dict[str, str] | None,
    complex_condition: str,
) -> dict[str, Any]:
    os.chdir(workbench_dir)
    if str(workbench_dir) not in sys.path:
        sys.path.insert(0, str(workbench_dir))
    from src.evals.actions import convert_intermediate_step_to_function_call
    from src.evals.evaluation import has_side_effects, is_correct
    from src.evals.inference import get_toolkits as load_toolkits
    from src.tools.state import reset_state

    tasks_path = workbench_dir / "data" / "processed" / "tasks_and_outcomes" / f"{domain}_tasks_and_outcomes.csv"
    tasks = pd.read_csv(tasks_path)
    if not 0 <= task_index < len(tasks):
        raise ValueError(f"task index must be within [0, {len(tasks) - 1}]")
    row = tasks.iloc[task_index]
    task = str(row["task"])
    outcome = ast.literal_eval(str(row["outcome"]))
    domains = ast.literal_eval(str(row["domains"]))
    task_tools = load_toolkits(domains)

    run_root = workbench_dir / "metamorph_matrix_runs" / condition
    run_dir = run_root / f"{domain}-{task_index}-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_environment(data_dir=run_dir / "metamorph_state")
    client = build_client(settings.provider, model_name or settings.model_name, settings.base_url, settings.api_key_env)
    calls: list[tuple[str, dict[str, str]]] = []
    aggregate: dict[str, Any] = {}
    phases: dict[str, Any] = {}
    started = time.perf_counter()

    def remaining_tools() -> int:
        return max(0, max_tool_calls - int(aggregate.get("tool_calls", 0) or 0))

    def remaining_tokens() -> int:
        return max(0, token_budget - int(aggregate.get("total_tokens", 0) or 0))

    def remaining_latency() -> float:
        return max(0.0, max_latency_seconds - (time.perf_counter() - started))

    features = task_features(task, domain_count=len(domains))
    route: str | None = None
    route_source: str | None = None
    route_confidence: float | None = None
    oracle_label: str | None = None
    router_answer = ""
    if condition == "Complex-only":
        route, route_source = "complex", "fixed"
    elif condition == "Oracle":
        key = f"{domain}:{task_index}"
        if oracle_labels is None or key not in oracle_labels:
            raise ValueError(
                f"Missing Oracle label for {key}; add it to --oracle-label-file before running Oracle"
            )
        oracle_label = oracle_labels[key]
        route = "single_agent" if oracle_label == "simple" else "complex"
        route_source = "human_annotation"
    elif condition == "Adaptive":
        router_answer, router_metrics = _run_phase(
            name="router",
            prompt=_router_prompt(
                task,
                tool_names=[tool.name for tool in task_tools],
                features=features,
            ),
            allowed_tools=set(),
            client=client.client,
            model_name=client.model_name,
            adapter=client.adapter,
            run_dir=run_dir,
            max_turns=1,
            max_tool_calls=0,
            max_total_tokens=remaining_tokens(),
            max_latency_seconds=remaining_latency(),
        )
        decision = _parse_router_decision(router_answer)
        # A malformed or low-confidence route is sent to the guarded complex
        # path.  This protects complex tasks from silent under-routing.
        if decision is None:
            route, route_source, route_confidence = "complex", "adaptive_fallback", 0.0
            router_error = "router did not return a valid JSON decision"
        elif decision.route == "single_agent" and decision.confidence >= 0.65:
            route, route_source, route_confidence = "single_agent", "planner", decision.confidence
            router_error = None
        else:
            route, route_source, route_confidence = "complex", "planner_conservative", decision.confidence
            router_error = None
        _merge_metrics(aggregate, router_metrics)
        phases["router"] = {
            "status": "completed" if decision else "fallback_complex",
            "metrics": router_metrics,
            "decision": decision.model_dump() if decision else None,
            "error": router_error,
        }

    execution_condition = condition
    if condition in {"Complex-only", "Adaptive", "Oracle"}:
        execution_condition = "S0" if route == "single_agent" else complex_condition
    if condition in LEGACY_ARMS:
        execution_condition = condition

    lesson_context = "（无历史 lesson）"
    if execution_condition == "S4" and lesson_file and lesson_file.exists():
        lesson_context = "\n".join(lesson_file.read_text(encoding="utf-8").splitlines()[-3:]) or lesson_context

    reset_state()
    with workbench_tools(task_tools, calls) as safe_to_official:
        read_tools = {safe for safe, official in safe_to_official.items() if not _is_write_tool(official)}
        write_tools = {safe for safe, official in safe_to_official.items() if _is_write_tool(official)}
        all_tools = set(safe_to_official)
        planner_answer = ""
        executor_answer = ""
        verifier_answer = ""
        handoff_error: str | None = None

        if execution_condition == "S0":
            planner_answer, metrics = _run_phase(
                name="single_agent",
                prompt=(
                    "You are a single-agent WorkBench controller. Inspect the sandbox before mutation, perform only the requested action, "
                    "and verify the resulting state when possible. Do not claim success without state evidence.\n\nTASK:\n" + task
                ),
                allowed_tools=all_tools,
                client=client.client,
                model_name=client.model_name,
                adapter=client.adapter,
                run_dir=run_dir,
                max_turns=max_turns,
                max_tool_calls=remaining_tools(),
                max_total_tokens=remaining_tokens(),
                max_latency_seconds=remaining_latency(),
                allow_write=allow_write,
            )
            _merge_metrics(aggregate, metrics)
            phases["single_agent"] = {"status": "completed" if planner_answer.strip() else "failed", "metrics": metrics}
        else:
            style = {
                "S1": "Follow the fixed read-plan-write-verify controller.",
                "S2": "Adapt the retrieval plan to this task and use the minimum sufficient read operations.",
                "S3": "Use the adaptive plan; a read-only causal shadow will be run after official execution.",
                "S4": "Use the adaptive plan and this prior lesson context:\n" + lesson_context,
            }[execution_condition]
            planner_answer, planner_metrics = _run_phase(
                name="planner",
                prompt=(
                    "You are the read-only planning phase for WorkBench. Use only read tools. Resolve the exact target and all values "
                    "needed for one mutation. Return exactly one JSON object, either "
                    '{"status":"READY","tool":"<safe write tool>","arguments":{"<arg>":"<value>"},"evidence":["<fact>"],"reason":""} '
                    'or {"status":"BLOCKED","tool":null,"arguments":{},"evidence":[],"reason":"<missing evidence>"}. '
                    + style + "\n\nTASK:\n" + task
                ),
                allowed_tools=read_tools,
                client=client.client,
                model_name=client.model_name,
                adapter=client.adapter,
                run_dir=run_dir,
                max_turns=min(max_turns, 6),
                max_tool_calls=min(remaining_tools(), 5),
                max_total_tokens=remaining_tokens(),
                max_latency_seconds=remaining_latency(),
            )
            handoff, handoff_error = _validate_handoff(
                planner_answer,
                write_tools=write_tools,
                safe_to_official=safe_to_official,
                task_tools=task_tools,
            )
            phases["planner"] = {
                "status": "ready" if handoff and handoff.status == "READY" else "blocked" if handoff and handoff.status == "BLOCKED" else "invalid",
                "metrics": planner_metrics,
                "handoff": handoff.model_dump() if handoff else None,
                "handoff_error": handoff_error,
            }
            _merge_metrics(aggregate, planner_metrics)

            writes_before = len(calls)
            executor_metrics: dict[str, Any] = {}
            if handoff and handoff.status == "READY":
                executor_answer, executor_metrics = _run_phase(
                    name="executor",
                    prompt=(
                        "You are the write-only WorkBench executor. Use exactly the validated tool and arguments below; do not search. "
                        "If the arguments are insufficient, do not call a tool and report BLOCKED.\n\nTASK:\n" + task +
                        "\n\nVALIDATED HANDOFF:\n" + json.dumps(handoff.model_dump(), ensure_ascii=False)
                    ),
                    allowed_tools=write_tools,
                    client=client.client,
                    model_name=client.model_name,
                    adapter=client.adapter,
                    run_dir=run_dir,
                    max_turns=2,
                    max_tool_calls=min(remaining_tools(), 1),
                    max_total_tokens=remaining_tokens(),
                    max_latency_seconds=remaining_latency(),
                    allow_write=allow_write,
                )
                _merge_metrics(aggregate, executor_metrics)
            write_calls = [call for call in calls[writes_before:] if _is_write_tool(call[0])]
            phases["executor"] = {
                "status": "executed" if write_calls else "blocked_no_write",
                "metrics": executor_metrics,
                "write_actions": len(write_calls),
            }

            verifier_metrics: dict[str, Any] = {}
            if write_calls:
                verifier_answer, verifier_metrics = _run_phase(
                    name="verifier",
                    prompt=(
                        "You are the read-only WorkBench verifier. Inspect the sandbox and return VERIFIED only if the requested state is present; "
                        "otherwise return NOT VERIFIED.\n\nTASK:\n" + task
                    ),
                    allowed_tools=read_tools,
                    client=client.client,
                    model_name=client.model_name,
                    adapter=client.adapter,
                    run_dir=run_dir,
                    max_turns=min(max_turns, 3),
                    max_tool_calls=min(remaining_tools(), 2),
                    max_total_tokens=remaining_tokens(),
                    max_latency_seconds=remaining_latency(),
                )
                _merge_metrics(aggregate, verifier_metrics)
            phases["verifier"] = {"status": "completed" if verifier_answer.strip() else "skipped_no_write", "metrics": verifier_metrics}

            if execution_condition in {"S3", "S4"}:
                shadow_answer, shadow_metrics = _run_phase(
                    name="causal_shadow",
                    prompt=(
                        "Run a read-only causal shadow analysis of the WorkBench plan below. Do not mutate the sandbox. "
                        "Explain what evidence or dependency would be missing if the planner-to-executor handoff were masked. "
                        "Return a concise JSON object with fields dependency, expected_failure, and evidence.\n\nTASK:\n" + task +
                        "\n\nPLANNER HANDOFF:\n" + planner_answer
                    ),
                    allowed_tools=read_tools,
                    client=client.client,
                    model_name=client.model_name,
                    adapter=client.adapter,
                    run_dir=run_dir,
                    max_turns=1,
                    max_tool_calls=min(remaining_tools(), 1),
                    max_total_tokens=remaining_tokens(),
                    max_latency_seconds=remaining_latency(),
                )
                _merge_metrics(aggregate, shadow_metrics)
                phases["causal_shadow"] = {"status": "completed" if shadow_answer.strip() else "stopped", "metrics": shadow_metrics, "read_only": True}

        write_calls = [call for call in calls if _is_write_tool(call[0])]
        predicted_actions = [convert_intermediate_step_to_function_call(name, args) for name, args in calls]
        controller_error = "" if write_calls or not write_tools else (handoff_error or "controller blocked completion: required write action was not executed")
        final_answer = verifier_answer or executor_answer or planner_answer
        correct = is_correct(predicted_actions, outcome, controller_error or ("" if final_answer.strip() else "empty final answer"))
        side_effects = has_side_effects(predicted_actions, correct)

    result = {
        "benchmark": "WorkBench",
        "condition": condition,
        "condition_definition": CONDITIONS[condition],
        "execution_condition": execution_condition,
        "complex_condition": complex_condition if condition in ROUTING_ARMS else None,
        "routing": {
            "route": route,
            "source": route_source,
            "confidence": route_confidence,
            "oracle_label": oracle_label,
            "features": features,
        } if condition in ROUTING_ARMS else None,
        "domain": domain,
        "task_index": task_index,
        "official_score": {"correct": correct, "side_effect": side_effects},
        "status": "completed" if final_answer.strip() and not controller_error else "blocked_no_write" if controller_error else "failed",
        "metrics": {
            **aggregate,
            "wall_latency_seconds": round(time.perf_counter() - started, 6),
            "token_budget": token_budget,
            "max_tool_calls": max_tool_calls,
            "max_latency_seconds": max_latency_seconds,
        },
        "phases": phases,
        "tool_calls": len(calls),
        "write_actions": len(write_calls),
        "allow_write": allow_write,
        "actions": predicted_actions,
        "final_answer": final_answer,
    }
    result_path = run_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if execution_condition == "S4" and lesson_file:
        lesson_file.parent.mkdir(parents=True, exist_ok=True)
        with lesson_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"domain": domain, "task_index": task_index, "correct": correct, "phases": list(phases)}, ensure_ascii=False) + "\n")
    return {
        "result_path": str(result_path),
        **{
            key: result[key]
            for key in (
                "condition",
                "execution_condition",
                "routing",
                "domain",
                "task_index",
                "official_score",
                "status",
                "metrics",
                "tool_calls",
                "write_actions",
            )
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the WorkBench adaptive routing matrix")
    parser.add_argument("--workbench-dir", type=Path, default=PROJECT_ROOT / "benchmarks" / "workbench")
    parser.add_argument("--task", dest="tasks", type=_task_spec, action="append", default=None, help="DOMAIN:INDEX; repeat three times")
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=tuple(CONDITIONS),
        default=list(ROUTING_ARMS),
        help="Default: S0 Complex-only Adaptive Oracle. S1-S4 remain available as legacy ablations.",
    )
    parser.add_argument("--model", default="", help="Override METAMORPH_MODEL for this matrix")
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--token-budget", type=int, default=30_000)
    parser.add_argument("--max-latency-seconds", type=float, default=180.0)
    parser.add_argument("--allow-write", action="store_true", help="Required for official WorkBench mutation scoring")
    parser.add_argument("--lesson-file", type=Path, default=None)
    parser.add_argument(
        "--complex-condition",
        choices=LEGACY_ARMS,
        default="S3",
        help="Fixed complex controller used by Complex-only, Adaptive, and Oracle (default: S3).",
    )
    parser.add_argument(
        "--oracle-label-file",
        type=Path,
        default=PROJECT_ROOT / "config" / "task_complexity_labels.json",
        help="Human-authored DOMAIN:INDEX -> simple|complex labels for Oracle.",
    )
    args = parser.parse_args()
    tasks = args.tasks or [("calendar", 0), ("customer_relationship_manager", 0), ("project_management", 0)]
    workbench_dir = args.workbench_dir.resolve()
    matrix_root = workbench_dir / "metamorph_matrix_runs" / f"matrix-{time.strftime('%Y%m%d-%H%M%S')}"
    lesson_file = args.lesson_file.resolve() if args.lesson_file else matrix_root / "lessons.jsonl"
    oracle_labels = load_oracle_labels(args.oracle_label_file.resolve()) if "Oracle" in args.conditions else None
    summary: list[dict[str, Any]] = []
    for condition in args.conditions:
        for domain, task_index in tasks:
            summary.append(run_one(
                workbench_dir=workbench_dir,
                domain=domain,
                task_index=task_index,
                condition=condition,
                model_name=args.model,
                max_turns=args.max_turns,
                max_tool_calls=args.max_tool_calls,
                token_budget=args.token_budget,
                max_latency_seconds=args.max_latency_seconds,
                allow_write=args.allow_write,
                lesson_file=lesson_file
                if condition == "S4" or (condition in ROUTING_ARMS and args.complex_condition == "S4")
                else None,
                oracle_labels=oracle_labels,
                complex_condition=args.complex_condition,
            ))
    summary_path = matrix_root / "summary.json"
    matrix_root.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({"conditions": CONDITIONS, "tasks": tasks, "results": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary_path": str(summary_path), "results": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
