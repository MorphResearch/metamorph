from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ALLOWED_ACTIONS = {"list_files", "read_file", "write_file", "finish"}


@dataclass(frozen=True)
class Decision:
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    answer: str = ""
    summary: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Decision":
        action = value.get("action")
        if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported action: {action!r}")
        arguments = value.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("Decision arguments must be an object")
        return cls(
            action=action,
            arguments=arguments,
            answer=str(value.get("answer", "")),
            summary=str(value.get("summary", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    score: float
    checks: dict[str, bool]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
