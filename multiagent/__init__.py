"""Task-adaptive multi-agent orchestration for Metamorph."""

from .models import (
    AgentResult,
    AgentRole,
    ArchitecturePlan,
    ContributionReport,
    Lesson,
    TaskMorphology,
)
from .orchestrator import MultiAgentOrchestrator

__all__ = [
    "AgentResult",
    "AgentRole",
    "ArchitecturePlan",
    "ContributionReport",
    "Lesson",
    "MultiAgentOrchestrator",
    "TaskMorphology",
]
