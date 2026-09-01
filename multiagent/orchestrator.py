"""Causally governed, budgeted multi-agent scaffold evolution."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .contracts import artifact_for_prompt, build_artifact, compile_plan, typed_null_artifact
from .evaluator import deterministic_report, enrich_with_evaluator_agent, propose_adjustment
from .lessons import LessonStore
from .models import AgentArtifact, AgentResult, BudgetPolicy
from .morphology import classify_task
from .planner import apply_active_lessons, design_architecture
from .utility import BudgetLedger, aggregate_metrics, budget_allows, score_utility


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
    """Execute a compiled DAG, audit local edges, and admit evidence-backed lessons."""

    def __init__(
        self,
        runner: Runner,
        data_dir: Path,
        logger: Any,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
        task_scorer: TaskScorer | None = None,
        max_parallelism: int = 8,
        budget_policy: BudgetPolicy | None = None,
        enable_evaluator: bool = True,
    ) -> None:
        self.runner = runner
        self.data_dir = Path(data_dir)
        self.logger = logger
        self.emit = emit
        self.lessons = LessonStore(self.data_dir)
        self.task_scorer = task_scorer
        self.max_parallelism = max(1, max_parallelism)
        self.budget_policy = budget_policy or BudgetPolicy()
        self.enable_evaluator = enable_evaluator
        self.budget_ledger = BudgetLedger(self.budget_policy.max_total_tokens)

    def _record(self, event_type: str, **payload: Any) -> None:
        self.logger.emit(event_type, **payload)
        if self.emit:
            self.emit(event_type, payload)

    def _role_prompt(
        self,
        task: str,
        role: Any,
        morphology: Any,
        artifacts: dict[str, AgentArtifact],
        lessons: list[dict[str, Any]],
        history: list[dict[str, str]] | None = None,
        dependencies: list[str] | None = None,
        masked_edges: set[tuple[str, str]] | None = None,
        role_by_id: dict[str, Any] | None = None,
    ) -> str:
        dependency_ids = dependencies if dependencies is not None else role.dependencies
        masked_edges = masked_edges or set()
        role_by_id = role_by_id or {}
        dependency_blocks: list[str] = []
        for agent_id in dependency_ids:
            if (agent_id, role.agent_id) in masked_edges:
                source_role = role_by_id.get(agent_id)
                contract = source_role.output_contract if source_role else role.output_contract
                artifact = typed_null_artifact(agent_id, role.agent_id, contract)
            else:
                artifact = artifacts.get(agent_id)
            if artifact is not None:
                dependency_blocks.append(f"[{agent_id} | {artifact.artifact_type}]\n{artifact_for_prompt(artifact)}")
        dependency_context = "\n".join(dependency_blocks) or "（无前序 Agent 输出）"
        lesson_context = json.dumps([
            {"lesson_id": item.get("lesson_id"), "dag_edit": item.get("dag_edit"), "strength": item.get("strength")}
            for item in lessons[-3:]
        ], ensure_ascii=False) if lessons else "（无 Active lesson）"
        history_context = json.dumps(history or [], ensure_ascii=False)
        return (
            f"你是本任务中的 {role.name}（{role.agent_id}）。\n"
            f"你的职责：{role.objective}\n"
            f"你的关注点：{role.focus}\n"
            f"输出契约：{json.dumps(role.output_contract.to_dict(), ensure_ascii=False)}\n"
            f"任务：{task}\n"
            f"任务形态：{json.dumps(morphology.to_dict(), ensure_ascii=False)}\n"
            f"前序 Agent artifacts：\n{dependency_context}\n"
            f"Active lessons：\n{lesson_context}\n"
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

    @staticmethod
    def _answer_from_artifacts(plan: Any, artifacts: dict[str, AgentArtifact], results: list[AgentResult]) -> str:
        synthesizer = artifacts.get("synthesizer")
        if synthesizer is not None:
            return synthesizer.content
        for role in reversed(plan.roles):
            artifact = artifacts.get(role.agent_id)
            if artifact is not None:
                return artifact.content
        return results[-1].answer if results else ""

    @staticmethod
    def _descendants(plan: Any, root: str) -> set[str]:
        children: dict[str, set[str]] = {role.agent_id: set() for role in plan.roles}
        for role in plan.roles:
            for dependency in role.dependencies:
                children.setdefault(dependency, set()).add(role.agent_id)
        seen = {root}
        frontier = [root]
        while frontier:
            current = frontier.pop()
            for child in children.get(current, set()):
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return seen

    def _execute_plan(
        self,
        task: str,
        morphology: Any,
        plan: Any,
        lessons: list[dict[str, Any]],
        history: list[dict[str, str]] | None,
        excluded_agent: str | None = None,
        event_prefix: str = "",
        initial_artifacts: dict[str, AgentArtifact] | None = None,
        selected_agent_ids: set[str] | None = None,
        masked_edges: set[tuple[str, str]] | None = None,
    ) -> tuple[dict[str, AgentArtifact], list[AgentResult]]:
        """Execute a full DAG or replay only a downstream subgraph.

        ``initial_artifacts`` freeze unaffected context during a causal replay;
        ``masked_edges`` replaces exactly one dependency with typed null input.
        """

        selected_ids = selected_agent_ids or {role.agent_id for role in plan.roles}
        active_roles = [role for role in plan.roles if role.agent_id in selected_ids and role.agent_id != excluded_agent]
        active_ids = {role.agent_id for role in active_roles}
        pending = {role.agent_id: role for role in active_roles}
        artifacts = dict(initial_artifacts or {})
        results: list[AgentResult] = []
        role_by_id = {role.agent_id: role for role in plan.roles}
        masked_edges = masked_edges or set()

        while pending:
            ready = [
                role for role in pending.values()
                if all(dependency in artifacts for dependency in role.dependencies)
            ]
            if not ready:
                for role in list(pending.values()):
                    artifact = build_artifact(role.agent_id, "", role.output_contract)
                    result = AgentResult(
                        role.agent_id,
                        role.name,
                        "",
                        list(role.dependencies),
                        False,
                        "cyclic or unresolved dependency",
                        {"success": False},
                        0.0,
                        artifact,
                    )
                    results.append(result)
                    artifacts[role.agent_id] = artifact
                    self._record(f"{event_prefix}agent.completed", agent=result.to_dict())
                    pending.pop(role.agent_id, None)
                break

            def execute(role: Any) -> tuple[Any, str, dict[str, Any], float | None, str | None, AgentArtifact]:
                reservation_id: str | None = None
                try:
                    started = time.perf_counter()
                    prompt = self._role_prompt(task, role, morphology, artifacts, lessons, history, role.dependencies, masked_edges, role_by_id)
                    reservation_id = f"{event_prefix}{role.agent_id}:{time.time_ns()}"
                    estimate = (len(prompt) + 2) // 3 + self.budget_policy.max_completion_tokens
                    if not self.budget_ledger.reserve(reservation_id, estimate):
                        artifact = build_artifact(role.agent_id, "", role.output_contract)
                        return role, "", {"success": False, "budget_stopped": True}, 0.0, "global token budget reservation denied", artifact
                    raw = self.runner(
                        prompt,
                        f"{event_prefix}{role.agent_id}",
                    )
                    answer, metrics, task_success = _unpack_runner_output(raw)
                    self.budget_ledger.settle(reservation_id, int(metrics.get("total_tokens", 0) or 0))
                    metrics.setdefault("latency_seconds", round(time.perf_counter() - started, 6))
                    artifact = build_artifact(role.agent_id, answer, role.output_contract)
                    return role, answer, metrics, task_success, None, artifact
                except Exception as exc:  # noqa: BLE001 - one failed role remains diagnosable
                    if reservation_id is not None:
                        self.budget_ledger.settle(reservation_id, 0)
                    artifact = build_artifact(role.agent_id, "", role.output_contract)
                    return role, "", {"success": False}, 0.0, str(exc), artifact

            with ThreadPoolExecutor(max_workers=min(self.max_parallelism, len(ready))) as pool:
                futures = {pool.submit(execute, role): role for role in ready}
                layer_results: dict[str, AgentResult] = {}
                for future in as_completed(futures):
                    role, answer, metrics, task_success, error, artifact = future.result()
                    result = AgentResult(
                        role.agent_id,
                        role.name,
                        answer,
                        list(role.dependencies),
                        error is None and artifact.valid,
                        error,
                        metrics,
                        task_success,
                        artifact,
                    )
                    layer_results[role.agent_id] = result

            for role in ready:
                result = layer_results[role.agent_id]
                pending.pop(role.agent_id, None)
                results.append(result)
                artifacts[role.agent_id] = result.artifact or build_artifact(role.agent_id, "", role.output_contract)
                self._record(f"{event_prefix}artifact.validated", artifact=artifacts[role.agent_id].to_dict(), target=role.agent_id)
                self._record(f"{event_prefix}agent.completed", agent=result.to_dict())

        return artifacts, results

    @staticmethod
    def _add_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        return {
            "token_cost": int(left.get("token_cost", 0) or 0) + int(right.get("token_cost", 0) or 0),
            "critical_path_latency": float(left.get("critical_path_latency", 0.0) or 0.0) + float(right.get("critical_path_latency", 0.0) or 0.0),
            "tool_calls": int(left.get("tool_calls", 0) or 0) + int(right.get("tool_calls", 0) or 0),
            "safety_incidents": int(left.get("safety_incidents", 0) or 0) + int(right.get("safety_incidents", 0) or 0),
            "regression_risk": float(left.get("regression_risk", 0.0) or 0.0) + float(right.get("regression_risk", 0.0) or 0.0),
        }

    def _audit_edges(
        self,
        task: str,
        morphology: Any,
        plan: Any,
        compiled: dict[str, Any],
        baseline_artifacts: dict[str, AgentArtifact],
        baseline_results: list[AgentResult],
        baseline_quality: float,
        baseline_metrics: dict[str, Any],
        prior_lessons: list[dict[str, Any]],
        history: list[dict[str, str]] | None,
        source_run: str | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
        """Run bounded, fixed-context edge interventions and admit evidence."""

        baseline_utility = score_utility(baseline_quality, baseline_metrics, self.budget_policy)
        cumulative_metrics = dict(baseline_metrics)
        audits: list[dict[str, Any]] = []
        admissions: list[dict[str, Any]] = []
        best_repair: dict[str, Any] | None = None
        by_id = {item.agent_id: item for item in baseline_results}
        baseline_budget_stopped = any(bool((item.metrics or {}).get("budget_stopped")) for item in baseline_results)

        for edge in compiled["edges"][:self.budget_policy.max_causal_audits]:
            if baseline_budget_stopped:
                audit = {"edge": edge, "status": "stopped", "reason": ["global token budget reservation denied"], "downstream": []}
                audits.append(audit)
                self._record("causal_audit.stopped", audit=audit)
                continue
            downstream = self._descendants(plan, edge["target"])
            estimated = aggregate_metrics(plan, [by_id[item] for item in downstream if item in by_id])
            projected = self._add_metrics(cumulative_metrics, estimated)
            allowed, reasons = budget_allows(projected, self.budget_policy)
            if not allowed:
                audit = {"edge": edge, "status": "stopped", "reason": reasons, "downstream": sorted(downstream)}
                audits.append(audit)
                self._record("causal_audit.stopped", audit=audit)
                continue

            started = time.perf_counter()
            replay_artifacts, replay_results = self._execute_plan(
                task,
                morphology,
                plan,
                prior_lessons,
                history,
                event_prefix=f"causal_audit_{edge['source']}_to_{edge['target']}.",
                initial_artifacts={key: value for key, value in baseline_artifacts.items() if key not in downstream},
                selected_agent_ids=downstream,
                masked_edges={(edge["source"], edge["target"])},
            )
            replay_answer = self._answer_from_artifacts(plan, replay_artifacts, replay_results)
            replay_quality = self._score(replay_answer)
            replay_metrics = aggregate_metrics(plan, replay_results, time.perf_counter() - started)
            cumulative_metrics = self._add_metrics(cumulative_metrics, replay_metrics)
            intervention_utility = score_utility(replay_quality, replay_metrics, self.budget_policy)
            edge_effect = baseline_utility.value - intervention_utility.value
            removal_gain = intervention_utility.value - baseline_utility.value
            confidence = abs(removal_gain) - self.budget_policy.uncertainty_penalty
            audit = {
                "edge": edge,
                "status": "completed",
                "downstream": sorted(downstream),
                "baseline_utility": baseline_utility.to_dict(),
                "intervention_utility": intervention_utility.to_dict(),
                "edge_utility_delta": round(edge_effect, 6),
                "removal_utility_gain": round(removal_gain, 6),
                "absolute_effect_lower_bound": round(confidence, 6),
                "replay_metrics": replay_metrics,
            }
            audits.append(audit)
            self._record("causal_audit.completed", audit=audit)

            if confidence <= self.budget_policy.min_utility_lower_bound:
                continue
            operation = "remove_dependency" if removal_gain > 0.0 else "preserve_dependency"
            dag_edit = {"operation": operation, "source": edge["source"], "target": edge["target"]}
            evidence = {
                "utility_delta": abs(removal_gain),
                "utility_lower_bound": confidence,
                "baseline": baseline_utility.to_dict(),
                "intervention": intervention_utility.to_dict(),
            }
            lesson = self.lessons.admit_causal_evidence(
                condition={
                    "task_kind": morphology.task_kind,
                    "strategy": plan.strategy,
                    "tool_intensity": morphology.tool_intensity,
                },
                dag_edit=dag_edit,
                evidence=evidence,
                source_run=source_run,
                artifact_contracts=compiled["contracts"],
            )
            admissions.append(lesson)
            self._record("lesson.admission_decided", lesson=lesson, audit=audit, governor="deterministic_budget_controller")
            if operation == "remove_dependency" and removal_gain - self.budget_policy.uncertainty_penalty > self.budget_policy.min_utility_lower_bound:
                candidate = {"outputs": replay_artifacts, "results": replay_results, "utility": intervention_utility, "audit": audit}
                if best_repair is None or candidate["utility"].value > best_repair["utility"].value:
                    best_repair = candidate

        return audits, best_repair, admissions

    def run(
        self,
        task: str,
        source_run: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        morphology = classify_task(task)
        seed_plan = design_architecture(task, morphology, [])
        lesson_context = {
            "task_kind": morphology.task_kind,
            "strategy": seed_plan.strategy,
            "tool_intensity": morphology.tool_intensity,
        }
        active_lessons, drift_rejections = self.lessons.select_active(lesson_context)
        plan = design_architecture(task, morphology, active_lessons)
        plan, applied_lessons = apply_active_lessons(plan, active_lessons)
        compiled = compile_plan(plan)
        if not compiled["valid"]:
            self._record("dag.rejected", architecture=plan.to_dict(), compilation=compiled)
            return {
                "answer": "",
                "mode": "multiagent",
                "morphology": morphology.to_dict(),
                "architecture": plan.to_dict(),
                "dag_compilation": compiled,
                "error": "DAG compiler rejected the proposed architecture",
            }
        self._record(
            "architecture.designed",
            morphology=morphology.to_dict(),
            architecture=plan.to_dict(),
            dag_compilation=compiled,
            active_lessons=active_lessons,
            applied_lessons=applied_lessons,
            drift_rejections=drift_rejections,
        )

        baseline_started = time.perf_counter()
        artifacts, results = self._execute_plan(task, morphology, plan, active_lessons, history)
        baseline_elapsed = time.perf_counter() - baseline_started
        baseline_answer = self._answer_from_artifacts(plan, artifacts, results)
        baseline_score = self._score(baseline_answer)
        baseline_metrics = aggregate_metrics(plan, results, baseline_elapsed)
        baseline_utility = score_utility(baseline_score, baseline_metrics, self.budget_policy)

        ablation_results: list[dict[str, Any]] = []
        for agent_id in (role.agent_id for role in plan.roles):
            ablated_artifacts, ablated_agents = self._execute_plan(
                task,
                morphology,
                plan,
                active_lessons,
                history,
                excluded_agent=agent_id,
                event_prefix=f"ablation_without_{agent_id}.",
            )
            ablated_answer = self._answer_from_artifacts(plan, ablated_artifacts, ablated_agents)
            ablated_score = self._score(ablated_answer)
            ablated_metrics = aggregate_metrics(plan, ablated_agents)
            ablation_results.append({
                "agent_id": agent_id,
                "baseline_task_success": baseline_score,
                "ablated_task_success": ablated_score,
                "performance_delta": round(ablated_score - baseline_score, 3),
                "ablated_token_cost": ablated_metrics["token_cost"],
                "ablated_latency_seconds": ablated_metrics["critical_path_latency"],
                "ablated_tool_calls": ablated_metrics["tool_calls"],
            })

        audits, repair, admissions = self._audit_edges(
            task,
            morphology,
            plan,
            compiled,
            artifacts,
            results,
            baseline_score,
            baseline_metrics,
            active_lessons,
            history,
            source_run,
        )
        final_artifacts = repair["outputs"] if repair else artifacts
        final_results = repair["results"] if repair else results
        final_answer = self._answer_from_artifacts(plan, final_artifacts, final_results)
        final_utility = repair["utility"] if repair else baseline_utility
        stop_reason = "local repair accepted" if repair else "no positive lower-bound local repair"
        self._record(
            "budget.decision",
            action="repair" if repair else "stop",
            reason=stop_reason,
            policy=self.budget_policy.to_dict(),
            ledger=self.budget_ledger.snapshot(),
            baseline_utility=baseline_utility.to_dict(),
            final_utility=final_utility.to_dict(),
        )

        report = deterministic_report(
            plan,
            results,
            ablation_results,
            task_success_score=baseline_score,
            latency_seconds=baseline_metrics["critical_path_latency"],
        )
        report.causal_audits = audits
        report.utility = {
            "baseline": baseline_utility.to_dict(),
            "final": final_utility.to_dict(),
            "budget_policy": self.budget_policy.to_dict(),
        }
        if self.enable_evaluator:
            report = enrich_with_evaluator_agent(report, plan, results, self.runner)
        else:
            report.evaluator_source = "disabled_by_budget_policy"
        self._record("contribution.evaluated", report=report.to_dict())
        adjustment = propose_adjustment(plan, report, morphology.complexity)
        self._record("architecture.adjusted", proposal=adjustment)

        return {
            "answer": final_answer,
            "mode": "multiagent",
            "morphology": morphology.to_dict(),
            "architecture": plan.to_dict(),
            "dag_compilation": compiled,
            "agents": [result.to_dict() for result in results],
            "contribution_report": report.to_dict(),
            "architecture_adjustment": adjustment,
            "causal_audits": audits,
            "repair": repair["audit"] if repair else None,
            "lesson_admissions": admissions,
            "active_lessons": active_lessons,
            "drift_rejections": drift_rejections,
            "budget_ledger": self.budget_ledger.snapshot(),
        }
