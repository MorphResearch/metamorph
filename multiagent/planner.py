"""Task-morphology-guided role and dependency planning."""

from __future__ import annotations

from typing import Any

from .models import AgentRole, ArchitecturePlan, TaskMorphology


def _lesson_hint(lessons: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for lesson in lessons[-3:]:
        summary = lesson.get("summary") or lesson.get("failure_pattern")
        if summary:
            hints.append(str(summary)[:240])
    return hints


def design_architecture(
    task: str,
    morphology: TaskMorphology,
    lessons: list[dict[str, Any]] | None = None,
) -> ArchitecturePlan:
    """Return a bounded execution graph for one task.

    This is the baseline planner.  Prior lessons are supplied as context and
    can change the chosen strategy in later versions without changing the
    execution protocol.
    """

    lessons = lessons or []
    roles: list[AgentRole]
    if morphology.task_kind == "coding":
        roles = [
            AgentRole("analyst", "任务分析 Agent", "拆解需求、识别约束和验收标准。", "requirements"),
            AgentRole("implementer", "实现 Agent", "根据需求完成实现或提出具体修改方案。", "implementation", ["analyst"]),
            AgentRole("tester", "测试与审查 Agent", "检查实现中的错误、边界情况和可验证性。", "verification", ["analyst", "implementer"]),
            AgentRole("synthesizer", "汇总 Agent", "整合实现和测试结果，给出最终答案与后续行动。", "synthesis", ["analyst", "implementer", "tester"]),
        ]
        strategy = "sequential-coding-review"
    elif morphology.task_kind == "research":
        roles = [
            AgentRole("researcher", "检索研究 Agent", "搜集事实、论文和可核验依据。", "retrieval"),
            AgentRole("critic", "批判分析 Agent", "检查证据质量、冲突和可能的错误。", "critique", ["researcher"]),
            AgentRole("synthesizer", "研究汇总 Agent", "形成结构化结论，区分证据、推断和未知信息。", "synthesis", ["researcher", "critic"]),
        ]
        strategy = "evidence-critique-synthesis"
    elif morphology.task_kind == "planning":
        roles = [
            AgentRole("decomposer", "规划 Agent", "把目标拆成可执行步骤和依赖关系。", "decomposition"),
            AgentRole("executor", "方案 Agent", "为关键步骤提出具体执行方案和资源需求。", "execution", ["decomposer"]),
            AgentRole("reviewer", "风险审查 Agent", "检查方案中的遗漏、冲突和协调成本。", "risk_review", ["decomposer", "executor"]),
            AgentRole("synthesizer", "方案汇总 Agent", "整合规划、执行和风险审查，形成最终方案。", "synthesis", ["decomposer", "executor", "reviewer"]),
        ]
        strategy = "decompose-execute-risk-review"
    elif morphology.needs_verification:
        roles = [
            AgentRole("analyst", "分析 Agent", "独立分析任务并产生候选答案。", "analysis"),
            AgentRole("verifier", "核验 Agent", "寻找分析中的错误和反例。", "verification", ["analyst"]),
            AgentRole("synthesizer", "汇总 Agent", "根据分析和核验结果给出最终答案。", "synthesis", ["analyst", "verifier"]),
        ]
        strategy = "analysis-verification-synthesis"
    else:
        roles = [
            AgentRole("executor", "执行 Agent", "完成任务并说明依据。", "execution"),
            AgentRole("synthesizer", "汇总 Agent", "检查执行结果并给出简洁最终答案。", "synthesis", ["executor"]),
        ]
        strategy = "executor-synthesis"

    rationale = list(morphology.rationale)
    rationale.append(f"采用 {strategy}，角色数量限制为 {len(roles)} 个。")
    hints = _lesson_hint(lessons)
    if hints:
        rationale.append("已将最近 lesson 作为本轮角色设计的上下文。")

    return ArchitecturePlan(
        strategy=strategy,
        rationale=rationale,
        roles=roles,
        prior_lessons_used=lessons[-3:],
    )


def apply_active_lessons(plan: ArchitecturePlan, lessons: list[dict[str, Any]]) -> tuple[ArchitecturePlan, list[dict[str, Any]]]:
    """Apply only safe, explicit DAG patches from already Active lessons.

    Lessons never add tools, permissions, or code changes. Unknown role IDs and
    unsupported edits are rejected so a stale lesson cannot silently reshape a
    new task graph.
    """

    role_by_id = {role.agent_id: role for role in plan.roles}
    applied: list[dict[str, Any]] = []
    for lesson in lessons:
        edit = lesson.get("dag_edit") or {}
        if edit.get("operation") != "remove_dependency":
            continue
        source, target = edit.get("source"), edit.get("target")
        role = role_by_id.get(str(target))
        if not source or role is None or source not in role.dependencies:
            continue
        role.dependencies = [dependency for dependency in role.dependencies if dependency != source]
        applied.append({"lesson_id": lesson.get("lesson_id"), "dag_edit": edit})
    if applied:
        plan.rationale.append(f"已应用 {len(applied)} 条经因果验证的 Active DAG lesson。")
    return plan, applied
