"""Small, deterministic task-morphology classifier.

The classifier is deliberately transparent in v0.1.  It is a policy anchor:
an LLM planner can be added later, but the system always records why a role
was selected and can benchmark the planner against this baseline.
"""

from __future__ import annotations

from .models import TaskMorphology


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def classify_task(task: str) -> TaskMorphology:
    text = task.lower()
    coding = _has_any(text, ("code", "coding", "python", "bug", "debug", "代码", "测试", "程序"))
    research = _has_any(text, ("research", "paper", "literature", "benchmark", "论文", "文献", "研究", "资料"))
    planning = _has_any(text, ("plan", "planning", "strategy", "roadmap", "计划", "方案", "架构", "设计"))
    analysis = _has_any(text, ("analyze", "analysis", "compare", "评估", "分析", "比较", "总结"))
    explicit_steps = _has_any(text, ("then", "after", "before", "step", "首先", "然后", "之后", "步骤"))
    difficult = _has_any(text, ("complex", "difficult", "hard", "long-horizon", "复杂", "困难", "长期"))

    if coding:
        kind = "coding"
    elif research:
        kind = "research"
    elif planning:
        kind = "planning"
    elif analysis:
        kind = "analysis"
    else:
        kind = "general"

    complexity = "high" if difficult or len(task) > 240 else "medium" if len(task) > 80 else "low"
    decomposable = kind in {"coding", "research", "planning", "analysis"} or complexity != "low"
    sequential = explicit_steps or kind in {"coding", "planning"}
    needs_verification = kind in {"coding", "research", "analysis"} or complexity == "high"
    needs_parallelism = kind in {"research", "analysis"} and not sequential
    tool_intensity = "high" if _has_any(text, ("web", "search", "file", "document", "网页", "搜索", "文件", "文档")) else "medium"

    rationale = [f"识别任务类型为 {kind}。", f"任务复杂度为 {complexity}。"]
    if decomposable:
        rationale.append("任务可以拆分为互相依赖或可独立检查的子任务。")
    if needs_verification:
        rationale.append("任务结果需要独立核验或错误分析。")
    if needs_parallelism:
        rationale.append("任务包含可并行探索的部分。")
    if sequential:
        rationale.append("任务存在明显的先后依赖，后续 Agent 需要读取前序结果。")

    return TaskMorphology(
        task_kind=kind,
        complexity=complexity,
        decomposable=decomposable,
        sequential_dependencies=sequential,
        needs_verification=needs_verification,
        needs_parallelism=needs_parallelism,
        tool_intensity=tool_intensity,
        rationale=rationale,
    )
