"""Offline acceptance for the manifest-driven formal-source runner V2."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm.adapters import AdapterResponse, ProviderAdapter

import experiments.experience_value.formal_source_run_v2 as v2
from experiments.experience_value.public_viability_gate_run import _code_hashes
from experiments.experience_value.tests.test_public_viability_gate_run import tool_call
from experiments.experience_value.live import EXPERIENCE_GENERATION_PROMPT
from experiments.experience_value.records import AuthorizationError
from experiments.experience_value.runner import ExperimentRunner
from experiments.experience_value.workspace import Snapshot, WorkspaceAccessError

ROOT = Path(__file__).resolve().parents[3]
PENDING = ROOT / "experiments/experience_value/formal_source_block_02.pending.json"
AUTH = ROOT / "experiments/experience_value/formal_source_block_02.authorization.pending.json"


class Fake(ProviderAdapter):
    def __init__(self) -> None:
        self.steps: dict[str, int] = {}
        self.requests: list[tuple[str, object]] = []

    def stream(self, **_: object) -> object:
        raise TypeError()

    def complete_configured(self, *, model_name: str, messages: list[dict[str, object]], tools: object, generation_options: object) -> AdapterResponse:
        task = next(str(message["content"]) for message in messages if "Task ID:" in str(message.get("content", ""))).split("Task ID: ")[1].split("\n")[0]
        self.requests.append((task, tools))
        if str(messages[-1].get("content")) == EXPERIENCE_GENERATION_PROMPT:
            return AdapterResponse(content=f"experience bytes for {task}", usage={"prompt_tokens": 20, "completion_tokens": 4}, stop_reason="stop")
        count = self.steps.get(task, 0)
        self.steps[task] = count + 1
        if count < 15:
            return AdapterResponse(tool_calls=[tool_call(f"{task}-{count}", "query_sql", {"sql": ".tables"})], usage={"prompt_tokens": 20, "completion_tokens": 4}, stop_reason="tool_calls")
        return AdapterResponse(content="0", usage={"prompt_tokens": 20, "completion_tokens": 1}, stop_reason="stop")


class FormalSourceV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "artifacts/experience_value")
        self.root = Path(self.temp.name)
        self.pending, self.authorization = self.root / "pending.json", self.root / "authorization.json"
        shutil.copy(PENDING, self.pending)
        shutil.copy(AUTH, self.authorization)
        self._bind_authorization()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _bind_authorization(self) -> None:
        auth = json.loads(self.authorization.read_text())
        auth["frozen_pending_config"]["path"] = str(self.pending.resolve().relative_to(ROOT)) if self.pending.resolve().is_relative_to(ROOT) else "experiments/experience_value/formal_source_block_02.pending.json"
        # The runner's code binding is the object under test; a temp pending
        # uses the same repository-relative frozen path only for offline work.
        auth["frozen_pending_config"]["path"] = "experiments/experience_value/formal_source_block_02.pending.json"
        auth["frozen_pending_config"]["sha256"] = hashlib.sha256(self.pending.read_bytes()).hexdigest()
        deps = _code_hashes()
        deps["entry"] = hashlib.sha256((ROOT / "experiments/experience_value/formal_source_run_v2.py").read_bytes()).hexdigest()
        auth["entry_code"]["sha256"] = deps["entry"]
        auth["code_dependencies"] = deps
        self.authorization.write_text(json.dumps(auth, indent=2, sort_keys=True) + "\n")

    def _load_temp(self):
        # _load intentionally requires a repository-relative frozen pending
        # path.  Copying it into the repo is unnecessary: patch the frozen
        # config binding to the canonical checked-in offline pending.
        pending = ROOT / "experiments/experience_value/formal_source_block_02.pending.json"
        return v2._load(pending, AUTH)

    def test_block2_exact_order_and_inheritance_fake_path(self) -> None:
        adapter = Fake()
        report_path = v2.execute(pending_path=PENDING, authorization_path=AUTH, output_root=self.root / "out", mode="fake", adapter=adapter)
        report = json.loads(report_path.read_text())
        self.assertEqual([(row["manifest_position"], row["task_id"], row["condition"]) for row in report["episodes"]], [(5, "8", "U0"), (6, "8", "F1"), (7, "8", "U1"), (8, "8", "F0")])
        self.assertEqual(report["next_manifest_position"], 9)
        self.assertEqual(report["status"], "COMPLETED")
        by_id = {row["episode_id"]: row for row in report["episodes"]}
        self.assertIsNone(by_id["formal-t08-u0"]["inheritance_source"])
        self.assertIsNone(by_id["formal-t08-f0"]["inheritance_source"])
        self.assertEqual(by_id["formal-t08-f1"]["inheritance_source"], "snapshot-c2e5d0df8d7f45bdb43d27f7ffb9f995")
        self.assertEqual(by_id["formal-t08-u1"]["inheritance_source"], "snapshot-d0eb99e062e14024bcdc0dc7c9d4aeee")
        run_root = report_path.parents[1]
        for episode_id, expected in (("formal-t08-f1", "56ef6d03541168dd9eda2a02820fbc788ff2477ad187df1e07540c383f61ff71"), ("formal-t08-u1", "c19b252e079de0ece47d38a3009755533cf4d10d49b5b6a3481f9b7d0436896f")):
            row = by_id[episode_id]
            snapshot_id = row["artifact_provenance"][0]["snapshot_id"]
            memory = run_root / "frozen_snapshots" / snapshot_id
            self.assertEqual(hashlib.sha256((memory / "experience_001.md").read_bytes()).hexdigest(), expected)
            self.assertTrue((memory / "experience_002.md").is_file())
        self.assertEqual(len(adapter.requests), 68)  # 4 x (15 SQL + answer + consolidation)

    def test_unsigned_live_rejects_without_provider_attempt(self) -> None:
        with self.assertRaises(AuthorizationError):
            v2.execute(pending_path=PENDING, authorization_path=AUTH, output_root=self.root / "live", mode="live", adapter=Fake())

    def test_altered_or_cross_condition_predecessor_rejected_pre_provider(self) -> None:
        payload = json.loads(PENDING.read_text())
        payload["predecessor_references"]["formal-t08-f1"]["snapshot_hash"] = "0" * 64
        altered = self.root / "altered.json"
        altered.write_text(json.dumps(payload, indent=2) + "\n")
        auth = json.loads(AUTH.read_text())
        auth["frozen_pending_config"]["path"] = str(altered.relative_to(ROOT))
        auth["frozen_pending_config"]["sha256"] = hashlib.sha256(altered.read_bytes()).hexdigest()
        auth["required_predecessors"]["formal-t08-f1"]["snapshot_hash"] = "0" * 64
        altered_auth = self.root / "altered-auth.json"
        altered_auth.write_text(json.dumps(auth, indent=2) + "\n")
        with self.assertRaises(AuthorizationError):
            v2._load(altered, altered_auth)
        payload = json.loads(PENDING.read_text())
        payload["predecessor_references"]["formal-t08-f1"]["condition"] = "U1"
        cross = self.root / "cross.json"
        cross.write_text(json.dumps(payload, indent=2) + "\n")
        auth = json.loads(AUTH.read_text())
        auth["frozen_pending_config"]["path"] = str(cross.relative_to(ROOT))
        auth["frozen_pending_config"]["sha256"] = hashlib.sha256(cross.read_bytes()).hexdigest()
        cross_auth = self.root / "cross-auth.json"
        cross_auth.write_text(json.dumps(auth, indent=2) + "\n")
        with self.assertRaises(AuthorizationError):
            v2._load(cross, cross_auth)

    def test_block1_backward_plan_and_all_future_blocks_parse_without_hardcoding(self) -> None:
        source = json.loads((ROOT / "FORMAL_SOURCE_MANIFEST_V1.json").read_text())
        blocks = json.loads((ROOT / "FORMAL_SOURCE_BLOCKS_V1.json").read_text())["blocks"]
        self.assertEqual([source["execution_order"][i - 1] for i in blocks[0]["manifest_positions"]], ["t07-F0", "t07-U0", "t07-F1", "t07-U1"])
        for block in blocks:
            items = [v2._source_item(position, source["execution_order"][position - 1]) for position in block["manifest_positions"]]
            self.assertEqual([item["id"].removeprefix("formal-") for item in items], [token.lower() for token in block["expected_tokens"]])
            self.assertEqual(block["manifest_positions"], list(range(block["manifest_positions"][0], block["manifest_positions"][0] + 4)))
            for item in items:
                predecessor = v2._required_predecessor(item, source)
                if item["condition"] in {"F1", "U1"} and int(item["task_id"]) != 7:
                    self.assertEqual(predecessor, (f"t{int(item['task_id']) - 1:02d}-{item['condition']}", f"formal-t{int(item['task_id']) - 1:02d}-{item['condition'].lower()}"))
                else:
                    self.assertIsNone(predecessor)

    def test_v2_parses_block1_with_historical_empty_memory_semantics(self) -> None:
        pending = json.loads(PENDING.read_text())
        block = json.loads((ROOT / "FORMAL_SOURCE_BLOCKS_V1.json").read_text())["blocks"][0]
        pending["block_id"] = block["id"]
        pending["predecessor_references"] = {}
        pending_path = self.root / "block1-v2.json"
        pending_path.write_text(json.dumps(pending, indent=2) + "\n")
        authorization = json.loads(AUTH.read_text())
        authorization["frozen_pending_config"] = {"path": str(pending_path.relative_to(ROOT)), "sha256": hashlib.sha256(pending_path.read_bytes()).hexdigest()}
        authorization["block_definition"].update(block_id=block["id"], allowed_manifest_positions=block["manifest_positions"], allowed_tokens=block["expected_tokens"], next_position_not_authorized=block["next_position"])
        authorization["required_predecessors"] = {}
        authorization_path = self.root / "block1-v2-auth.json"
        authorization_path.write_text(json.dumps(authorization, indent=2) + "\n")
        _p, _a, items, parents, _c, _prices, loaded = v2._load(pending_path, authorization_path)
        self.assertEqual(loaded["id"], "formal_source_block_01")
        self.assertEqual([(i["manifest_position"], i["task_id"], i["condition"]) for i in items], [(1, "07", "F0"), (2, "07", "U0"), (3, "07", "F1"), (4, "07", "U1")])
        self.assertTrue(all(parent is None for parent in parents.values()))

    def test_all_frozen_blocks_use_generic_v2_block_resolution(self) -> None:
        source = json.loads((ROOT / "FORMAL_SOURCE_MANIFEST_V1.json").read_text())
        for block in json.loads((ROOT / "FORMAL_SOURCE_BLOCKS_V1.json").read_text())["blocks"]:
            pending = json.loads(PENDING.read_text())
            pending["block_id"] = block["id"]
            items = [v2._source_item(position, source["execution_order"][position - 1]) for position in block["manifest_positions"]]
            needed = [item for item in items if v2._required_predecessor(item, source) is not None]
            pending["predecessor_references"] = {item["id"]: {"run_id": "synthetic", "snapshot_id": "synthetic", "snapshot_hash": "synthetic", "artifact_sha256": "synthetic"} for item in needed}
            pending_path = self.root / f"{block['id']}.json"
            pending_path.write_text(json.dumps(pending, indent=2) + "\n")
            authorization = json.loads(AUTH.read_text())
            authorization["frozen_pending_config"] = {"path": str(pending_path.relative_to(ROOT)), "sha256": hashlib.sha256(pending_path.read_bytes()).hexdigest()}
            authorization["block_definition"].update(block_id=block["id"], allowed_manifest_positions=block["manifest_positions"], allowed_tokens=block["expected_tokens"], next_position_not_authorized=block["next_position"])
            authorization["required_predecessors"] = pending["predecessor_references"]
            authorization_path = self.root / f"{block['id']}-auth.json"
            authorization_path.write_text(json.dumps(authorization, indent=2) + "\n")
            with patch.object(v2, "_resolve_parents", return_value={item["id"]: None for item in items}):
                _p, _a, loaded_items, _parents, _config, _prices, loaded_block = v2._load(pending_path, authorization_path)
            self.assertEqual(loaded_block["id"], block["id"])
            self.assertEqual([item["manifest_position"] for item in loaded_items], block["manifest_positions"])
            self.assertEqual([item["id"].removeprefix("formal-") for item in loaded_items], [token.lower() for token in block["expected_tokens"]])

    def test_cumulative_snapshot_and_missing_predecessor_guards(self) -> None:
        # Task 9 receives task 8's cumulative immutable snapshot, including
        # task 7's artifact; it cannot overwrite either inherited file.
        inherited_root = self.root / "synthetic-parent"
        inherited_root.mkdir()
        (inherited_root / "experience_001.md").write_bytes(b"task7")
        (inherited_root / "experience_002.md").write_bytes(b"task8")
        content_hash, files = v2.hash_tree(inherited_root)
        predecessor = Snapshot("snapshot-task8", inherited_root, content_hash, None, "synthetic", files)
        runner = ExperimentRunner(self.root / "task9")
        prepared = runner.prepare_task("F1", "formal-source-v1", "formal-t09-f1", parent=predecessor, task_text="offline")
        self.assertEqual(runner.manager.read_agent_file(prepared.session, "/memory/experience_001.md"), b"task7")
        self.assertEqual(runner.manager.read_agent_file(prepared.session, "/memory/experience_002.md"), b"task8")
        with self.assertRaises(WorkspaceAccessError):
            runner.manager.write_agent_file(prepared.session, "/memory/experience_001.md", b"overwrite")
        payload = json.loads(PENDING.read_text())
        del payload["predecessor_references"]["formal-t08-f1"]
        missing = self.root / "missing.json"
        missing.write_text(json.dumps(payload, indent=2) + "\n")
        authorization = json.loads(AUTH.read_text())
        authorization["frozen_pending_config"] = {"path": str(missing.relative_to(ROOT)), "sha256": hashlib.sha256(missing.read_bytes()).hexdigest()}
        del authorization["required_predecessors"]["formal-t08-f1"]
        missing_auth = self.root / "missing-auth.json"
        missing_auth.write_text(json.dumps(authorization, indent=2) + "\n")
        with self.assertRaises(AuthorizationError):
            v2._load(missing, missing_auth)
