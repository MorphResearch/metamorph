from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from llm.adapters import AdapterResponse, ProviderAdapter

from experiments.experience_value.live import CONSOLIDATION_PROMPT, estimate_formal_input_cutoff, estimate_input_tokens
from experiments.experience_value.public_viability_gate_run import _code_hashes, execute
from experiments.experience_value.records import AuthorizationError, RunRecords
from experiments.experience_value.runner import ExperimentRunner
from graphs.loop import run_loop


ROOT = Path(__file__).resolve().parents[3]
PENDING = ROOT / "experiments/experience_value/public_viability_gate.pending.json"
AUTHORIZATION = ROOT / "experiments/experience_value/public_viability_gate.authorization.pending.json"


def tool_call(identifier: str, name: str, arguments: dict[str, str]) -> dict[str, str]:
    return {"id": identifier, "name": name, "arguments": json.dumps(arguments)}


def bind_gate_authorization(pending: Path, authorization: Path) -> None:
    payload = json.loads(authorization.read_text(encoding="utf-8"))
    payload["frozen_pending_config"]["sha256"] = hashlib.sha256(pending.read_bytes()).hexdigest()
    payload["entry_code"]["sha256"] = hashlib.sha256((ROOT / "experiments/experience_value/public_viability_gate_run.py").read_bytes()).hexdigest()
    payload["code_dependencies"] = _code_hashes()
    authorization.write_text(json.dumps(payload), encoding="utf-8")


class GateFakeAdapter(ProviderAdapter):
    """Uses actual public SQL/evaluator code while never contacting a provider."""

    def __init__(self) -> None:
        self.main_steps: dict[str, int] = {}
        self.requests: list[dict[str, object]] = []

    def stream(self, **_kwargs):  # type: ignore[override]
        raise TypeError("test uses configured non-streaming path")

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        task_message = next(message["content"] for message in messages if message.get("role") == "user" and "Task ID:" in message.get("content", ""))
        episode = re.search(r"Task ID: ([^\n]+)", task_message).group(1)  # type: ignore[union-attr]
        self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options)})
        if messages[-1].get("content") == CONSOLIDATION_PROMPT:
            return AdapterResponse(
                tool_calls=[tool_call(f"consolidate-{episode}", "write_file", {"path": "/memory/reusable.txt", "content": "fake reusable note"})],
                usage={"prompt_tokens": 20, "completion_tokens": 5}, stop_reason="tool_calls",
            )
        step = self.main_steps.get(episode, 0)
        self.main_steps[episode] = step + 1
        if step < 15:
            return AdapterResponse(
                tool_calls=[tool_call(f"query-{episode}-{step}", "query_sql", {"sql": ".tables"})],
                usage={"prompt_tokens": 20, "completion_tokens": 5}, stop_reason="tool_calls",
            )
        self.assert_terminal_tools(tools)
        return AdapterResponse(content="0", usage={"prompt_tokens": 20, "completion_tokens": 5}, stop_reason="stop")

    @staticmethod
    def assert_terminal_tools(tools) -> None:
        if tools:
            raise AssertionError("terminal-only request exposed a tool schema")


class NoWriteGateAdapter(GateFakeAdapter):
    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        if messages[-1].get("content") == CONSOLIDATION_PROMPT:
            task_message = next(message["content"] for message in messages if message.get("role") == "user" and "Task ID:" in message.get("content", ""))
            episode = re.search(r"Task ID: ([^\n]+)", task_message).group(1)  # type: ignore[union-attr]
            self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options)})
            return AdapterResponse(content="", usage={"prompt_tokens": 20, "completion_tokens": 1}, stop_reason="stop")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class LargeLegalHistoryGateAdapter(GateFakeAdapter):
    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        task_message = next(message["content"] for message in messages if message.get("role") == "user" and "Task ID:" in message.get("content", ""))
        episode = re.search(r"Task ID: ([^\n]+)", task_message).group(1)  # type: ignore[union-attr]
        if messages[-1].get("content") != CONSOLIDATION_PROMPT and episode == "viability-1-f0" and self.main_steps.get(episode, 0) == 0:
            self.main_steps[episode] = 1
            self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options)})
            return AdapterResponse(
                tool_calls=[tool_call("large-legal-feedback", "query_sql", {"sql": "SELECT quote(zeroblob(7500))"})],
                usage={"prompt_tokens": 20, "completion_tokens": 5}, stop_reason="tool_calls",
            )
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class TwentyFourDecisionAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def stream(self, **_kwargs):
        raise TypeError()

    def complete(self, *, model_name, messages, tools):
        self.calls += 1
        name = "list_dir" if self.calls <= 9 else "query_sql"
        return AdapterResponse(tool_calls=[tool_call(str(self.calls), name, {"path": "/memory"} if name == "list_dir" else {"sql": "SELECT 1"})])


class PublicViabilityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pending, self.authorization = self.root / "pending.json", self.root / "authorization.json"
        shutil.copyfile(PENDING, self.pending)
        shutil.copyfile(AUTHORIZATION, self.authorization)
        bind_gate_authorization(self.pending, self.authorization)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_actual_public_fake_path_reaches_answer_evaluator_and_consolidation(self):
        adapter = GateFakeAdapter()
        report_path = execute(pending_path=self.pending, authorization_path=self.authorization, output_root=self.root / "out", mode="fake", adapter=adapter)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(len(report["episodes"]), 2)
        self.assertTrue(all(episode["native_score"] is not None for episode in report["episodes"]))
        self.assertTrue(all(episode["sql_queries"] == 15 for episode in report["episodes"]))
        self.assertTrue(all(episode["snapshot_files"] == ["reusable.txt"] for episode in report["episodes"]))
        self.assertTrue(all(episode["consolidation"]["allowed_tools"] == ["list_dir", "read_file", "write_file"] for episode in report["episodes"]))
        self.assertTrue(all(episode["consolidation"]["sql_allowed"] is False for episode in report["episodes"]))
        self.assertTrue(all(item["write_request_tool_call_id"].startswith("consolidate-") for episode in report["episodes"] for item in episode["artifact_provenance"]))
        self.assertTrue(all(item["snapshot_hash"] == episode["snapshot_hash"] for episode in report["episodes"] for item in episode["artifact_provenance"]))
        events = [json.loads(line) for line in (report_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(event["type"] == "public_env.action" and event.get("action") == "ANSWER" for event in events), 2)
        self.assertEqual(sum(event["type"] == "public_env.native_evaluator" for event in events), 2)
        self.assertEqual(sum(event["type"] == "terminal_answer.decision_available" for event in events), 2)
        self.assertEqual(sum(event["type"] == "terminal_answer.submitted" for event in events), 2)
        transcripts = (report_path.parent / "provider_transcripts.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("reference SQL", transcripts)
        self.assertNotIn("Ground truth", transcripts)
        terminal_requests = [request for request in adapter.requests if request["tools"] == []]
        self.assertEqual(len(terminal_requests), 2)
        consolidation_requests = [request for request in adapter.requests if request["messages"][-1].get("content") == CONSOLIDATION_PROMPT]
        self.assertEqual(len(consolidation_requests), 2)
        self.assertTrue(all("query_sql" not in [tool["function"]["name"] for tool in request["tools"]] for request in consolidation_requests))

    def test_optional_consolidation_can_legitimately_make_no_artifact(self):
        report = json.loads(execute(pending_path=self.pending, authorization_path=self.authorization, output_root=self.root / "no-write", mode="fake", adapter=NoWriteGateAdapter()).read_text(encoding="utf-8"))
        self.assertTrue(all(episode["snapshot_files"] == [] for episode in report["episodes"]))
        self.assertTrue(all(episode["artifact_provenance"] == [] for episode in report["episodes"]))
        self.assertTrue(all(episode["native_score"] is not None for episode in report["episodes"]))

    def test_full_legal_fifteen_query_history_is_not_stopped_by_old_diagnostic_bias(self):
        report_path = execute(pending_path=self.pending, authorization_path=self.authorization, output_root=self.root / "large-history", mode="fake", adapter=LargeLegalHistoryGateAdapter())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        first = report["episodes"][0]
        self.assertEqual(first["sql_queries"], 15)
        self.assertIsNotNone(first["native_score"])
        events = [json.loads(line) for line in (report_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        starts = [event for event in events if event["type"] == "provider.request_started" and event.get("attempt_id") == first["attempt_id"]]
        self.assertTrue(any(event["input_token_estimate"]["estimated_tokens"] >= 24_000 for event in starts))
        self.assertTrue(all(event["formal_input_cutoff_estimate"]["estimated_tokens"] < 24_000 for event in starts))

    def test_twenty_fourth_decision_does_not_receive_a_twenty_fifth_terminal_request(self):
        with tempfile.TemporaryDirectory() as directory:
            records = RunRecords(Path(directory))
            adapter = TwentyFourDecisionAdapter()
            metrics: dict[str, object] = {}
            run_loop(
                client=object(), model_name="fake", convo=[{"role": "user", "content": "x"}], logger=records,
                max_turns=24, emit=None, ctx={"attempt_id": "terminal-cap"}, adapter=adapter, metrics=metrics,
                allowed_tool_names={"list_dir", "query_sql"}, max_tool_calls=24,
                tool_call_limits={"query_sql": 15}, stop_on_tool_limit_reached=True,
                terminal_only_after_tool_limit_names={"query_sql"},
                tool_schema_provider=lambda _names: [], tool_dispatcher=lambda _n, _a, _c, _allowed: "ok",
            )
            self.assertEqual(adapter.calls, 24)
            self.assertEqual(metrics["runner_stop_reason"], "terminal_answer_unavailable_model_decision_budget_reached")

    def test_calibrated_formal_cutoff_is_not_the_old_diagnostic_cutoff(self):
        messages = [{"role": "user", "content": "word " * 6000}]
        diagnostic = estimate_input_tokens(messages, [])
        formal = estimate_formal_input_cutoff(messages, [], diagnostic=diagnostic)
        self.assertGreater(diagnostic["message_characters"], 24_000)
        self.assertLess(diagnostic["estimated_tokens"], 24_000)
        self.assertLess(formal["estimated_tokens"], diagnostic["estimated_tokens"])
        self.assertEqual(formal["formula"], "ceil(diagnostic_estimated_tokens * 0.50) + 256")

    def test_f1_u1_mount_an_immutable_source_snapshot_but_f0_u0_do_not(self):
        runner = ExperimentRunner(self.root / "workspace")
        source = runner.prepare_task("F0", "test", "source")
        runner.run_scripted(source, lambda runtime: (runtime.write("/memory/reusable.txt", b"note"), "done")[1])
        snapshot = runner.manager.freeze_memory(source.session)
        f0 = runner.prepare_task("F0", "test", "f0", parent=snapshot)
        u0 = runner.prepare_task("U0", "test", "u0", parent=snapshot)
        f1 = runner.prepare_task("F1", "test", "f1", parent=snapshot)
        u1 = runner.prepare_task("U1", "test", "u1", parent=snapshot)
        self.assertIsNone(f0.session.parent_snapshot_id)
        self.assertIsNone(u0.session.parent_snapshot_id)
        self.assertEqual(f1.session.parent_snapshot_id, snapshot.snapshot_id)
        self.assertEqual(u1.session.parent_snapshot_id, snapshot.snapshot_id)
        self.assertEqual(runner.manager.read_agent_file(f1.session, "/memory/reusable.txt"), b"note")
        self.assertEqual(runner.manager.read_agent_file(u1.session, "/memory/reusable.txt"), b"note")

    def test_pending_live_mode_sends_zero_provider_requests(self):
        with self.assertRaises(AuthorizationError):
            execute(pending_path=self.pending, authorization_path=self.authorization, output_root=self.root / "live", mode="live")
