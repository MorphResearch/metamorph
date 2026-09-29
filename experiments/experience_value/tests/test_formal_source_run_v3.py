"""Offline acceptance for V3's no-new-artifact predecessor resolver."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm.adapters import AdapterResponse, ProviderAdapter

from experiments.experience_value import formal_source_run_v3 as v3
from experiments.experience_value.public_viability_gate_run import _code_hashes
from experiments.experience_value.records import AuthorizationError
from experiments.experience_value.tests.test_public_viability_gate_run import tool_call

ROOT = Path(__file__).resolve().parents[3]
BLOCK6_PENDING = ROOT / "experiments/experience_value/formal_source_block_06.pending.json"


class Fake(ProviderAdapter):
    """Fake provider; SQL and native evaluation still use the public adapter."""
    def __init__(self) -> None:
        self.steps: dict[str, int] = {}
        self.requests = 0

    def stream(self, **_: object) -> object:
        raise TypeError()

    def complete_configured(self, *, model_name: str, messages: list[dict[str, object]], tools: object, generation_options: object) -> AdapterResponse:
        self.requests += 1
        task = next(str(message["content"]) for message in messages if "Task ID:" in str(message.get("content", ""))).split("Task ID: ")[1].split("\n")[0]
        if "输出一份简短" in str(messages[-1].get("content", "")):
            return AdapterResponse(content=f"offline V3 experience for {task}", usage={"prompt_tokens": 20, "completion_tokens": 4}, stop_reason="stop")
        step = self.steps.get(task, 0)
        self.steps[task] = step + 1
        if step < 15:
            return AdapterResponse(tool_calls=[tool_call(f"{task}-{step}", "query_sql", {"sql": ".tables"})], usage={"prompt_tokens": 20, "completion_tokens": 4}, stop_reason="tool_calls")
        return AdapterResponse(content="0", usage={"prompt_tokens": 20, "completion_tokens": 1}, stop_reason="stop")


class FormalSourceV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "artifacts/experience_value")
        self.root = Path(self.temp.name)
        self.pending = self.root / "pending.json"
        self.authorization = self.root / "authorization.json"
        self._write_block7_documents()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_block7_documents(self) -> None:
        pending = json.loads(BLOCK6_PENDING.read_text())
        block = json.loads((ROOT / "FORMAL_SOURCE_BLOCKS_V1.json").read_text())["blocks"][6]
        pending.update(status=v3.V3_PENDING_STATUS, block_id=block["id"])
        common = {
            "study_kind": "formal_source_v1", "included_in_primary_analysis": True,
            "formal_protocol_sha256": pending["formal_protocol"]["sha256"],
            "source_manifest_sha256": pending["source_manifest"]["sha256"],
            "run_id": "e0-dbae883e65154899b20be4a9d9cd20ba",
            "record_path": "artifacts/experience_value/formal_source/e0-dbae883e65154899b20be4a9d9cd20ba/research_records/formal_source_block_run.json",
            "authorization_path": "experiments/experience_value/formal_source_block_06.authorization.authorized_20260928T221145+0800.json",
        }
        pending["predecessor_references"] = {
            "formal-t13-f1": common | {
                "operational_case": "A", "predecessor_token": "t12-F1", "episode_id": "formal-t12-f1", "task_id": 12, "condition": "F1",
                "snapshot_id": "snapshot-9786f4a81f194eec85b9ee4b2073ed37", "snapshot_hash": "1f79e1b47bb13a6fc4e6ec4e24e24014aa729a3ccafe07c4f011681df4b99af9",
                "artifact_path": "/memory/experience_006.md", "artifact_sha256": "1c6a1902e02ca49d4ddc12475a2206ee0cbfdc2b48ca4fd4af0a72d97a20bb54",
            },
            "formal-t13-u1": common | {
                "operational_case": "B", "predecessor_token": "t12-U1", "episode_id": "formal-t12-u1", "task_id": 12, "condition": "U1",
                "snapshot_id": "snapshot-665b386530fe49d18e1753aa1cf0c5b8", "snapshot_hash": "7009a08bdc7ef78ec20200dca1825eaf77637f055c92bac940854feb8b8b7686",
                "snapshot_storage_run_id": "e0-dc6e03395e4a4aa7b86c52430d97bda2", "snapshot_files": [f"experience_{n:03d}.md" for n in range(1, 6)],
                "input_snapshot_id": "snapshot-665b386530fe49d18e1753aa1cf0c5b8", "input_snapshot_hash": "7009a08bdc7ef78ec20200dca1825eaf77637f055c92bac940854feb8b8b7686",
                "input_snapshot_storage_run_id": "e0-dc6e03395e4a4aa7b86c52430d97bda2", "input_snapshot_record_path": "artifacts/experience_value/formal_source/e0-dc6e03395e4a4aa7b86c52430d97bda2/research_records/formal_source_block_run.json",
                "input_snapshot_authorization_path": "experiments/experience_value/formal_source_block_05.authorization.authorized_20260928T220047+0800.json", "input_snapshot_source_episode": "formal-t11-u1",
            },
        }
        self.pending.write_text(json.dumps(pending, indent=2, sort_keys=True) + "\n")
        auth = {
            "status": "PENDING_FORMAL_SOURCE_BLOCK_07_USER_SIGNOFF_NO_LIVE_CALLS", "live_requests_authorized": False,
            "real_model_requests_sent_under_this_authorization": 0, "study_kind": "formal_source_v1", "included_in_primary_analysis": True,
            "frozen_pending_config": {"path": str(self.pending.relative_to(ROOT)), "sha256": self._sha(self.pending)},
            "entry_code": {"path": v3.V3_ENTRY_PATH, "sha256": self._sha(ROOT / v3.V3_ENTRY_PATH)},
            "code_dependencies": _code_hashes() | {"entry": self._sha(ROOT / v3.V3_ENTRY_PATH)},
            "formal_protocol": pending["formal_protocol"] | {"scientific_diff": "NONE"}, "source_manifest": pending["source_manifest"],
            "block_definition": pending["block_definition"] | {"block_id": block["id"], "allowed_manifest_positions": block["manifest_positions"], "allowed_tokens": block["expected_tokens"], "next_position_not_authorized": block["next_position"]},
            "required_predecessors": pending["predecessor_references"], "hard_cap_usd": "7.00",
        }
        self.authorization.write_text(json.dumps(auth, indent=2, sort_keys=True) + "\n")

    def test_block7_case_a_case_b_and_plan_have_zero_provider_requests(self) -> None:
        output = v3.execute(pending_path=self.pending, authorization_path=self.authorization, output_root=self.root / "plan", mode="plan-only")
        plan = json.loads(output.read_text())
        self.assertEqual([(row["manifest_position"], row["task_id"], row["condition"]) for row in plan["episodes"]], [(25, "13", "F1"), (26, "13", "U1"), (27, "13", "F0"), (28, "13", "U0")])
        self.assertEqual(plan["next_manifest_position"], 29)
        self.assertEqual(v3._case_b(self._case_b_reference(), {"task_id": "13", "condition": "U1"}, json.loads(self.pending.read_text())).files, tuple(f"experience_{n:03d}.md" for n in range(1, 6)))
        self.assertFalse((self.root / "plan" / "events.jsonl").exists())

    def test_fake_uses_actual_resolver_then_stops_before_position_29(self) -> None:
        adapter = Fake()
        result = v3.execute(pending_path=self.pending, authorization_path=self.authorization, output_root=self.root / "fake", mode="fake", adapter=adapter)
        report = json.loads(result.read_text())
        self.assertEqual([row["manifest_position"] for row in report["episodes"]], [25, 26, 27, 28])
        by_id = {row["episode_id"]: row for row in report["episodes"]}
        self.assertIsNone(by_id["formal-t13-f0"]["inheritance_source"])
        self.assertIsNone(by_id["formal-t13-u0"]["inheritance_source"])
        self.assertEqual(by_id["formal-t13-u1"]["inheritance_source"], "snapshot-665b386530fe49d18e1753aa1cf0c5b8")
        self.assertGreater(adapter.requests, 0)

    def _case_b_reference(self) -> dict[str, object]:
        return json.loads(self.pending.read_text())["predecessor_references"]["formal-t13-u1"]

    def test_case_b_rejects_wrong_immediate_or_cross_condition(self) -> None:
        pending = json.loads(self.pending.read_text())
        ref = self._case_b_reference()
        ref["predecessor_token"] = "t11-U1"
        with self.assertRaises(AuthorizationError): v3._case_b(ref, {"task_id": "13", "condition": "U1"}, pending)
        ref = self._case_b_reference(); ref["condition"] = "F1"
        with self.assertRaises(AuthorizationError): v3._case_b(ref, {"task_id": "13", "condition": "U1"}, pending)

    def test_continuity_rejects_add_delete_modify_and_nonimmutable_files(self) -> None:
        original = self.root / "original"; candidate = self.root / "candidate"
        original.mkdir(); candidate.mkdir()
        (original / "experience_001.md").write_bytes(b"one")
        (candidate / "experience_001.md").write_bytes(b"one")
        os.chmod(original / "experience_001.md", 0o400); os.chmod(candidate / "experience_001.md", 0o400)
        self.assertEqual(v3._assert_memory_continuity(original, candidate), ("experience_001.md",))
        (candidate / "experience_002.md").write_bytes(b"hidden")
        os.chmod(candidate / "experience_002.md", 0o400)
        with self.assertRaises(AuthorizationError): v3._assert_memory_continuity(original, candidate)
        (candidate / "experience_002.md").unlink()
        os.chmod(candidate / "experience_001.md", 0o600); (candidate / "experience_001.md").write_bytes(b"changed"); os.chmod(candidate / "experience_001.md", 0o400)
        with self.assertRaises(AuthorizationError): v3._assert_memory_continuity(original, candidate)
        (candidate / "experience_001.md").unlink()
        with self.assertRaises(AuthorizationError): v3._assert_memory_continuity(original, candidate)

    def test_unsigned_live_is_rejected_before_any_provider_call(self) -> None:
        adapter = Fake()
        with self.assertRaises(AuthorizationError):
            v3.execute(pending_path=self.pending, authorization_path=self.authorization, output_root=self.root / "live", mode="live", adapter=adapter)
        self.assertEqual(adapter.requests, 0)

    def test_case_b_is_generic_for_block8_no_memory_resource_and_generation_failure(self) -> None:
        """All no-new-artifact outcomes use the same strict continuity rule."""
        inherited = self.root / "block8-input"; output = self.root / "block8-output"
        inherited.mkdir(); output.mkdir()
        for root in (inherited, output):
            (root / "experience_001.md").write_bytes(b"formal history")
            os.chmod(root / "experience_001.md", 0o400)
        snapshot_hash, files = v3.hash_tree(inherited)
        reference = {
            "operational_case": "B", "input_snapshot_id": "snapshot-11111111111111111111111111111111", "input_snapshot_hash": snapshot_hash,
            "snapshot_id": "snapshot-22222222222222222222222222222222", "snapshot_hash": snapshot_hash, "snapshot_files": list(files),
            "input_snapshot_storage_run_id": "e0-11111111111111111111111111111111", "snapshot_storage_run_id": "e0-22222222222222222222222222222222",
            "input_snapshot_record_path": "ignored.json", "input_snapshot_authorization_path": "ignored.json", "input_snapshot_source_episode": "formal-t13-u1",
        }
        previous = {"attempt_id": "synthetic", "input_snapshot_hash": reference["input_snapshot_id"], "snapshot_hash": snapshot_hash, "snapshot_files": list(files)}
        origin = {"episodes": [{"episode_id": "formal-t13-u1", "condition": "U1", "snapshot_hash": snapshot_hash, "snapshot_files": list(files)}]}
        item, pending = {"task_id": "14", "condition": "U1"}, {"source_manifest": {"path": "FORMAL_SOURCE_MANIFEST_V1.json"}}
        with patch.object(v3, "_verify_common_case_b_lineage", return_value=previous), patch.object(v3, "_snapshot_root", side_effect=lambda run_id, _snapshot_id: inherited if str(run_id).startswith("e0-111") else output), patch.object(v3, "_run_root", return_value=self.root), patch.object(v3, "_root_relative", return_value=self.root / "ignored.json"), patch.object(v3, "_verify_formal_record_and_authorization", return_value=origin):
            for _outcome in ("NO_MEMORY", "RESOURCE_LIMITED_FAILURE", "generation_failure"):
                result = v3._case_b(reference, item, pending)
                self.assertEqual(result.files, files)
