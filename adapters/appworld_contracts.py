"""Strict, versioned contracts for the fixed AppWorld S3 scaffold."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError


SCHEMA_VERSION = "appworld.fixed-s3.v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannedAction(StrictModel):
    app: str = Field(min_length=1)
    api: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str = Field(min_length=1)
    expected_state_change: str = Field(min_length=1)


class PlannerArtifact(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    status: Literal["READY", "BLOCKED"]
    task_interpretation: str = Field(min_length=1)
    ordered_actions: list[PlannedAction] = Field(default_factory=list)
    verification_criteria: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.status == "READY" and not self.verification_criteria:
            raise ValueError("READY planner artifact requires verification_criteria")
        if self.status == "BLOCKED" and not self.blocked_reason:
            raise ValueError("BLOCKED planner artifact requires blocked_reason")


class ExecutedAction(StrictModel):
    app: str = Field(min_length=1)
    api: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    observation: str = ""
    success: bool


class ExecutorArtifact(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    status: Literal["COMPLETED", "PARTIAL", "BLOCKED", "FAILED"]
    executed_actions: list[ExecutedAction] = Field(default_factory=list)
    claimed_state_changes: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    final_answer: Any | None = None


class VerificationCheck(StrictModel):
    criterion: str = Field(min_length=1)
    evidence: str = ""
    passed: bool


class VerifierArtifact(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    status: Literal["VERIFIED", "NOT_VERIFIED", "BLOCKED"]
    checks: list[VerificationCheck] = Field(default_factory=list)
    discrepancies: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.status == "NOT_VERIFIED" and not self.repair_instructions:
            raise ValueError("NOT_VERIFIED verifier artifact requires repair_instructions")


class ToolSelectionArtifact(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    tools: list[str] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1)


class TypedNullArtifact(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    artifact_type: str
    source: str
    target: str
    valid: Literal[False] = False
    value: None = None
    reason: str


ContractT = TypeVar("ContractT", bound=BaseModel)


def parse_strict_json(text: str, contract: type[ContractT]) -> ContractT:
    """Parse an exact JSON object; markdown fences and surrounding prose are invalid."""

    value = json.loads(text.strip())
    if not isinstance(value, dict):
        raise ValueError("artifact must be one JSON object")
    return contract.model_validate(value)


def validate_artifact(text: str, contract: type[ContractT]) -> tuple[ContractT | None, list[str]]:
    try:
        return parse_strict_json(text, contract), []
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        return None, [str(exc)]


def typed_null(source: str, target: str, artifact_type: str) -> TypedNullArtifact:
    return TypedNullArtifact(
        artifact_type=artifact_type,
        source=source,
        target=target,
        reason=f"causal intervention masked {source} -> {target}",
    )


def canonical_json(value: BaseModel | dict[str, Any] | list[Any]) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def artifact_hash(value: BaseModel | dict[str, Any] | list[Any] | str) -> str:
    text = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


CONTRACTS: dict[str, type[BaseModel]] = {
    "planner": PlannerArtifact,
    "executor": ExecutorArtifact,
    "repair": ExecutorArtifact,
    "verifier": VerifierArtifact,
    "tool_selector": ToolSelectionArtifact,
}
