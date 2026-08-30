"""Data contracts for the first task-adaptive multi-agent layer.

These are intentionally plain dataclasses.  They are easy to serialize into
run evidence, and keep the orchestration policy independent from any LLM SDK.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskMorphology:
    """A compact, inspectable description of a task's structure."""

    task_kind: str
    complexity: str
    decomposable: bool
    sequential_dependencies: bool
    needs_verification: bool
    needs_parallelism: bool
    tool_intensity: str
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentRole:
    """One role in an execution graph."""

    agent_id: str
    name: str
    objective: str
    focus: str
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitecturePlan:
    """The architecture selected for one task."""

    strategy: str
    rationale: list[str]
    roles: list[AgentRole]
    prior_lessons_used: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "rationale": self.rationale,
            "roles": [role.to_dict() for role in self.roles],
            "prior_lessons_used": self.prior_lessons_used,
        }


@dataclass
class AgentResult:
    """Observable output of one role execution."""

    agent_id: str
    role: str
    answer: str
    dependencies: list[str] = field(default_factory=list)
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentContribution:
    """Measured contribution signals for one agent."""

    agent_id: str
    marginal_contribution: float
    error_correction: float
    distinctiveness: float
    redundancy: float
    information_usefulness: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContributionReport:
    """Contribution and communication report for one run."""

    agents: list[AgentContribution]
    pairwise_redundancy: list[dict[str, Any]] = field(default_factory=list)
    evaluator_answer: str = ""
    evaluator_source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agents": [agent.to_dict() for agent in self.agents],
            "pairwise_redundancy": self.pairwise_redundancy,
            "evaluator_answer": self.evaluator_answer,
            "evaluator_source": self.evaluator_source,
        }


@dataclass
class Lesson:
    """A durable lesson that can inform a future architecture proposal."""

    task_kind: str
    summary: str
    successful_pattern: str
    failure_pattern: str
    next_architecture: dict[str, Any]
    source_run: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
