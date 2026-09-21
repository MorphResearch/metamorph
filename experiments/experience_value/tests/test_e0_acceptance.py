from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from experiments.experience_value.fixture import QueryRejected, create_local_fixture
from experiments.experience_value.records import AuthorizationError, LiveAuthorization, record_attempt
from experiments.experience_value.runner import ExperimentRunner, FIXED_PROMPT, SHARED_PROMPT
from experiments.experience_value.workspace import WorkspaceAccessError, hash_tree


def write_memory(runtime):
    runtime.write("/memory/experience.txt", b"sentinel: durable discovery")
    return "saved"


def read_memory(runtime):
    return runtime.read("/memory/experience.txt").decode("utf-8")


class E0AcceptanceTests(unittest.TestCase):
    """T01--T14: offline, ScriptedAgent engineering evidence only."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "artifacts"
        self.runner = ExperimentRunner(self.root, receiver_config={"provider": "fixture", "model": "receiver-v0", "max_requests": 2})

    def tearDown(self):
        self.temp.cleanup()

    def _source(self):
        practice = self.runner.prepare_task("U1", "rep-1", "local-practice")
        _, snapshot = self.runner.run_scripted(practice, write_memory)
        return practice, snapshot

    def test_t01_only_workflow_prompt_differs(self):
        fixed = self.runner.prepare_task("F0", "r", "same-task")
        autonomous = self.runner.prepare_task("U0", "r", "same-task")
        self.assertEqual(fixed.tool_schema_hash, autonomous.tool_schema_hash)
        self.assertEqual(fixed.request_config_hash, autonomous.request_config_hash)
        self.assertIn(SHARED_PROMPT, fixed.prompt)
        self.assertIn(SHARED_PROMPT, autonomous.prompt)
        self.assertIn(FIXED_PROMPT, fixed.prompt)
        self.assertNotEqual(fixed.prompt, autonomous.prompt)

    def test_t02_new_session_does_not_receive_prior_marker(self):
        old, _ = self._source()
        fresh = self.runner.prepare_task("U0", "rep-1", "different-task")
        self.assertNotEqual(old.session.conversation_id, fresh.session.conversation_id)
        self.assertNotIn("durable discovery", fresh.prompt)
        self.assertFalse(fresh.session.memory_root.iterdir().__next__() if any(fresh.session.memory_root.iterdir()) else False)

    def test_t03_no_retention_cannot_read_old_artifact(self):
        _, source = self._source()
        no_retention = self.runner.prepare_task("U0", "rep-1", "probe", parent=source)
        with self.assertRaises(WorkspaceAccessError):
            self.runner.manager.read_agent_file(no_retention.session, "/memory/experience.txt")

    def test_t04_retention_reads_original_bytes_and_hash(self):
        _, source = self._source()
        inherited = self.runner.prepare_task("U1", "rep-1", "next", parent=source)
        self.assertEqual(
            self.runner.manager.read_agent_file(inherited.session, "/memory/experience.txt"),
            b"sentinel: durable discovery",
        )
        self.assertEqual(hash_tree(inherited.session.memory_root)[0], source.content_hash)

    def test_t05_probe_clones_do_not_write_back_or_cross_contaminate(self):
        _, source = self._source()
        self.runner.register_source("M_U", source)
        _, _, probe_a = self.runner.run_probe("M_U", "probe-a", lambda runtime: (runtime.write("/memory/a.txt", b"only-a") or "a"))
        _, _, probe_b = self.runner.run_probe("M_U", "probe-b", lambda runtime: "b")
        self.assertFalse((probe_b.session.memory_root / "a.txt").exists())
        self.assertEqual(hash_tree(source.path)[0], source.content_hash)
        self.assertNotEqual(probe_a.session.agent_root, probe_b.session.agent_root)

    def test_t06_group_paths_and_symlinks_are_rejected(self):
        one = self.runner.prepare_task("F1", "rep-a", "a")
        two = self.runner.prepare_task("U1", "rep-b", "b")
        with self.assertRaises(WorkspaceAccessError):
            self.runner.manager.read_agent_file(one.session, str(two.session.memory_root))
        link = one.session.memory_root / "escape"
        link.symlink_to(two.session.memory_root, target_is_directory=True)
        with self.assertRaises(WorkspaceAccessError):
            self.runner.manager.read_agent_file(one.session, "/memory/escape/anything")

    def test_t07_hidden_records_and_database_are_not_agent_paths(self):
        prepared = self.runner.prepare_task("F0", "r", "task")
        service = self.runner.root / "tool_service"
        database = create_local_fixture(service)
        for forbidden in (str(self.runner.manager.research_root / "events.jsonl"), str(database.database_path), "/research_records/events.jsonl"):
            with self.assertRaises(WorkspaceAccessError):
                self.runner.manager.read_agent_file(prepared.session, forbidden)

    def test_t08_every_sql_query_is_metered_and_limited(self):
        database = create_local_fixture(self.runner.root / "tool_service", max_queries=3)
        self.assertEqual(database.query("SELECT count(*) FROM observations"), [(4,)])
        with self.assertRaises(QueryRejected):
            database.query("DELETE FROM observations")
        self.assertEqual(database.query("SELECT region FROM regions ORDER BY region"), [("north",), ("south",)])
        with self.assertRaises(QueryRejected):
            database.query("SELECT value FROM observations")
        self.assertEqual(database.successful_queries, 2)
        self.assertEqual(database.failed_queries, 1)
        self.assertEqual(database.blocked_queries, 1)

    def test_t09_unauthorized_live_never_invokes_provider(self):
        calls = []
        def provider():
            calls.append("called")
            return "unexpected", Decimal("0"), {}
        with self.assertRaises(AuthorizationError):
            self.runner.live_smoke(LiveAuthorization(authorized=False), Decimal("0.01"), provider)
        self.assertEqual(calls, [])

    def test_t10_budget_and_unknown_billing_stop_future_calls(self):
        calls = []
        authorization = LiveAuthorization(True, "fixture", "m", "CNY", Decimal("1"), 1, "local-test-price")
        self.runner.live_smoke(authorization, Decimal("0.50"), lambda: (calls.append("one") or "ok", None, None))
        self.assertEqual(calls, ["one"])
        ledger = json.loads((self.runner.manager.research_root / "live_ledger.json").read_text())
        self.assertTrue(ledger["billing_unknown"])
        with self.assertRaises(AuthorizationError):
            LiveAuthorization(True, "fixture", "m", "CNY", Decimal("1"), 4, "local-test-price").validate()

    def test_t11_empty_artifact_and_error_types_remain_distinct(self):
        empty = self.runner.prepare_task("F0", "r", "empty")
        _, snapshot = self.runner.run_scripted(empty, lambda runtime: "no artifact")
        self.assertEqual(snapshot.files, ())
        task_error = record_attempt(attempt_id="a", condition="F0", task_id="x", error_kind="task_error", task_correct=False)
        infra_error = record_attempt(attempt_id="b", condition="F0", task_id="x", error_kind="infrastructure_error")
        self.assertEqual(task_error["infra_status"], "unknown")
        self.assertEqual(infra_error["task_correct"], None)

    def test_t12_raw_source_excludes_research_canary(self):
        source_task = self.runner.prepare_task("F1", "r", "raw-source")
        _, raw = self.runner.run_scripted(source_task, lambda runtime: (runtime.write("/memory/raw.txt", b"visible agent artifact") or "ok"))
        (self.runner.manager.research_root / "hidden_evaluator.txt").write_text("HIDDEN_CANARY", encoding="utf-8")
        self.runner.register_source("RAW_F", raw)
        seen = []
        self.runner.run_probe("RAW_F", "raw-probe", lambda runtime: (seen.append(runtime.read("/memory/raw.txt")) or "ok"))
        self.assertEqual(seen, [b"visible agent artifact"])
        self.assertNotIn("HIDDEN_CANARY", raw.path.joinpath("raw.txt").read_text())

    def test_t13_snapshots_are_independent_and_attempts_never_overwrite(self):
        first, source = self._source()
        second = self.runner.prepare_task("U1", "rep-1", "same-task", parent=source)
        self.assertNotEqual(first.session.attempt_id, second.session.attempt_id)
        self.runner.manager.write_agent_file(second.session, "/memory/experience.txt", b"changed clone")
        self.assertEqual((source.path / "experience.txt").read_bytes(), b"sentinel: durable discovery")
        self.assertNotEqual(hash_tree(second.session.memory_root)[0], source.content_hash)

    def test_t14_five_sources_share_receiver_and_have_independent_probes(self):
        _, source = self._source()
        for kind in ("M_F", "M_U", "RAW_F", "RAW_U"):
            self.runner.register_source(kind, source)
        probes = []
        for kind in ("EMPTY", "M_F", "M_U", "RAW_F", "RAW_U"):
            _, _, prepared = self.runner.run_probe(kind, f"probe-{kind}", lambda runtime: "receiver")
            probes.append(prepared)
        self.assertEqual({item.request_config_hash for item in probes}, {probes[0].request_config_hash})
        self.assertEqual(len({item.session.agent_root for item in probes}), 5)


if __name__ == "__main__":
    unittest.main()
