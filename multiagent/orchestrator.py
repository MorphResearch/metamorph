"""End-to-end task-adaptive multi-agent run orchestration."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .evaluator import deterministic_report, enrich_with_evaluator_agent, propose_adjustment
from .lessons import LessonStore
from .morphology import classify_task
from .planner import design_architecture
from .models import AgentResult


Runner = Callable[[str, str], Any]
TaskScorer = Callable[[str], float | bool]


def _unpack_runner_output(value: Any) -> tuple[str, dict[str, Any], float | None]:
    if isinstance(value, dict):
        answer = str(value.get("answer", "") or "")
        metrics = dict(value.get("metrics") or {})
        task_success = value.get("task_success")
        return answer, metrics, float(task_success) if task_success is not None else None
    return str(value or ""), {}, None


class MultiAgentOrchestrator:
    """Run bounded roles, exchange lessons, and propose the next architecture."""

    def __init__(
        self,
        runner: Runner,
        data_dir: Path,
        logger: Any,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
        task_scorer: TaskScorer | None = None,
        max_parallelism: int = 8,
    ) -> None:
        self.runner = runner
        self.data_dir = Path(data_dir)
        self.logger = logger
        self.emit = emit
        self.lessons = LessonStore(self.data_dir)
        self.task_scorer = task_scorer
        self.max_parallelism = max(1, max_parallelism)

    def _record(self, event_type: str, **payload: Any) -> None:
        self.logger.emit(event_type, **payload)
        if self.emit:
            self.emit(event_type, payload)

    def _role_prompt(
        self,
        task: str,
        role: Any,
        morphology: Any,
        outputs: dict[str, str],
        lessons: list[dict[str, Any]],
        history: list[dict[str, str]] | None = None,
        dependencies: list[str] | None = None,
    ) -> str:
        dependency_ids = dependencies if dependencies is not None else role.dependencies
        dependency_context = "\n".join(
            f"[{agent_id}]\n{outputs[agent_id]}" for agent_id in dependency_ids if agent_id in outputs
        ) or "（无前序 Agent 输出）"
        lesson_context = "\n".join(str(lesson.get("summary", "")) for lesson in lessons[-3:]) or "（无历史 lesson）"
        history_context = json.dumps(history or [], ensure_ascii=False)
        return (
            f"你是本任务中的 {role.name}（{role.agent_id}）。\n"
            f"你的职责：{role.objective}\n"
            f"你的关注点：{role.focus}\n"
            f"任务：{task}\n"
            f"任务形态：{json.dumps(morphology.to_dict(), ensure_ascii=False)}\n"
            f"前序 Agent 结果：\n{dependency_context}\n"
            f"历史 lesson：\n{lesson_context}\n"
            f"本会话历史：\n{history_context}\n"
            "请只完成你的职责，明确事实、推断和不确定性；不要重复前序结果。"
        )

    def _score(self, answer: str) -> float:
        if self.task_scorer is None:
            return 1.0 if answer.strip() else 0.0
        try:
            value = self.task_scorer(answer)
            return max(0.0, min(1.0, float(value)))
        except Exception as exc:  # noqa: BLE001 - scoring must not break a run
            self._record("scorer.error", error=str(exc))
            return 0.0

    def _execute_plan(
        self,
        task: str,
        morphology: Any,
        plan: Any,
        lessons: list[dict[str, Any]],
        history: list[dict[str, str]] | None,
        excluded_agent: str | None = None,
        event_prefix: str = "",
    ) -> tuple[dict[str, str], list[AgentResult]]:
        active_roles = [role for role in plan.roles if role.agent_id != excluded_agent]
        active_ids = {role.agent_id for role in active_roles}
        pending = {role.agent_id: role for role in active_roles}
        outputs: dict[str, str] = {}
        results: list[AgentResult] = []

        while pending:
            ready = [
                role for role in pending.values()
                if all(dep in outputs for dep in role.dependencies if dep in active_ids)
            ]
            if not ready:
                for role in list(pending.values()):
                    result = AgentResult(
                        role.agent_id, role.name, "", [dep for dep in role.dependencies if dep in active_ids],
                        False, "cyclic or unresolved dependency", {"success": False}, 0.0,
                    )
                    results.append(result)
                    self._record(f"{event_prefix}agent.completed", agent=result.to_dict())
                    pending.pop(role.agent_id, None)
                break

            def execute(role: Any) -> tuple[Any, str, dict[str, Any], float | None, str | None]:
                dependencies = [dep for dep in role.dependencies if dep in active_ids]
                try:
                    raw = self.runner(
                        self._role_prompt(task, role, morphology, outputs, lessons, history, dependencies),
                        f"{event_prefix}{role.agent_id}",
                    )
                    answer, metrics, task_success = _unpack_runner_output(raw)
                    return role, answer, metrics, task_success, None
                except Exception as exc:  # noqa: BLE001 - one failed role remains diagnosable
                    return role, "", {"success": False}, 0.0, str(exc)

            # All roles in this layer have their dependencies satisfied, so
            # they can execute concurrently without sharing mutable outputs.
            with ThreadPoolExecutor(max_workers=min(self.max_parallelism, len(ready))) as pool:
                futures = {pool.submit(execute, role): role for role in ready}
                layer_results: dict[str, AgentResult] = {}
                for future in as_completed(futures):
                    role, answer, metrics, task_success, error = future.result()
                    dependencies = [dep for dep in role.dependencies if dep in active_ids]
                    result = AgentResult(
                        role.agent_id,
                        role.name,
                        answer,
                        dependencies,
                        error is None and bool(answer),
                        error,
                        metrics,
                        task_success,
                    )
                    layer_results[role.agent_id] = result

            # Preserve plan order for reproducible evidence and final fallback.
            for role in ready:
                result = layer_results[role.agent_id]
                pending.pop(role.agent_id, None)
                results.append(result)
                outputs[role.agent_id] = result.answer
                self._record(f"{event_prefix}agent.completed", agent=result.to_dict())

        return outputs, results

    def run(
        self,
        task: str,
        source_run: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        morphology = classify_task(task)
        prior_lessons = self.lessons.recent()
        plan = design_architecture(task, morphology, prior_lessons)
        self._record("architecture.designed", morphology=morphology.to_dict(), architecture=plan.to_dict())

        baseline_started = time.perf_counter()
        outputs, results = self._execute_plan(task, morphology, plan, prior_lessons, history)
        baseline_latency = time.perf_counter() - baseline_started

        baseline_answer = outputs.get("synthesizer") or (results[-1].answer if results else "")
        baseline_score = self._score(baseline_answer)
        ablation_results: list[dict[str, Any]] = []
        for agent_id in (role.agent_id for role in plan.roles):
            ablated_outputs, ablated_agents = self._execute_plan(
                task,
                morphology,
                plan,
                prior_lessons,
                history,
                excluded_agent=agent_id,
                event_prefix=f"ablation_without_{agent_id}.",
            )
            ablated_answer = ablated_outputs.get("synthesizer") or (ablated_agents[-1].answer if ablated_agents else "")
            ablated_score = self._score(ablated_answer)
            ablation_results.append({
                "agent_id": agent_id,
                "baseline_task_success": baseline_score,
                "ablated_task_success": ablated_score,
                "performance_delta": round(ablated_score - baseline_score, 3),
                "ablated_token_cost": sum(int((item.metrics or {}).get("total_tokens", 0) or 0) for item in ablated_agents),
                "ablated_latency_seconds": round(sum(float((item.metrics or {}).get("latency_seconds", 0.0) or 0.0) for item in ablated_agents), 6),
                "ablated_tool_calls": sum(int((item.metrics or {}).get("tool_calls", 0) or 0) for item in ablated_agents),
            })

        report = deterministic_report(
            plan,
            results,
            ablation_results,
            task_success_score=baseline_score,
            latency_seconds=baseline_latency,
        )
        report = enrich_with_evaluator_agent(report, plan, results, self.runner)
        self._record("contribution.evaluated", report=report.to_dict())
        adjustment = propose_adjustment(plan, report, morphology.complexity)
        self._record("architecture.adjusted", proposal=adjustment)

        final_answer = outputs.get("synthesizer") or (results[-1].answer if results else "")
        lesson = {
            "task_kind": morphology.task_kind,
            "summary": f"{plan.strategy}: measured {len(results)} roles; next architecture is reviewable, not auto-applied.",
            "successful_pattern": "；".join(item.role for item in results if item.success),
            "failure_pattern": "；".join(item.agent_id for item in results if not item.success) or "none observed",
            "next_architecture": adjustment,
            "source_run": source_run,
        }
        self.lessons.append(lesson)
        self._record("lesson.exchanged", lesson=lesson, prior_lessons_used=prior_lessons[-3:])

        return {
            "answer": final_answer,
            "mode": "multiagent",
            "morphology": morphology.to_dict(),
            "architecture": plan.to_dict(),
            "agents": [result.to_dict() for result in results],
            "contribution_report": report.to_dict(),
            "architecture_adjustment": adjustment,
            "lesson": lesson,
        }
