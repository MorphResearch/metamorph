"""Contribution, error-correction, and communication analysis."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .models import AgentContribution, AgentResult, ArchitecturePlan, ContributionReport


_WORD_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")
_CORRECTION_TERMS = ("error", "wrong", "risk", "missing", "inconsistent", "错误", "风险", "遗漏", "不一致", "纠正", "验证")


def _words(text: str) -> set[str]:
    return {word.lower() for word in _WORD_RE.findall(text) if len(word) > 1}


def _jaccard(left: str, right: str) -> float:
    a, b = _words(left), _words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def deterministic_report(plan: ArchitecturePlan, results: list[AgentResult]) -> ContributionReport:
    """Produce reproducible proxy measurements before an LLM judge is added."""

    by_id = {result.agent_id: result for result in results}
    contributions: list[AgentContribution] = []
    pairwise: list[dict[str, Any]] = []
    for result in results:
        peers = [other for other in results if other.agent_id != result.agent_id]
        max_similarity = max((_jaccard(result.answer, peer.answer) for peer in peers), default=0.0)
        dependency_text = " ".join(by_id[dep].answer for dep in result.dependencies if dep in by_id)
        usefulness = _jaccard(dependency_text, result.answer) if dependency_text else (0.7 if result.answer else 0.0)
        correction = 1.0 if any(term in result.answer.lower() for term in _CORRECTION_TERMS) else 0.0
        distinctiveness = _clamp(1.0 - max_similarity)
        redundancy = _clamp(max_similarity)
        marginal = _clamp(0.45 * (1.0 if result.success and result.answer else 0.0) + 0.35 * distinctiveness + 0.2 * correction)
        notes = []
        if correction:
            notes.append("输出包含可识别的核验或纠错信号。")
        if redundancy >= 0.75:
            notes.append("与其他 Agent 输出高度相似，建议考虑合并。")
        if not result.answer:
            notes.append("没有产生有效输出。")
        contributions.append(AgentContribution(result.agent_id, marginal, correction, distinctiveness, redundancy, _clamp(usefulness), notes))

    for index, left in enumerate(results):
        for right in results[index + 1:]:
            similarity = _clamp(_jaccard(left.answer, right.answer))
            if similarity >= 0.5:
                pairwise.append({"left": left.agent_id, "right": right.agent_id, "redundancy": similarity})

    return ContributionReport(contributions, pairwise)


def _extract_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def enrich_with_evaluator_agent(
    report: ContributionReport,
    plan: ArchitecturePlan,
    results: list[AgentResult],
    runner: Callable[[str, str], str] | None,
) -> ContributionReport:
    """Ask a dedicated evaluator role for a structured second opinion.

    If the provider does not return valid JSON, the deterministic report is
    retained.  This makes the evaluator useful without making the run brittle.
    """

    if runner is None:
        return report
    payload = {
        "architecture": plan.to_dict(),
        "results": [result.to_dict() for result in results],
        "baseline_report": report.to_dict(),
    }
    prompt = (
        "你是独立的 multi-agent contribution evaluator。请评估每个 Agent 是否带来新能力、"
        "是否纠正错误、错误是否与其他 Agent 不同、上下游信息是否有用或冗余。"
        "只返回 JSON，不要 markdown，格式为 {\"summary\": str, \"recommendations\": [str], "
        "\"agent_findings\": [{\"agent_id\": str, \"finding\": str}]}。\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    answer = runner(prompt, "evaluator")
    parsed = _extract_json(answer)
    report.evaluator_answer = answer
    report.evaluator_source = "llm+deterministic" if parsed else "deterministic-fallback"
    if parsed:
        report.evaluator_answer = json.dumps(parsed, ensure_ascii=False)
    return report


def propose_adjustment(plan: ArchitecturePlan, report: ContributionReport, complexity: str) -> dict[str, Any]:
    """Turn measurements into a reviewable next-architecture proposal."""

    contributions = {item.agent_id: item for item in report.agents}
    operations: list[dict[str, Any]] = []
    for agent_id, item in contributions.items():
        if agent_id != "synthesizer" and item.marginal_contribution < 0.22:
            operations.append({"action": "remove_or_merge", "agent_id": agent_id, "reason": "low measured marginal contribution"})
    for pair in report.pairwise_redundancy:
        if pair["redundancy"] >= 0.75:
            operations.append({"action": "merge", "agents": [pair["left"], pair["right"]], "reason": "high output redundancy"})
    if complexity == "high" and not any(item.error_correction > 0 for item in report.agents):
        operations.append({"action": "add", "role": "verifier", "reason": "high-complexity task lacks correction signal"})
    if not operations:
        operations.append({"action": "keep", "reason": "no strong evidence for structural change"})

    return {
        "status": "proposed",
        "operations": operations,
        "requires_human_approval": True,
        "safety_note": "本建议只影响下一轮任务规划，不自动修改代码、权限或工具。",
    }
