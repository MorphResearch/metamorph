"""Task-adaptive multi-agent orchestration for Metamorph."""

from .models import (
    AgentArtifact,
    AgentResult,
    AgentRole,
    ArchitecturePlan,
    ArtifactContract,
    BudgetPolicy,
    ContributionReport,
    Lesson,
    TaskMorphology,
)
from .orchestrator import MultiAgentOrchestrator

__all__ = [
    "AgentResult",
    "AgentArtifact",
    "AgentRole",
    "ArchitecturePlan",
    "ArtifactContract",
    "BudgetPolicy",
    "ContributionReport",
    "Lesson",
    "MultiAgentOrchestrator",
    "TaskMorphology",
]
