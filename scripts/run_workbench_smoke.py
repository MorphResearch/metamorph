"""Run one WorkBench task through a guarded read-plan-write-verify controller.

WorkBench scores the final state of a mutable sandbox. A generic tool loop can
mistake a successful search for task completion, so this runner intentionally
separates discovery from mutation: the planner receives only read tools, the
executor receives only write tools, and the verifier receives only read tools.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

import pandas as pd
from pydantic import BaseModel, Field, create_model


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Settings
from graphs.agent import run_agent
from llm.client import build_client
from state.events import EventLogger
from tools.base import TOOL_REGISTRY, register


WRITE_PREFIXES = ("create_", "delete_", "update_", "send_", "forward_", "reply_", "add_")
MUTATION_WORDS = re.compile(
    r"\b(create|delete|remove|cancel|update|change|modify|send|forward|reply|add|assign|reschedule)\b",
    re.IGNORECASE,
)


def _add_workbench_to_path(workbench_dir: Path) -> None:
    resolved = str(workbench_dir.resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


def _safe_tool_name(name: str) -> str:
    return "workbench_" + "".join(char if char.isalnum() else "_" for char in name)


def _is_write_tool(name: str) -> bool:
    """Return whether an official WorkBench tool mutates the sandbox."""
    operation = name.rsplit(".", maxsplit=1)[-1]
    return operation.startswith(WRITE_PREFIXES)


def _mutation_required(task: str) -> bool:
    return bool(MUTATION_WORDS.search(task))


def _required_write_args(tool: Any) -> set[str]:
    """Return semantic required fields for WorkBench's permissive tool API.

    WorkBench annotates many mutation parameters as ``Optional`` so that its
    generic tool loop can emit a readable error. The controller must still
    reject incomplete planner handoffs before entering the write phase.
    """
    operation = tool.name.rsplit(".", maxsplit=1)[-1]
    arguments = set(tool.args_schema)
    if operation == "add_customer":
        return {"customer_name", "assigned_to_email", "status"}
    if operation.startswith(("create_", "update_", "send_", "forward_", "reply_")):
        return arguments
    if operation.startswith("delete_"):
        return arguments
    return arguments


class PlannerHandoff(BaseModel):
    """Strict planner-to-executor contract for state-changing tasks."""

    status: Literal["READY", "BLOCKED"]
    tool: str | None = None
    arguments: dict[str, str] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract one JSON object from a model response, including code fences."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(candidate[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def _validate_handoff(
    answer: str,
    *,
    write_tools: set[str],
    safe_to_official: dict[str, str],
    task_tools: list[Any],
) -> tuple[PlannerHandoff | None, str | None]:
    payload = _extract_json_object(answer)
    if payload is None:
        return None, "planner did not return a JSON handoff"
    try:
        handoff = PlannerHandoff.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - invalid model output becomes BLOCKED
        return None, f"invalid planner handoff: {exc}"
    if handoff.status == "BLOCKED":
        if handoff.tool is not None or handoff.arguments:
            return None, "BLOCKED handoff must not contain a tool or arguments"
        return handoff, None
    if handoff.tool not in write_tools:
        # Accept an official tool name, then normalize it to the safe registry name.
        safe_name = next((safe for safe, official in safe_to_official.items() if official == handoff.tool), None)
        if safe_name is None:
            return None, "planner selected a tool outside the write allowlist"
        handoff.tool = safe_name
    selected = next((tool for tool in task_tools if _safe_tool_name(tool.name) == handoff.tool), None)
    if selected is None:
        return None, "planner selected an unknown write tool"
    expected = set(selected.args_schema)
    required = _required_write_args(selected)
    missing = sorted(required - set(handoff.arguments))
    unknown = sorted(set(handoff.arguments) - expected)
    empty = sorted(name for name in required if not str(handoff.arguments.get(name, "")).strip())
    if missing or empty:
        missing = sorted(set(missing) | set(empty))
        return None, f"planner handoff is missing required arguments: {', '.join(missing)}"
    if unknown:
        return None, f"planner handoff contains unknown arguments: {', '.join(unknown)}"
    if not handoff.evidence:
        return None, "planner handoff is missing evidence"
    return handoff, None


@contextmanager
def workbench_tools(tools: list[Any], calls: list[tuple[str, dict[str, str]]]) -> Iterator[dict[str, str]]:
    """Temporarily expose a task's official WorkBench tools.

    The dynamically-created Pydantic class keeps the source tool docstring.
    ``tools.base.openai_tool_schema`` uses that docstring as the function
    description, so the model receives WorkBench's exact action semantics,
    parameter formats, and examples rather than only a generated tool name.
    """

    original = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()
    safe_to_official: dict[str, str] = {}
    for workbench_tool in tools:
        safe_name = _safe_tool_name(workbench_tool.name)
        fields: dict[str, Any] = {}
        for arg_name, entry in workbench_tool.args_schema.items():
            default = entry.get("default", ...)
            title = str(entry.get("title", arg_name))
            fields[arg_name] = (str, Field(default=default, description=title))
        schema = create_model(f"{safe_name.title()}Input", **fields)
        schema.__doc__ = str(getattr(workbench_tool, "description", "")).strip()

        def invoke(_tool: Any = workbench_tool, **kwargs: str) -> str:
            # Pydantic includes optional fields with their ``None`` default in
            # model_dump(); WorkBench expects omitted optional parameters, not
            # the literal string "None" (notably for calendar time bounds).
            normalized = {key: str(value) for key, value in kwargs.items() if value is not None}
            value = _tool(**normalized)
            # Only completed sandbox calls are sent to the official evaluator.
            calls.append((_tool.name, normalized))
            return str(value)

        register(safe_name, schema, invoke, mutates=_is_write_tool(workbench_tool.name))
        safe_to_official[safe_name] = workbench_tool.name
    try:
        yield safe_to_official
    finally:
        TOOL_REGISTRY.clear()
        TOOL_REGISTRY.update(original)


def _merge_metrics(target: dict[str, Any], phase_metrics: dict[str, Any]) -> None:
    for key in ("llm_calls", "tool_calls", "prompt_tokens", "completion_tokens", "total_tokens", "latency_seconds"):
        target[key] = round(target.get(key, 0) + phase_metrics.get(key, 0), 6)
    target["success"] = bool(target.get("success") or phase_metrics.get("success"))


def _run_phase(
    *,
    name: str,
    prompt: str,
    allowed_tools: set[str],
    client: Any,
    model_name: str,
    adapter: Any,
    run_dir: Path,
    max_turns: int,
    max_tool_calls: int,
    max_total_tokens: int | None = None,
    max_latency_seconds: float | None = None,
    allow_write: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Run an isolated controller phase and preserve its own event stream."""
    phase_metrics: dict[str, Any] = {}
    answer = run_agent(
        client=client,
        model_name=model_name,
        messages=[{"role": "user", "content": prompt}],
        logger=EventLogger(run_dir / "events" / name),
        data_dir=run_dir / "metamorph_state" / name,
        workspace_root=PROJECT_ROOT,
        max_turns=max_turns,
        adapter=adapter,
        metrics=phase_metrics,
        allowed_tool_names=allowed_tools,
        max_tool_calls=max_tool_calls,
        max_total_tokens=max_total_tokens,
        max_latency_seconds=max_latency_seconds,
        allow_write=allow_write,
    )
    return answer, phase_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one WorkBench task with Metamorph")
    parser.add_argument("--workbench-dir", type=Path, default=PROJECT_ROOT / "benchmarks" / "workbench")
    parser.add_argument("--domain", default="calendar", choices=("analytics", "calendar", "customer_relationship_manager", "email", "multi_domain", "project_management"))
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=8, help="Compatibility cap; phases use tighter caps.")
    parser.add_argument("--max-tool-calls", type=int, default=5, help="Compatibility cap; phases use tighter caps.")
    parser.add_argument("--token-budget", type=int, default=80_000, help="One shared token budget across all phases.")
    parser.add_argument("--max-latency-seconds", type=float, default=300.0, help="One shared wall-clock budget across all phases.")
    parser.add_argument("--allow-write", action="store_true", help="Explicitly allow WorkBench mutation calls.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workbench_dir = args.workbench_dir.resolve()
    os.chdir(workbench_dir)
    _add_workbench_to_path(workbench_dir)
    from src.evals.actions import convert_intermediate_step_to_function_call
    from src.evals.evaluation import has_side_effects, is_correct
    from src.evals.inference import get_toolkits
    from src.tools.state import reset_state

    tasks_path = workbench_dir / "data" / "processed" / "tasks_and_outcomes" / f"{args.domain}_tasks_and_outcomes.csv"
    tasks = pd.read_csv(tasks_path)
    if not 0 <= args.task_index < len(tasks):
        raise ValueError(f"task-index must be within [0, {len(tasks) - 1}]")
    row = tasks.iloc[args.task_index]
    task = str(row["task"])
    outcome = ast.literal_eval(str(row["outcome"]))
    task_tools = get_toolkits(ast.literal_eval(str(row["domains"])))
    requires_mutation = _mutation_required(task)

    run_dir = workbench_dir / "metamorph_runs" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_environment(data_dir=run_dir / "metamorph_state")
    allow_write = settings.allow_write or args.allow_write
    client = build_client(settings.provider, settings.model_name, settings.base_url, settings.api_key_env)
    calls: list[tuple[str, dict[str, str]]] = []
    aggregate_metrics: dict[str, Any] = {}
    phases: dict[str, dict[str, Any]] = {}
    reset_state()
    started = time.perf_counter()

    def remaining_tool_calls() -> int:
        return max(0, args.max_tool_calls - int(aggregate_metrics.get("tool_calls", 0) or 0))

    def remaining_tokens() -> int:
        return max(0, args.token_budget - int(aggregate_metrics.get("total_tokens", 0) or 0))

    def remaining_latency() -> float:
        return max(0.0, args.max_latency_seconds - (time.perf_counter() - started))

    with workbench_tools(task_tools, calls) as safe_to_official:
        read_tools = {safe for safe, official in safe_to_official.items() if not _is_write_tool(official)}
        write_tools = {safe for safe, official in safe_to_official.items() if _is_write_tool(official)}
        planner_prompt = (
            "You are the read-only planning phase of a WorkBench execution controller. "
            "Use the supplied read-only sandbox tools to identify the exact target and all values needed for the task. "
            "Do not attempt any create, update, delete, send, reply, forward, or add operation. "
            "Make one focused search first; do not repeat equivalent searches. Then use ID-based lookup on returned candidates "
            "to resolve every constraint in the task (for example, ordering, date, title, participant, and duration). "
            "For an ordinal calendar request such as 'first meeting', use the chronologically earliest matching event; "
            "do not infer an unstated account owner or debate that convention. "
            "When evidence is sufficient, return exactly one JSON object and no markdown: "
            "{\"status\":\"READY\",\"tool\":\"<safe write tool name>\","
            "\"arguments\":{\"<arg>\":\"<value>\"},\"evidence\":[\"<fact supporting the action>\"],\"reason\":\"\"}. "
            "Use the exact safe write tool name shown by the tool schema. If evidence is insufficient, return "
            "{\"status\":\"BLOCKED\",\"tool\":null,\"arguments\":{},\"evidence\":[],\"reason\":\"<missing evidence>\"}.\n\nTASK:\n" + task
        )
        planner_answer, planner_metrics = _run_phase(
            name="planner",
            prompt=planner_prompt,
            allowed_tools=read_tools,
            client=client.client,
            model_name=client.model_name,
            adapter=client.adapter,
            run_dir=run_dir,
            # One extra turn after the bounded read calls is required to turn
            # observations into an explicit executor hand-off.
            max_turns=min(args.max_turns, 6),
            max_tool_calls=min(remaining_tool_calls(), 5),
            max_total_tokens=remaining_tokens(),
            max_latency_seconds=remaining_latency(),
        )
        handoff, handoff_error = _validate_handoff(
            planner_answer,
            write_tools=write_tools,
            safe_to_official=safe_to_official,
            task_tools=task_tools,
        ) if requires_mutation else (None, None)
        phases["planner"] = {
            "status": "ready" if handoff and handoff.status == "READY" else "blocked" if handoff and handoff.status == "BLOCKED" else "invalid" if requires_mutation else "completed",
            "metrics": planner_metrics,
            "handoff": handoff.model_dump() if handoff else None,
            "handoff_error": handoff_error,
        }
        _merge_metrics(aggregate_metrics, planner_metrics)

        writes_before = len(calls)
        executor_answer = ""
        executor_metrics: dict[str, Any] = {}
        if requires_mutation and handoff and handoff.status == "READY":
            executor_prompt = (
                "You are the write-only execution phase of a WorkBench controller. "
                "Use only the provided write tools. Do not search or retrieve data. "
                "Execute exactly one well-supported mutation from the planner's evidence. "
                "If the plan lacks a precise target or required parameter, do not guess: reply BLOCKED without calling a tool. "
                "After a successful tool call, briefly report the executed action.\n\n"
                "TASK:\n" + task + "\n\nVALIDATED PLANNER HANDOFF (use exactly this tool and arguments):\n" +
                json.dumps(handoff.model_dump(), ensure_ascii=False)
            )
            executor_answer, executor_metrics = _run_phase(
                name="executor",
                prompt=executor_prompt,
                allowed_tools=write_tools,
                client=client.client,
                model_name=client.model_name,
                adapter=client.adapter,
                run_dir=run_dir,
                max_turns=min(args.max_turns, 2),
                max_tool_calls=min(remaining_tool_calls(), 1),
                max_total_tokens=remaining_tokens(),
                max_latency_seconds=remaining_latency(),
                allow_write=allow_write,
            )
            _merge_metrics(aggregate_metrics, executor_metrics)
        write_calls = [call for call in calls[writes_before:] if _is_write_tool(call[0])]
        phases["executor"] = {
            "status": "executed" if write_calls else ("not_required" if not requires_mutation else "blocked_no_write"),
            "metrics": executor_metrics,
            "write_actions": len(write_calls),
        }

        verifier_answer = ""
        verifier_metrics: dict[str, Any] = {}
        if not requires_mutation or write_calls:
            verifier_prompt = (
                "You are the read-only verification phase of a WorkBench controller. "
                "Inspect the sandbox state using the provided read-only tools. Do not mutate anything. "
                "Verify whether the requested outcome is now present; report VERIFIED only when the actual state supports it, "
                "otherwise report NOT VERIFIED.\n\nTASK:\n" + task + "\n\n"
                "PLANNER OUTPUT:\n" + planner_answer + "\n\nEXECUTOR OUTPUT:\n" + executor_answer
            )
            verifier_answer, verifier_metrics = _run_phase(
                name="verifier",
                prompt=verifier_prompt,
                allowed_tools=read_tools,
                client=client.client,
                model_name=client.model_name,
                adapter=client.adapter,
                run_dir=run_dir,
                max_turns=min(args.max_turns, 3),
                max_tool_calls=min(remaining_tool_calls(), 2),
                max_total_tokens=remaining_tokens(),
                max_latency_seconds=remaining_latency(),
            )
            _merge_metrics(aggregate_metrics, verifier_metrics)
        phases["verifier"] = {
            "status": "completed" if verifier_answer.strip() else ("skipped_no_write" if requires_mutation else "failed"),
            "metrics": verifier_metrics,
        }

    predicted_actions = [convert_intermediate_step_to_function_call(name, tool_input) for name, tool_input in calls]
    controller_error = "" if (not requires_mutation or write_calls) else (
        "controller blocked completion: required write action was not executed"
        if handoff_error is None else f"controller blocked completion: {handoff_error}"
    )
    final_answer = verifier_answer or executor_answer or planner_answer
    correct = is_correct(predicted_actions, outcome, controller_error or ("" if final_answer.strip() else "empty final answer"))
    side_effects = has_side_effects(predicted_actions, correct)
    status = "completed" if final_answer.strip() and not controller_error else "blocked_no_write" if controller_error else "failed"
    result = {
        "benchmark": "WorkBench",
        "controller": "read-plan-write-verify-v1",
        "domain": args.domain,
        "task_index": args.task_index,
        "status": status,
        "requires_mutation": requires_mutation,
        "official_score": {"correct": correct, "side_effect": side_effects},
        "metrics": {
            **aggregate_metrics,
            "wall_latency_seconds": round(time.perf_counter() - started, 6),
            "token_budget": args.token_budget,
            "max_tool_calls": args.max_tool_calls,
            "max_latency_seconds": args.max_latency_seconds,
        },
        "phases": phases,
        "tool_calls": len(calls),
        "write_actions": len(write_calls),
        "allowed_tools": len(task_tools),
        "allow_write": allow_write,
        "actions": predicted_actions,
        "final_answer": final_answer,
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "run_dir": str(run_dir),
        "status": result["status"],
        "official_score": result["official_score"],
        "metrics": result["metrics"],
        "phases": {name: {key: value for key, value in phase.items() if key != "metrics"} for name, phase in phases.items()},
        "tool_calls": result["tool_calls"],
        "write_actions": result["write_actions"],
        "allowed_tools": result["allowed_tools"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
