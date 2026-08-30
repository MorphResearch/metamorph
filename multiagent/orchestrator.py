"""End-to-end task-adaptive multi-agent run orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .evaluator import deterministic_report, enrich_with_evaluator_agent, propose_adjustment
from .lessons import LessonStore
from .morphology import classify_task
from .planner import design_architecture
from .models import AgentResult


Runner = Callable[[str, str], str]


class MultiAgentOrchestrator:
    """Run bounded roles, exchange lessons, and propose the next architecture."""

    def __init__(
        self,
        runner: Runner,
        data_dir: Path,
        logger: Any,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.runner = runner
        self.data_dir = Path(data_dir)
        self.logger = logger
        self.emit = emit
        self.lessons = LessonStore(self.data_dir)

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
    ) -> str:
        dependency_context = "\n".join(
            f"[{agent_id}]\n{outputs[agent_id]}" for agent_id in role.dependencies if agent_id in outputs
        ) or "（无前序 Agent 输出）"
        lesson_context = "\n".join(str(lesson.get("summary", "")) for lesson in lessons[-3:]) or "（无历史 lesson）"
        return (
            f"你是本任务中的 {role.name}（{role.agent_id}）。\n"
            f"你的职责：{role.objective}\n"
            f"你的关注点：{role.focus}\n"
            f"任务：{task}\n"
            f"任务形态：{json.dumps(morphology.to_dict(), ensure_ascii=False)}\n"
            f"前序 Agent 结果：\n{dependency_context}\n"
            f"历史 lesson：\n{lesson_context}\n"
            "请只完成你的职责，明确事实、推断和不确定性；不要重复前序结果。"
        )

    def run(self, task: str, source_run: str | None = None) -> dict[str, Any]:
        morphology = classify_task(task)
        prior_lessons = self.lessons.recent()
        plan = design_architecture(task, morphology, prior_lessons)
        self._record("architecture.designed", morphology=morphology.to_dict(), architecture=plan.to_dict())

        outputs: dict[str, str] = {}
        results: list[AgentResult] = []
        for role in plan.roles:
            try:
                answer = self.runner(self._role_prompt(task, role, morphology, outputs, prior_lessons), role.agent_id)
                result = AgentResult(role.agent_id, role.name, answer or "", role.dependencies, bool(answer))
            except Exception as exc:  # noqa: BLE001 - one failed role should be diagnosable
                result = AgentResult(role.agent_id, role.name, "", role.dependencies, False, str(exc))
            results.append(result)
            outputs[role.agent_id] = result.answer
            self._record("agent.completed", agent=result.to_dict())

        report = deterministic_report(plan, results)
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
