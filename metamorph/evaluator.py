from __future__ import annotations

from .schemas import EvaluationResult


def evaluate_run(*, finished: bool, answer: str, tool_errors: int, steps: int, max_steps: int) -> EvaluationResult:
    checks = {
        "finished": finished,
        "has_answer": bool(answer.strip()),
        "no_tool_errors": tool_errors == 0,
        "within_step_budget": steps <= max_steps,
    }
    score = sum(checks.values()) / len(checks)
    status = "passed" if checks["finished"] and checks["has_answer"] and checks["within_step_budget"] else "failed"
    notes = []
    if tool_errors:
        notes.append(f"{tool_errors} tool error(s) were observed")
    if not finished:
        notes.append("The model did not finish within the step budget")
    return EvaluationResult(status=status, score=score, checks=checks, notes=notes)
