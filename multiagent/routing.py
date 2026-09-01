"""Task-complexity routing shared by benchmark runners.

The routing policy is intentionally separate from the complex execution
controller.  This makes the four-arm comparison explicit:

* S0: always single-agent;
* Complex-only: always the selected complex controller;
* Adaptive: an LLM router selects a controller;
* Oracle: a pre-annotated task label selects a controller.

Oracle labels are loaded from a human-authored file and must never be derived
from the benchmark outcome.  The lightweight heuristic in this module is only
for diagnostics and fallback routing; it is not an oracle label.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal


Route = Literal["single_agent", "complex"]

ROUTING_CONDITIONS = {
    "S0": "always use the single-agent controller",
    "Complex-only": "always use the selected complex controller",
    "Adaptive": "planner/router selects single-agent or complex controller",
    "Oracle": "human-authored complexity label selects the controller",
}

LEGACY_CONDITIONS = {
    "S1": "fixed read-plan-write-verify controller",
    "S2": "adaptive planner with minimum sufficient retrieval",
    "S3": "S2 plus a read-only causal shadow phase",
    "S4": "S3 plus cross-task lesson context",
}

_COMPLEX_TERMS = (
    "all",
    "each",
    "if",
    "unless",
    "before",
    "after",
    "then",
    "first",
    "last",
    "earliest",
    "latest",
    "multiple",
    "every",
    "过去",
    "如果",
    "除非",
    "之前",
    "之后",
    "然后",
    "所有",
    "每个",
    "第一个",
    "最后一个",
    "最早",
    "最晚",
)
_WRITE_TERMS = (
    "create",
    "delete",
    "remove",
    "cancel",
    "update",
    "change",
    "modify",
    "send",
    "forward",
    "reply",
    "add",
    "book",
    "move",
    "创建",
    "删除",
    "取消",
    "更新",
    "修改",
    "发送",
    "添加",
    "预订",
    "移动",
)


def task_features(task: str, *, domain_count: int = 1) -> dict[str, Any]:
    """Extract transparent, outcome-independent routing features."""

    text = task.lower()
    def present(term: str) -> bool:
        # English control words need token boundaries ("if" occurs inside
        # words such as "qualified"); Chinese markers are naturally matched
        # as substrings.
        if term.isascii() and term.replace("-", "").isalpha():
            return bool(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text))
        return term in text

    complex_hits = [term for term in _COMPLEX_TERMS if present(term)]
    write_hits = [term for term in _WRITE_TERMS if present(term)]
    conditional = bool(re.search(r"\b(if|unless|when|whether)\b|如果|除非|是否", text))
    multi_domain = domain_count > 1
    predicted_steps = 1 + int(bool(write_hits)) + int(bool(complex_hits)) + int(multi_domain)
    return {
        "task_length": len(task),
        "domain_count": domain_count,
        "complexity_terms": sorted(set(complex_hits)),
        "write_terms": sorted(set(write_hits)),
        "has_condition": conditional,
        "has_write": bool(write_hits),
        "predicted_steps": predicted_steps,
    }


def heuristic_route(task: str, *, domain_count: int = 1) -> tuple[Route, dict[str, Any]]:
    """Return a conservative diagnostic route without using the gold outcome."""

    features = task_features(task, domain_count=domain_count)
    complex_task = (
        features["task_length"] > 180
        or features["domain_count"] > 1
        or features["has_condition"]
        or len(features["complexity_terms"]) >= 2
        or features["predicted_steps"] >= 4
    )
    return ("complex" if complex_task else "single_agent"), features


def load_oracle_labels(path: Path) -> dict[str, str]:
    """Load human-authored ``DOMAIN:INDEX -> simple|complex`` labels."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    labels = payload.get("labels", payload) if isinstance(payload, dict) else None
    if not isinstance(labels, dict):
        raise ValueError(f"Oracle label file must contain a labels object: {path}")
    normalized: dict[str, str] = {}
    for key, value in labels.items():
        label = str(value).strip().lower()
        if label not in {"simple", "complex"}:
            raise ValueError(f"Oracle label for {key!r} must be simple or complex")
        normalized[str(key)] = label
    return normalized
