"""Run τ² tasks through the adaptive routing arms and legacy S0--S4 ablations."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from loguru import logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAU2_ROOT = PROJECT_ROOT / "benchmarks" / "tau2-bench"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TAU2_ROOT / "src"))

logger.remove()
logger.add(sys.stderr, level="ERROR")

from adapters.tau2_adapter import CONDITIONS, Tau2AdapterAgent  # noqa: E402
from multiagent.routing import ROUTING_CONDITIONS, load_oracle_labels  # noqa: E402
from tau2.data_model.simulation import TerminationReason  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation  # noqa: E402
from tau2.orchestrator.orchestrator import Orchestrator  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.user.user_simulator import UserSimulator  # noqa: E402
from tau2.utils.llm_utils import get_token_usage  # noqa: E402


def run_one(
    *,
    condition: str,
    domain: str,
    task_id: str,
    agent_model: str,
    user_model: str,
    max_steps: int,
    max_errors: int,
    lesson_context: str,
    complex_condition: str,
    route_override: str | None,
) -> dict:
    task_loader = registry.get_tasks_loader(domain)
    tasks = task_loader()
    task = next((item for item in tasks if item.id == task_id), None)
    if task is None:
        raise ValueError(f"Task {task_id!r} not found in domain {domain!r}")
    environment = registry.get_env_constructor(domain)()
    agent = Tau2AdapterAgent(
        condition=condition,
        environment=environment,
        llm=agent_model,
        llm_args={"temperature": 0.0},
        lesson_context=lesson_context,
        task_context=str(task.user_scenario),
        complex_condition=complex_condition,
        route_override=route_override,
    )
    user = UserSimulator(
        # Match tau2.run.run_task: the official simulator receives the full
        # scenario string, including persona and structured instructions.
        instructions=str(task.user_scenario),
        llm=user_model,
        llm_args={"temperature": 0.0},
    )
    orchestrator = Orchestrator(
        domain=domain,
        agent=agent,
        user=user,
        environment=environment,
        task=task,
        max_steps=max_steps,
        max_errors=max_errors,
        seed=300,
    )
    started = time.perf_counter()
    simulation = orchestrator.run()
    evaluation_error = None
    try:
        simulation.reward_info = evaluate_simulation(
            domain=domain,
            task=task,
            simulation=simulation,
            evaluation_type=EvaluationType.ALL,
            solo_mode=False,
        )
    except Exception as exc:  # Keep smoke results diagnosable on evaluator failures.
        evaluation_error = f"{type(exc).__name__}: {exc}"
    usage = get_token_usage(simulation.messages)
    assistant_tool_calls = sum(
        len(message.tool_calls or [])
        for message in simulation.messages
        if getattr(message, "role", None) == "assistant" and message.is_tool_call()
    )
    result = {
        "benchmark": "τ²-Bench",
        "adapter": "Tau2AdapterAgent",
        "condition": condition,
        "condition_definition": CONDITIONS[condition],
        "execution_condition": agent.execution_condition,
        "complex_condition": complex_condition if condition in ROUTING_CONDITIONS else None,
        "routing": {
            "route": orchestrator.agent_state.route if orchestrator.agent_state else route_override,
            "decision": orchestrator.agent_state.route_decision if orchestrator.agent_state else None,
            "source": "human_annotation" if condition == "Oracle" else "planner" if condition == "Adaptive" else "fixed",
        } if condition in ROUTING_CONDITIONS else None,
        "domain": domain,
        "task_id": task_id,
        "official_reward": simulation.reward_info.reward if simulation.reward_info else 0.0,
        "reward_basis": simulation.reward_info.reward_basis if simulation.reward_info else task.evaluation_criteria.reward_basis,
        "evaluation_error": evaluation_error,
        "termination_reason": simulation.termination_reason,
        "terminated_early": simulation.termination_reason
        in {TerminationReason.MAX_STEPS.value, TerminationReason.TOO_MANY_ERRORS.value},
        "duration_seconds": round(simulation.duration, 6),
        "wall_latency_seconds": round(time.perf_counter() - started, 6),
        "token_usage": usage,
        "assistant_tool_calls": assistant_tool_calls,
        "messages": len(simulation.messages),
        "assistant_actions": [
            {"name": call.name, "arguments": call.arguments}
            for message in simulation.messages
            if getattr(message, "role", None) == "assistant" and message.is_tool_call()
            for call in (message.tool_calls or [])
        ],
        "adapter_events": agent.events,
        "replay": orchestrator.agent_state.replay if orchestrator.agent_state else None,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="mock")
    parser.add_argument("--task-id", default="create_task_1")
    parser.add_argument("--agent-model", default="deepseek/deepseek-chat")
    parser.add_argument("--user-model", default="deepseek/deepseek-chat")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-errors", type=int, default=5)
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=list(CONDITIONS),
        default=list(ROUTING_CONDITIONS),
    )
    parser.add_argument(
        "--complex-condition",
        choices=("S1", "S2", "S3", "S4"),
        default="S3",
        help="Fixed complex controller used by the three routing arms.",
    )
    parser.add_argument(
        "--oracle-label-file",
        type=Path,
        default=PROJECT_ROOT / "config" / "task_complexity_labels.json",
        help="Human-authored DOMAIN:TASK_ID -> simple|complex labels for Oracle.",
    )
    parser.add_argument("--lesson-context", default="Previous lesson: verify the target user before mutation.")
    parser.add_argument(
        "--output",
        type=Path,
        default=TAU2_ROOT / "data" / "simulations" / "metamorph_adapter_smoke.json",
    )
    args = parser.parse_args()
    oracle_labels = load_oracle_labels(args.oracle_label_file.resolve()) if "Oracle" in args.conditions else None

    results = []
    for condition in args.conditions:
        print(f"Running {condition} on {args.domain}:{args.task_id}")
        route_override = None
        if condition == "Oracle":
            key = f"{args.domain}:{args.task_id}"
            if oracle_labels is None or key not in oracle_labels:
                raise ValueError(f"Missing Oracle label for {key}; add it to --oracle-label-file")
            route_override = "single_agent" if oracle_labels[key] == "simple" else "complex"
        results.append(
            run_one(
                condition=condition,
                domain=args.domain,
                task_id=args.task_id,
                agent_model=args.agent_model,
                user_model=args.user_model,
                max_steps=args.max_steps,
                max_errors=args.max_errors,
                lesson_context=args.lesson_context,
                complex_condition=args.complex_condition,
                route_override=route_override,
            )
        )
        latest = results[-1]
        print(
            f"  reward={latest['official_reward']} "
            f"termination={latest['termination_reason']} "
            f"tool_calls={latest['assistant_tool_calls']}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    print(f"Saved {len(results)} results to {args.output}")


if __name__ == "__main__":
    main()
