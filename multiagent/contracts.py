"""DAG compilation and typed artifact helpers.

The compiler is deliberately deterministic: an LLM may propose a graph, but
only this module decides whether the graph is executable in the bounded runtime.
"""

from __future__ import annotations

from typing import Any

from .models import AgentArtifact, ArchitecturePlan, ArtifactContract


def compile_plan(plan: ArchitecturePlan) -> dict[str, Any]:
    """Validate role identifiers, dependency references, contracts, and cycles."""

    roles = {role.agent_id: role for role in plan.roles}
    issues: list[str] = []
    if len(roles) != len(plan.roles):
        issues.append("duplicate agent_id")

    edges: list[dict[str, str]] = []
    for role in plan.roles:
        contract = role.output_contract
        if not contract.artifact_type:
            issues.append(f"{role.agent_id}: missing artifact type")
        if "content" not in contract.required_fields:
            issues.append(f"{role.agent_id}: output contract must require content")
        for dependency in role.dependencies:
            if dependency not in roles:
                issues.append(f"{role.agent_id}: unresolved dependency {dependency}")
                continue
            if dependency == role.agent_id:
                issues.append(f"{role.agent_id}: self dependency")
                continue
            edges.append({"source": dependency, "target": role.agent_id})

    indegree = {role_id: 0 for role_id in roles}
    children = {role_id: [] for role_id in roles}
    for edge in edges:
        children[edge["source"]].append(edge["target"])
        indegree[edge["target"]] += 1
    ready = [role_id for role_id, count in indegree.items() if count == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(roles):
        issues.append("dependency graph is cyclic")

    return {
        "valid": not issues,
        "issues": issues,
        "edges": edges,
        "contracts": {role.agent_id: role.output_contract.to_dict() for role in plan.roles},
    }


def build_artifact(producer_id: str, content: str, contract: ArtifactContract) -> AgentArtifact:
    """Create a validated dependency artifact from a role answer."""

    errors: list[str] = []
    if "content" in contract.required_fields and not content.strip():
        errors.append("required field content is empty")
    return AgentArtifact(
        producer_id=producer_id,
        artifact_type=contract.artifact_type,
        content=content,
        required_fields=list(contract.required_fields),
        schema_version=contract.schema_version,
        valid=not errors,
        validation_errors=errors,
    )


def typed_null_artifact(source: str, target: str, contract: ArtifactContract) -> AgentArtifact:
    """Return a schema-preserving intervention for one communication edge."""

    return AgentArtifact(
        producer_id=source,
        artifact_type=contract.artifact_type,
        content="",
        required_fields=list(contract.required_fields),
        schema_version=contract.schema_version,
        valid=False,
        validation_errors=[f"causal intervention masked {source} -> {target}"],
    )


def artifact_for_prompt(artifact: AgentArtifact) -> str:
    """Keep the contract visible to downstream roles without pretending null is data."""

    if artifact.valid:
        return artifact.content
    return (
        f"<typed-null-artifact type={artifact.artifact_type} producer={artifact.producer_id} "
        f"reason={' | '.join(artifact.validation_errors)}>"
    )
