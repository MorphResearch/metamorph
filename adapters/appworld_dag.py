"""Typed task-workflow DAGs and replay-safe local interventions.

The controller plane (planner, executor runtime, final evaluator) is not a
causal condition.  This module represents the task-internal graph selected by
that plane.  It is deliberately model- and AppWorld-independent so P0 can
prove its scheduling, artifact, and checkpoint invariants without an API call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from typing import Any, Callable, Literal


Artifact = Any
NodeRunner = Callable[["DAGNode", dict[str, Artifact]], Artifact]
CheckpointWriter = Callable[[str], dict[str, Any]]


def _hash(value: Artifact) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DAGNode:
    """One typed operator in a task workflow.

    ``read_only`` is a safety declaration used by topology interventions: only
    independent read-only branches may be rescheduled between parallel and
    serialized execution.
    """

    id: str
    operator: Literal["inspect", "join", "act", "check", "repair"]
    input_types: dict[str, str] = field(default_factory=dict)
    output_type: str = "Artifact"
    read_only: bool = True
    run_if: Literal["always", "not_verified"] = "always"


@dataclass(frozen=True)
class DAGEdge:
    source: str
    target: str
    input_name: str
    artifact_type: str


@dataclass(frozen=True)
class DAGSpec:
    id: str
    nodes: tuple[DAGNode, ...]
    edges: tuple[DAGEdge, ...]
    # A batch is an execution scheduling declaration.  Only independent,
    # read-only nodes may share a batch and they are run concurrently.
    schedule: tuple[tuple[str, ...], ...]


class DAGCompiler:
    """Validate and compile a small, pre-registered DAG library."""

    def compile(self, spec: DAGSpec) -> DAGSpec:
        nodes = {node.id: node for node in spec.nodes}
        if not spec.id or len(nodes) != len(spec.nodes):
            raise ValueError("DAG requires a non-empty ID and unique node IDs")
        scheduled = [node_id for batch in spec.schedule for node_id in batch]
        if sorted(scheduled) != sorted(nodes) or len(scheduled) != len(set(scheduled)):
            raise ValueError("schedule must contain every node exactly once")
        index = {node_id: batch_index for batch_index, batch in enumerate(spec.schedule) for node_id in batch}
        for edge in spec.edges:
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError(f"edge names unknown node: {edge}")
            if edge.input_name not in nodes[edge.target].input_types:
                raise ValueError(f"edge targets undeclared input {edge.target}.{edge.input_name}")
            expected = nodes[edge.target].input_types[edge.input_name]
            if edge.artifact_type != expected or nodes[edge.source].output_type != edge.artifact_type:
                raise ValueError(f"edge type mismatch on {edge.source} -> {edge.target}")
            if index[edge.source] >= index[edge.target]:
                raise ValueError(f"edge violates acyclic schedule: {edge.source} -> {edge.target}")
        for batch in spec.schedule:
            if len(batch) > 1 and any(not nodes[node_id].read_only for node_id in batch):
                raise ValueError("parallel batches may contain only read-only nodes")
        return spec


def registered_dags() -> dict[str, DAGSpec]:
    """Return the four frozen workflow families used in P0/P1.

    Templates encode only causal structure. Prompt wording, model, tools, and
    budgets remain experiment configuration and are frozen separately.
    """

    inspect = lambda node_id: DAGNode(node_id, "inspect", output_type="PlanArtifact")
    check = lambda node_id: DAGNode(
        node_id, "check", {"execution": "ExecutionArtifact"}, "VerificationArtifact", read_only=True
    )
    act = lambda node_id, inputs: DAGNode(node_id, "act", inputs, "ExecutionArtifact", read_only=False)
    return {
        "G0": DAGSpec("G0", (act("act", {}),), (), (("act",),)),
        "G1": DAGSpec(
            "G1",
            (inspect("inspect"), act("act", {"plan": "PlanArtifact"}), check("check")),
            (
                DAGEdge("inspect", "act", "plan", "PlanArtifact"),
                DAGEdge("act", "check", "execution", "ExecutionArtifact"),
            ),
            (("inspect",), ("act",), ("check",)),
        ),
        "G2": DAGSpec(
            "G2",
            (
                inspect("inspect_a"),
                inspect("inspect_b"),
                DAGNode("join", "join", {"a": "PlanArtifact", "b": "PlanArtifact"}, "PlanArtifact"),
                act("act", {"plan": "PlanArtifact"}),
                check("check"),
            ),
            (
                DAGEdge("inspect_a", "join", "a", "PlanArtifact"),
                DAGEdge("inspect_b", "join", "b", "PlanArtifact"),
                DAGEdge("join", "act", "plan", "PlanArtifact"),
                DAGEdge("act", "check", "execution", "ExecutionArtifact"),
            ),
            (("inspect_a", "inspect_b"), ("join",), ("act",), ("check",)),
        ),
        "G3": DAGSpec(
            "G3",
            (
                inspect("inspect"),
                act("act", {"plan": "PlanArtifact"}),
                check("check"),
                DAGNode("repair", "repair", {"verification": "VerificationArtifact"}, "ExecutionArtifact", read_only=False, run_if="not_verified"),
                DAGNode("final_check", "check", {"execution": "ExecutionArtifact"}, "VerificationArtifact", run_if="not_verified"),
            ),
            (
                DAGEdge("inspect", "act", "plan", "PlanArtifact"),
                DAGEdge("act", "check", "execution", "ExecutionArtifact"),
                DAGEdge("check", "repair", "verification", "VerificationArtifact"),
                DAGEdge("repair", "final_check", "execution", "ExecutionArtifact"),
            ),
            (("inspect",), ("act",), ("check",), ("repair",), ("final_check",)),
        ),
    }


@dataclass(frozen=True)
class Intervention:
    """A pre-registered local structural intervention.

    ``masked_edges`` passes a type-correct null to the target but never rolls
    back the source's already-observed world effects. ``serialize_read_only``
    is valid only for the named parallel batch.
    """

    skipped_nodes: frozenset[str] = frozenset()
    masked_edges: frozenset[tuple[str, str]] = frozenset()
    passthrough_edges: frozenset[tuple[str, str]] = frozenset()
    serialize_read_only: bool = False


class InterventionEngine:
    def validate(self, spec: DAGSpec, intervention: Intervention) -> None:
        nodes = {node.id: node for node in spec.nodes}
        if not intervention.skipped_nodes <= nodes.keys():
            raise ValueError("intervention skips an unknown node")
        all_edges = {(edge.source, edge.target) for edge in spec.edges}
        requested = intervention.masked_edges | intervention.passthrough_edges
        if not requested <= all_edges:
            raise ValueError("intervention names an unknown edge")
        if intervention.masked_edges & intervention.passthrough_edges:
            raise ValueError("an edge cannot be masked and passthrough")
        if intervention.serialize_read_only:
            parallel = [batch for batch in spec.schedule if len(batch) > 1]
            if len(parallel) != 1 or any(not nodes[node_id].read_only for node_id in parallel[0]):
                raise ValueError("topology intervention requires one independent read-only parallel batch")

    def schedule_for(self, spec: DAGSpec, intervention: Intervention) -> tuple[tuple[str, ...], ...]:
        self.validate(spec, intervention)
        if not intervention.serialize_read_only:
            return spec.schedule
        return tuple((node_id,) for batch in spec.schedule for node_id in batch)

    @staticmethod
    def typed_null(edge: DAGEdge) -> dict[str, Any]:
        return {
            "schema_version": "appworld.dag-null.v1",
            "valid": False,
            "source": edge.source,
            "target": edge.target,
            "artifact_type": edge.artifact_type,
            "reason": "causal edge-mask intervention",
        }


class DAGExecutor:
    """Execute a compiled DAG and checkpoint every executed node.

    ``runner`` owns model/tool interaction. Keeping it injected makes P0 run
    entirely on a deterministic fake world, and makes replay auditing use the
    exact same scheduling logic as a live run.
    """

    def __init__(self, *, runner: NodeRunner, checkpoint: CheckpointWriter) -> None:
        self.runner = runner
        self.checkpoint = checkpoint
        self.interventions = InterventionEngine()

    def execute(
        self,
        spec: DAGSpec,
        intervention: Intervention | None = None,
        *,
        initial_artifacts: dict[str, Artifact] | None = None,
    ) -> dict[str, Any]:
        spec = DAGCompiler().compile(spec)
        intervention = intervention or Intervention()
        self.interventions.validate(spec, intervention)
        # Replays restore both a world checkpoint and immutable upstream
        # artifacts.  Skipped upstream nodes therefore retain their recorded
        # outputs instead of being silently converted to null inputs.
        artifacts: dict[str, Artifact] = dict(initial_artifacts or {})
        node_records: dict[str, dict[str, Any]] = {}
        checkpoints: dict[str, dict[str, Any]] = {}
        attempt_checkpoints: dict[str, dict[str, Any]] = {}
        predecessors: dict[str, list[DAGEdge]] = {node.id: [] for node in spec.nodes}
        for edge in spec.edges:
            predecessors[edge.target].append(edge)
        for batch in self.interventions.schedule_for(spec, intervention):
            runnable: list[tuple[DAGNode, dict[str, Artifact]]] = []
            for node_id in batch:
                node = next(item for item in spec.nodes if item.id == node_id)
                inputs: dict[str, Artifact] = {}
                for edge in predecessors[node_id]:
                    pair = (edge.source, edge.target)
                    if pair in intervention.masked_edges:
                        inputs[edge.input_name] = self.interventions.typed_null(edge)
                    elif edge.source in artifacts:
                        inputs[edge.input_name] = artifacts[edge.source]
                    else:
                        inputs[edge.input_name] = self.interventions.typed_null(edge)
                if node_id in intervention.skipped_nodes:
                    node_records[node_id] = {"status": "skipped_intervention", "inputs": inputs}
                    continue
                if node.run_if == "not_verified":
                    values = [*inputs.values(), *artifacts.values()]
                    not_verified = any(
                        (value.get("status") if isinstance(value, dict) else getattr(value, "status", None))
                        == "NOT_VERIFIED"
                        for value in values
                    )
                    if not not_verified:
                        node_records[node_id] = {"status": "skipped_condition", "inputs": inputs}
                        continue
                runnable.append((node, inputs))

            # Parallel batches are limited by DAGCompiler to independent,
            # read-only nodes.  Checkpoints are still made in deterministic
            # graph order after all futures finish: AppWorld snapshots are not
            # safe to create concurrently, while the model inspections are.
            if len(runnable) > 1:
                with ThreadPoolExecutor(max_workers=len(runnable), thread_name_prefix="dag-read") as pool:
                    futures = [(node, inputs, pool.submit(self.runner, node, inputs)) for node, inputs in runnable]
                    outputs = [(node, inputs, future.result()) for node, inputs, future in futures]
            else:
                outputs = [(node, inputs, self.runner(node, inputs)) for node, inputs in runnable]

            for node, inputs, artifact in outputs:
                checkpoint = self.checkpoint(f"node-{node.id}")
                attempt_checkpoints[node.id] = checkpoint
                if artifact is None:
                    # A tool action may already have changed the world before
                    # its final contract fails.  Preserve that state evidence,
                    # but never call the DAG node completed or provide a fake
                    # artifact to downstream nodes.
                    node_records[node.id] = {
                        "status": "failed_null_artifact",
                        "inputs": inputs,
                        "environment_effect_checkpoint": checkpoint,
                    }
                    continue
                artifacts[node.id] = artifact
                checkpoints[node.id] = checkpoint
                node_records[node.id] = {
                    "status": "completed",
                    "inputs": inputs,
                    "artifact_hash": _hash(artifact),
                    "checkpoint": checkpoint,
                }
        invalid_nodes = sorted(
            node_id for node_id, record in node_records.items() if record["status"] == "failed_null_artifact"
        )
        return {
            "schema_version": "appworld.dag-execution.v1",
            "dag_id": spec.id,
            "schedule": [list(batch) for batch in self.interventions.schedule_for(spec, intervention)],
            "intervention": {
                "skipped_nodes": sorted(intervention.skipped_nodes),
                "masked_edges": [list(edge) for edge in sorted(intervention.masked_edges)],
                "passthrough_edges": [list(edge) for edge in sorted(intervention.passthrough_edges)],
                "serialize_read_only": intervention.serialize_read_only,
            },
            "artifacts": artifacts,
            "artifact_hashes": {node_id: _hash(value) for node_id, value in artifacts.items()},
            "nodes": node_records,
            "checkpoints": checkpoints,
            "attempt_checkpoints": attempt_checkpoints,
            "protocol_valid": not invalid_nodes,
            "protocol_invalid_reasons": [f"null artifact from {node_id}" for node_id in invalid_nodes],
        }
