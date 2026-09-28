"""Minimal offline runner for F/U retention and common-receiver probes.

It does not build a provider client and cannot make a live request unless an
already-validated authorization plus an explicit callback are supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Literal

from .records import AuthorizationError, CostLedger, LiveAuthorization, RunRecords
from .workspace import AgentSession, Snapshot, WorkspaceManager

Condition = Literal["F0", "U0", "F1", "U1"]
SourceKind = Literal["EMPTY", "M_F", "M_U", "RAW_F", "RAW_U"]

SHARED_PROMPT = (
    "Complete the current task using visible tool feedback. You may use files in /memory "
    "and may save reusable text, code, or tests there, but no artifact is required. "
    "If you choose to save one, its immutable snapshot may be independently cloned into "
    "a later new session when that session's condition permits it."
)
FIXED_PROMPT = (
    "Organize your work as: inspect task and materials; implement; check and revise if needed; "
    "then decide whether to retain an artifact. This is guidance, not a forced controller."
)
AUTONOMOUS_PROMPT = "Organize inspection, implementation, checking, and retention in any order you judge useful."
RECEIVER_PROMPT = "Complete the current task using the same /memory and /work file interface."


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreparedTask:
    session: AgentSession
    prompt: str
    tool_schema_hash: str
    request_config_hash: str


class AgentRuntime:
    """The only file operations passed to a ScriptedAgent in offline tests."""

    def __init__(self, manager: WorkspaceManager, session: AgentSession, records: RunRecords):
        self.manager, self.session, self.records = manager, session, records

    def read(self, logical_path: str) -> bytes:
        data = self.manager.read_agent_file(self.session, logical_path)
        self.records.emit("agent.file_read", attempt_id=self.session.attempt_id, path=logical_path, bytes=len(data))
        return data

    def write(self, logical_path: str, data: bytes) -> None:
        self.manager.write_agent_file(self.session, logical_path, data)
        self.records.emit("agent.file_write", attempt_id=self.session.attempt_id, path=logical_path, bytes=len(data))

    def list_dir(self, logical_path: str) -> dict[str, object]:
        result = self.manager.list_agent_directory(self.session, logical_path)
        self.records.emit("agent.dir_list", attempt_id=self.session.attempt_id, path=logical_path, returned=result["returned"], truncated=result["truncated"])
        return result


class ExperimentRunner:
    def __init__(self, output_root: Path, receiver_config: dict[str, object] | None = None):
        self.run_id = f"e0-{uuid.uuid4().hex}"
        self.root = Path(output_root) / self.run_id
        self.manager = WorkspaceManager(self.root)
        self.records = RunRecords(self.manager.research_root)
        self.receiver_config = receiver_config or {"provider": "unconfigured", "model": "unconfigured", "max_requests": 1}
        self.snapshots: dict[str, Snapshot] = {}
        self.raw_sources: dict[str, Snapshot] = {}

    def prepare_task(
        self,
        condition: Condition,
        replicate: str,
        task_id: str,
        parent: Snapshot | None = None,
        task_text: str | None = None,
    ) -> PreparedTask:
        should_retain = condition.endswith("1")
        session = self.manager.start_task(
            condition=condition,
            replicate=replicate,
            task_id=task_id,
            parent=parent if should_retain else None,
        )
        workflow = FIXED_PROMPT if condition.startswith("F") else AUTONOMOUS_PROMPT
        prompt = f"{SHARED_PROMPT}\n\nTask ID: {task_id}\nTask: {task_text or task_id}\n\n{workflow}"
        prepared = PreparedTask(
            session=session,
            prompt=prompt,
            tool_schema_hash=stable_hash(["list_dir", "read_file", "write_file", "query_sql"]),
            request_config_hash=stable_hash({"same_loop": "single_agent", "same_limits": True}),
        )
        self.records.emit(
            "task.prepared", attempt_id=session.attempt_id, condition=condition, task_id=task_id,
            conversation_id=session.conversation_id, parent_snapshot_id=session.parent_snapshot_id,
            prompt_hash=stable_hash(prompt), tool_schema_hash=prepared.tool_schema_hash,
            request_config_hash=prepared.request_config_hash,
        )
        return prepared

    def prepare_receiver_task(self, task_id: str, task_text: str, parent: Snapshot) -> PreparedTask:
        """Prepare a new E* conversation without inheriting source messages."""
        session = self.manager.start_task(condition="E*", replicate="receiver", task_id=task_id, parent=parent)
        prompt = f"{RECEIVER_PROMPT}\n\nTask ID: {task_id}\nTask: {task_text}"
        prepared = PreparedTask(
            session, prompt, stable_hash(["list_dir", "read_file", "write_file", "query_sql"]), stable_hash(self.receiver_config)
        )
        self.records.emit(
            "task.prepared", attempt_id=session.attempt_id, condition="E*", task_id=task_id,
            conversation_id=session.conversation_id, parent_snapshot_id=session.parent_snapshot_id,
            prompt_hash=stable_hash(prompt), tool_schema_hash=prepared.tool_schema_hash,
            request_config_hash=prepared.request_config_hash,
        )
        return prepared

    def run_scripted(self, prepared: PreparedTask, agent: Callable[[AgentRuntime], str]) -> tuple[str, Snapshot]:
        runtime = AgentRuntime(self.manager, prepared.session, self.records)
        answer = agent(runtime)
        snapshot = self.manager.freeze_memory(prepared.session)
        self.records.emit(
            "task.completed", attempt_id=prepared.session.attempt_id, agent_kind="ScriptedAgent",
            answer=answer, output_snapshot_hash=snapshot.content_hash, snapshot_id=snapshot.snapshot_id,
        )
        return answer, snapshot

    def register_source(self, kind: SourceKind, snapshot: Snapshot) -> None:
        if kind == "EMPTY":
            raise ValueError("EMPTY is created by the runner, not registered")
        (self.raw_sources if kind.startswith("RAW_") else self.snapshots)[kind] = snapshot

    def run_probe(self, kind: SourceKind, task_id: str, receiver: Callable[[AgentRuntime], str]) -> tuple[str, Snapshot, PreparedTask]:
        if kind == "EMPTY":
            source = self.manager.empty_snapshot()
        else:
            sources = self.raw_sources if kind.startswith("RAW_") else self.snapshots
            if kind not in sources:
                raise ValueError(f"source {kind} is pending; it cannot silently become EMPTY")
            source = sources[kind]
        session = self.manager.start_task(condition="E*", replicate="receiver", task_id=task_id, parent=source)
        prepared = PreparedTask(session, RECEIVER_PROMPT, stable_hash(["list_dir", "read_file", "write_file", "query_sql"]), stable_hash(self.receiver_config))
        answer, output = self.run_scripted(prepared, receiver)
        self.records.emit(
            "probe.completed", source_kind=kind, source_snapshot_id=source.snapshot_id,
            source_hash=source.content_hash, receiver_hash=stable_hash(self.receiver_config),
            attempt_id=session.attempt_id, probe_snapshot_id=output.snapshot_id,
        )
        return answer, output, prepared

    def plan_only(self) -> Path:
        planned = []
        for condition in ("F0", "U0", "F1", "U1"):
            for replicate in range(2):
                for phase, count in (("practice", 3), ("probe", 3)):
                    for order in range(count):
                        planned.append({"experiment": "E1", "condition": condition, "replicate": replicate, "phase": phase, "order": order, "status": "planned_only"})
        for source in ("EMPTY", "M_F", "M_U", "RAW_F", "RAW_U"):
            for paired_source in range(2):
                for order in range(3):
                    planned.append({"experiment": "E2", "source": source, "paired_source": paired_source, "phase": "probe", "order": order, "status": "planned_only", "depends_on_future_snapshot": source != "EMPTY"})
        if len(planned) != 78:
            raise AssertionError("dry-run plan must remain 48 + 30 episodes")
        return self.records.write_json("plan_only.json", {"requests_sent": 0, "episodes": planned})

    def live_smoke(self, authorization: LiveAuthorization, estimated_cost: Decimal, invoke: Callable[[], tuple[str, Decimal | None, dict[str, object] | None]]) -> str:
        ledger = CostLedger(authorization)
        entry = ledger.reserve(estimated_cost)  # validates before invoke
        answer, actual, usage = invoke()
        ledger.settle(entry, actual, usage)
        self.records.write_json("live_ledger.json", {"entries": ledger.entries, "billing_unknown": ledger.billing_unknown})
        return answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Day-1 experience-value runner")
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value"))
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    runner = ExperimentRunner(args.output_root)
    if not args.plan_only:
        parser.error("only --plan-only is available without explicit live authorization")
    print(runner.plan_only())


if __name__ == "__main__":
    main()
