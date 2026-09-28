from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from experiments.experience_value.fixture import QueryRejected, classify_local_fixture_result, create_local_fixture, score_local_fixture_answer
from experiments.experience_value.live import PriceSheet, ToolOnlyService, ToolOnlySmokeConfig, run_tool_only_episode, tool_only_schemas
from experiments.experience_value.records import AuthorizationError, BudgetError, CostLedger, LiveAuthorization, record_attempt
from experiments.experience_value.runner import ExperimentRunner, FIXED_PROMPT, SHARED_PROMPT
from experiments.experience_value.workspace import WorkspaceAccessError, hash_tree
from llm.adapters import OpenAICompatibleAdapter


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
            LiveAuthorization(True, "fixture", "m", "CNY", Decimal("1"), 4, "local-test-price", max_episodes=4).validate()

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

    def test_directory_discovery_is_scoped_empty_and_inheritable(self):
        prepared = self.runner.prepare_task("U1", "r", "dir-task")
        runtime = self.runner.run_scripted(prepared, lambda agent: (agent.write("/memory/nested/custom.txt", b"fixture marker") or "saved"))[0]
        self.assertEqual(runtime, "saved")
        source = self.runner.manager.freeze_memory(prepared.session)
        inherited = self.runner.prepare_task("U1", "r2", "dir-probe", parent=source)
        probe_runtime = self.runner.manager.list_agent_directory(inherited.session, "/memory")
        self.assertEqual(probe_runtime["entries"], [{"name": "nested", "type": "directory"}])
        nested = self.runner.manager.list_agent_directory(inherited.session, "/memory/nested")
        self.assertEqual(nested["entries"], [{"name": "custom.txt", "type": "file"}])
        self.assertEqual(self.runner.manager.read_agent_file(inherited.session, "/memory/nested/custom.txt"), b"fixture marker")
        empty = self.runner.prepare_task("U0", "empty", "empty-dir")
        self.assertEqual(self.runner.manager.list_agent_directory(empty.session, "/memory")["entries"], [])
        self.assertNotIn("task.md", empty.prompt)
        with self.assertRaises(WorkspaceAccessError):
            self.runner.manager.list_agent_directory(inherited.session, "/memory/nested/custom.txt")
        with self.assertRaises(WorkspaceAccessError):
            self.runner.manager.list_agent_directory(inherited.session, "/research_records")
        escape = inherited.session.memory_root / "escape"
        escape.symlink_to(self.runner.manager.research_root, target_is_directory=True)
        with self.assertRaises(WorkspaceAccessError):
            self.runner.manager.list_agent_directory(inherited.session, "/memory/escape")


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)
        self.options = []

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self


def _response(content, tool_calls, usage, finish_reason, reasoning_content=""):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning_content), finish_reason=finish_reason)],
        usage=usage,
    )


class ToolOnlyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runner = ExperimentRunner(Path(self.temp.name) / "artifacts")
        self.prepared = self.runner.prepare_task("U1", "r", "tool-only-task")
        self.database = create_local_fixture(self.runner.root / "tool_service", max_queries=2)
        self.config = ToolOnlySmokeConfig(
            provider="deepseek", exact_model_id="deepseek-v4-pro", base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY", max_input_characters=12_000, max_input_tokens_per_request=512,
            max_output_tokens_per_request=64, max_requests_per_episode=2, max_tool_calls_per_episode=2,
            timeout_seconds=20.0, retries=0,
        )
        self.prices = PriceSheet(Decimal("1.32"), Decimal("3.96"), "fake-test-price", "2026-09-21")
        self.authorization = LiveAuthorization(True, "deepseek", "deepseek-v4-pro", "USD", Decimal("0.01"), 2, "fake-test-price")

    def tearDown(self):
        self.temp.cleanup()

    def test_fake_transport_uses_existing_loop_and_pairs_tool_messages(self):
        sql_call = SimpleNamespace(id="call-sql", function=SimpleNamespace(name="query_sql", arguments='{"sql":"SELECT region, cluster FROM regions ORDER BY region"}'))
        write_call = SimpleNamespace(id="call-write", function=SimpleNamespace(name="write_file", arguments='{"path":"/memory/model.txt","content":"model artifact"}'))
        config = ToolOnlySmokeConfig(
            provider="deepseek", exact_model_id="deepseek-v4-pro", base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY", max_input_characters=12_000, max_input_tokens_per_request=512,
            max_output_tokens_per_request=64, max_requests_per_episode=3, max_tool_calls_per_episode=3,
            timeout_seconds=20.0, retries=0, thinking_enabled=True, reasoning_effort="low",
        )
        authorization = LiveAuthorization(True, "deepseek", "deepseek-v4-pro", "USD", Decimal("0.01"), 3, "fake-test-price")
        client = _FakeClient([
            _response("", [sql_call], SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15), "tool_calls", "reasoning one"),
            _response("", [write_call], SimpleNamespace(prompt_tokens=14, completion_tokens=3, total_tokens=17), "tool_calls", "reasoning two"),
            _response("finished", [], SimpleNamespace(prompt_tokens=18, completion_tokens=2, total_tokens=20), "stop"),
        ])
        answer, snapshot, metrics = run_tool_only_episode(
            prepared=self.prepared, manager=self.runner.manager, records=self.runner.records, database=self.database,
            adapter=OpenAICompatibleAdapter(client, provider="deepseek"), ledger=CostLedger(authorization),
            config=config, prices=self.prices, transport_kind="fake_transport",
        )
        self.assertEqual(answer, "finished")
        self.assertEqual(metrics["llm_calls"], 3)
        self.assertIn("model.txt", snapshot.files)
        self.assertEqual(len(client.completions.requests), 3)
        first_messages = client.completions.requests[0]["messages"]
        self.assertEqual([message["role"] for message in first_messages], ["system", "user"])
        self.assertNotIn("sentinel", json.dumps(first_messages))
        self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(first_messages))
        second_messages = client.completions.requests[1]["messages"]
        tool_message = next(message for message in second_messages if message.get("role") == "tool")
        self.assertEqual(tool_message["tool_call_id"], "call-sql")
        self.assertEqual(next(message for message in second_messages if message.get("role") == "assistant")["reasoning_content"], "reasoning one")
        self.assertEqual(client.options, [{"max_retries": 0, "timeout": 20.0}] * 3)
        for request in client.completions.requests:
            self.assertNotIn("tool_choice", request)
            self.assertEqual(request["reasoning_effort"], "low")
            self.assertEqual(request["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertEqual({schema["function"]["name"] for schema in tool_only_schemas()}, {"list_dir", "read_file", "write_file", "query_sql"})
        self.assertNotIn("execute", {schema["function"]["name"] for schema in tool_only_schemas()})
        events = [json.loads(line) for line in self.runner.records.path.read_text().splitlines()]
        completed = [event for event in events if event["type"] == "tool.completed"]
        self.assertEqual([event["tool_call_id"] for event in completed], ["call-sql", "call-write"])
        self.assertTrue(all(event["arguments_parsed"] and event["dispatched"] for event in completed))
        appended = [event for event in events if event["type"] == "tool.feedback_appended"]
        self.assertEqual([event["tool_call_id"] for event in appended], ["call-sql", "call-write"])
        transcripts = [event for event in events if event["type"] == "provider.transcript"]
        self.assertEqual(len(transcripts), 3)
        self.assertFalse(transcripts[0]["request"]["effective_request"]["tool_choice_present"])
        self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(transcripts))
        self.assertEqual(len(self.runner.records.root.joinpath("provider_transcripts.jsonl").read_text().splitlines()), 3)

    def test_unknown_usage_keeps_reservation_and_blocks_a_second_network_attempt(self):
        tool_call = SimpleNamespace(id="call-sql", function=SimpleNamespace(name="query_sql", arguments='{"sql":"SELECT count(*) FROM observations"}'))
        client = _FakeClient([
            _response("", [tool_call], None, "tool_calls"),
            _response("must not be requested", [], None, "stop"),
        ])
        with self.assertRaises(BudgetError):
            run_tool_only_episode(
                prepared=self.prepared, manager=self.runner.manager, records=self.runner.records, database=self.database,
                adapter=OpenAICompatibleAdapter(client, provider="deepseek"), ledger=CostLedger(self.authorization),
                config=self.config, prices=self.prices, transport_kind="fake_transport",
            )
        self.assertEqual(len(client.completions.requests), 1)
        ledger_files = list(self.runner.manager.research_root.glob("ledger_*.json"))
        self.assertEqual(len(ledger_files), 1)
        ledger = json.loads(ledger_files[0].read_text())
        self.assertTrue(ledger["billing_unknown"])
        self.assertEqual(ledger["entries"][0]["status"], "billing_unknown")

    def test_tool_cap_is_not_reported_as_normal_completion(self):
        tool_call = SimpleNamespace(id="call-sql", function=SimpleNamespace(name="query_sql", arguments='{"sql":"SELECT count(*) FROM observations"}'))
        client = _FakeClient([
            _response("", [tool_call], SimpleNamespace(prompt_tokens=10, completion_tokens=5), "tool_calls"),
            _response("<tool request omitted because budget ended>", [], SimpleNamespace(prompt_tokens=12, completion_tokens=4), "stop"),
        ])
        config = ToolOnlySmokeConfig(
            provider="deepseek", exact_model_id="deepseek-v4-pro", base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY", max_input_characters=12_000, max_input_tokens_per_request=512,
            max_output_tokens_per_request=64, max_requests_per_episode=2, max_tool_calls_per_episode=1,
            timeout_seconds=20.0, retries=0,
        )
        answer, _snapshot, metrics = run_tool_only_episode(
            prepared=self.prepared, manager=self.runner.manager, records=self.runner.records, database=self.database,
            adapter=OpenAICompatibleAdapter(client, provider="deepseek"), ledger=CostLedger(self.authorization),
            config=config, prices=self.prices, transport_kind="fake_transport",
        )
        self.assertIn("budget ended", answer)
        self.assertEqual(metrics["runner_stop_reason"], "tool_budget_exhausted")

    def test_result_interpretation_separates_return_scoring_and_task_success(self):
        score = score_local_fixture_answer("local_fixture_estimate_coastal_mean", "<tool_calls><invoke>SELECT 1</invoke></tool_calls>")
        result = classify_local_fixture_result("<tool_calls><invoke>SELECT 1</invoke></tool_calls>", "tool_budget_exhausted", score)
        self.assertTrue(result["runner_returned_nonempty_text"])
        self.assertTrue(result["evaluator_executed"])
        self.assertFalse(result["answer_accepted_as_task_answer"])
        self.assertFalse(result["task_correct"])

    def test_list_dir_uses_the_same_tool_budget(self):
        list_call = SimpleNamespace(id="call-list", function=SimpleNamespace(name="list_dir", arguments='{"path":"/memory"}'))
        client = _FakeClient([
            _response("", [list_call], SimpleNamespace(prompt_tokens=10, completion_tokens=5), "tool_calls"),
            _response("done", [], SimpleNamespace(prompt_tokens=12, completion_tokens=4), "stop"),
        ])
        config = ToolOnlySmokeConfig(
            provider="deepseek", exact_model_id="deepseek-v4-pro", base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY", max_input_characters=12_000, max_input_tokens_per_request=512,
            max_output_tokens_per_request=64, max_requests_per_episode=2, max_tool_calls_per_episode=1,
            timeout_seconds=20.0, retries=0,
        )
        _answer, _snapshot, metrics = run_tool_only_episode(
            prepared=self.prepared, manager=self.runner.manager, records=self.runner.records, database=self.database,
            adapter=OpenAICompatibleAdapter(client, provider="deepseek"), ledger=CostLedger(self.authorization),
            config=config, prices=self.prices, transport_kind="fake_transport",
        )
        self.assertEqual(metrics["tool_calls"], 1)
        events = [json.loads(line) for line in self.runner.records.path.read_text().splitlines()]
        self.assertEqual(len([event for event in events if event["type"] == "agent.dir_list"]), 1)

    def test_budget_rejected_tool_call_gets_explicit_feedback_pair(self):
        accepted = SimpleNamespace(id="call-list", function=SimpleNamespace(name="list_dir", arguments='{"path":"/memory"}'))
        rejected = SimpleNamespace(id="call-sql", function=SimpleNamespace(name="query_sql", arguments='{"sql":"SELECT count(*) FROM observations"}'))
        client = _FakeClient([
            _response("", [accepted, rejected], SimpleNamespace(prompt_tokens=10, completion_tokens=5), "tool_calls"),
            _response("done", [], SimpleNamespace(prompt_tokens=12, completion_tokens=4), "stop"),
        ])
        config = ToolOnlySmokeConfig(
            provider="deepseek", exact_model_id="deepseek-v4-pro", base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY", max_input_characters=12_000, max_input_tokens_per_request=512,
            max_output_tokens_per_request=64, max_requests_per_episode=2, max_tool_calls_per_episode=1,
            timeout_seconds=20.0, retries=0,
        )
        run_tool_only_episode(
            prepared=self.prepared, manager=self.runner.manager, records=self.runner.records, database=self.database,
            adapter=OpenAICompatibleAdapter(client, provider="deepseek"), ledger=CostLedger(self.authorization),
            config=config, prices=self.prices, transport_kind="fake_transport",
        )
        second_messages = client.completions.requests[1]["messages"]
        assistant = next(message for message in second_messages if message.get("role") == "assistant")
        self.assertEqual([call["id"] for call in assistant["tool_calls"]], ["call-list", "call-sql"])
        rejection = next(message for message in second_messages if message.get("tool_call_id") == "call-sql")
        self.assertIn("tool budget exhausted", rejection["content"])
        events = [json.loads(line) for line in self.runner.records.path.read_text().splitlines()]
        rejected_events = [event for event in events if event["type"] == "tool.rejected"]
        self.assertEqual(rejected_events[0]["tool_call_id"], "call-sql")
        self.assertEqual(rejected_events[0]["count_units"], 0)


if __name__ == "__main__":
    unittest.main()
