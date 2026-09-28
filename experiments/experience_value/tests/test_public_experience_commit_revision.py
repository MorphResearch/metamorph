"""Offline tests for deterministic experience commitment; no provider is contacted."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from llm.adapters import AdapterResponse

from experiments.experience_value.live import EXPERIENCE_GENERATION_PROMPT
from experiments.experience_value.public_viability_gate_run import _code_hashes, execute
from experiments.experience_value.records import AuthorizationError
from experiments.experience_value.tests.test_public_viability_gate_run import GateFakeAdapter, tool_call
from experiments.experience_value.workspace import WorkspaceAccessError, WorkspaceManager


ROOT = Path(__file__).resolve().parents[3]
PENDING = ROOT / "experiments/experience_value/public_viability_gate.experience_commit_v3.pending.json"
AUTH_TEMPLATE = ROOT / "experiments/experience_value/public_viability_gate.operational_v2.authorization.pending.json"


def bind(pending: Path, auth: Path) -> None:
    data = json.loads(auth.read_text())
    data["frozen_pending_config"] = {"path": str(pending), "sha256": hashlib.sha256(pending.read_bytes()).hexdigest()}
    data["entry_code"]["sha256"] = hashlib.sha256((ROOT / "experiments/experience_value/public_viability_gate_run.py").read_bytes()).hexdigest()
    data["code_dependencies"] = _code_hashes()
    auth.write_text(json.dumps(data))


class CommitAdapter(GateFakeAdapter):
    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        if messages[-1].get("content") == EXPERIENCE_GENERATION_PROMPT:
            task = next(m["content"] for m in messages if "Task ID:" in m.get("content", ""))
            episode = re.search(r"Task ID: ([^\n]+)", task).group(1)  # type: ignore[union-attr]
            self.requests.append({"episode": episode, "messages": messages, "tools": tools, "options": generation_options})
            if episode == "viability-1-f0":
                return AdapterResponse(content="Reusable schema lesson", usage={"prompt_tokens": 20, "completion_tokens": 4}, stop_reason="stop")
            return AdapterResponse(content="NO_MEMORY", usage={"prompt_tokens": 20, "completion_tokens": 2}, stop_reason="stop")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class ToolCallGenerationAdapter(CommitAdapter):
    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        if messages[-1].get("content") == EXPERIENCE_GENERATION_PROMPT:
            return AdapterResponse(tool_calls=[tool_call("forbidden", "write_file", {"path": "/memory/x", "content": "x"})], usage={"prompt_tokens": 20, "completion_tokens": 2}, stop_reason="tool_calls")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class EmptyGenerationAdapter(CommitAdapter):
    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        if messages[-1].get("content") == EXPERIENCE_GENERATION_PROMPT:
            return AdapterResponse(content="", usage={"prompt_tokens": 20, "completion_tokens": 0}, stop_reason="stop")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class ExperienceCommitRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pending, self.auth = self.root / "pending.json", self.root / "auth.json"
        shutil.copyfile(PENDING, self.pending)
        shutil.copyfile(AUTH_TEMPLATE, self.auth)
        bind(self.pending, self.auth)

    def tearDown(self):
        self.tmp.cleanup()

    def test_visible_text_is_byte_committed_and_no_memory_is_not(self):
        result = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "out", mode="fake", adapter=CommitAdapter())
        report = json.loads(result.read_text())
        first, second = report["episodes"]
        artifact = first["artifact_provenance"][0]
        self.assertEqual(artifact["path"], "/memory/experience_001.md")
        self.assertEqual(artifact["raw_visible_content_sha256"], artifact["committed_file_sha256"])
        self.assertEqual(second["artifact_paths"], [])
        self.assertTrue(second["consolidation"]["metrics"]["voluntary_no_memory"])
        self.assertEqual(first["consolidation"]["allowed_tools"], [])
        self.assertEqual(first["consolidation"]["max_file_operations"], 0)
        # The report exposes an immutable research-side record rather than
        # mounting it as memory. Its event metadata asserts no evaluator or
        # reference material was visible when it was created.
        events = [json.loads(line) for line in (result.parent / "events.jsonl").read_text().splitlines()]
        raw_events = [event for event in events if event["type"] == "raw_experience.archived"]
        self.assertEqual(len(raw_events), 2)
        self.assertTrue(all(not event["agent_mountable"] and not event["evaluator_or_reference_visible"] for event in raw_events))

    def test_tool_call_generation_is_not_executed_or_retried(self):
        result = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "tool", mode="fake", adapter=ToolCallGenerationAdapter())
        report = json.loads(result.read_text())
        self.assertTrue(all(not row["artifact_paths"] for row in report["episodes"]))
        events = (result.parent / "events.jsonl").read_text()
        self.assertIn("tool.rejected", events)
        self.assertNotIn("agent.file_write", events)

    def test_empty_generation_is_recorded_without_artifact(self):
        result = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "empty", mode="fake", adapter=EmptyGenerationAdapter())
        report = json.loads(result.read_text())
        self.assertTrue(all(not row["artifact_paths"] for row in report["episodes"]))
        self.assertTrue(all(row["consolidation"]["metrics"]["consolidation_generation_failure"] for row in report["episodes"]))

    def test_unsigned_v3_live_path_rejects_before_any_provider_attempt(self):
        adapter = CommitAdapter()
        with self.assertRaises(AuthorizationError):
            execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "unsigned-live", mode="live", adapter=adapter)
        self.assertEqual(adapter.requests, [])

    def test_signed_v3_is_accepted_with_the_same_operational_wrapper(self):
        authorization = json.loads(self.auth.read_text())
        authorization["status"] = "AUTHORIZED_PUBLIC_VIABILITY_GATE_EXPERIENCE_COMMIT_V3"
        authorization["live_requests_authorized"] = True
        self.auth.write_text(json.dumps(authorization))
        always_open = lambda *_args, **_kwargs: {
            "request_allowed": True, "new_episode_allowed": True,
            "reason": "offline", "local_time": "2026-09-27T20:00:00+08:00", "utc_offset": "+0800",
        }
        result = execute(
            pending_path=self.pending, authorization_path=self.auth,
            output_root=self.root / "signed-live", mode="live", adapter=CommitAdapter(),
            offpeak_check=always_open, preflight_check=lambda: {"ok": True},
            shim_check=lambda: None, report_path=self.root / "signed-live.md",
        )
        report = json.loads(result.read_text())
        self.assertEqual(report["gate_outcome"], "GO")
        self.assertTrue(any(row["artifact_paths"] for row in report["episodes"]))

    def test_unique_immutable_paths_and_f1_inheritance_policy(self):
        manager = WorkspaceManager(self.root / "work")
        first = manager.start_task(condition="F0", replicate="x", task_id="a")
        manager.write_agent_file(first, "/memory/experience_001.md", b"one")
        parent = manager.freeze_memory(first)
        second = manager.start_task(condition="F1", replicate="x", task_id="b", parent=parent)
        self.assertEqual(manager.read_agent_file(second, "/memory/experience_001.md"), b"one")
        manager.write_agent_file(second, "/memory/experience_002.md", b"two")
        self.assertEqual(manager.read_agent_file(second, "/memory/experience_001.md"), b"one")
        with self.assertRaises(WorkspaceAccessError):
            manager.write_agent_file(second, "/memory/experience_001.md", b"mutated")
        # F0/U0 callers pass no parent snapshot, so archived source memory is
        # not implicitly mounted for a later control/source task.
        third = manager.start_task(condition="F0", replicate="x", task_id="c")
        self.assertFalse((third.memory_root / "experience_001.md").exists())
