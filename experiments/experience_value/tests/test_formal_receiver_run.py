"""Offline-only acceptance for the sealed Formal Receiver V1 runner."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm.adapters import AdapterResponse, ProviderAdapter

import experiments.experience_value.formal_receiver_run as receiver

ROOT = Path(__file__).resolve().parents[3]


def call(identifier: str, name: str, arguments: dict[str, object]) -> dict[str, str]:
    return {"id": identifier, "name": name, "arguments": json.dumps(arguments)}


class SyntheticTask:
    """No public probe, reference answer, or evaluator is opened in this fixture."""
    synthetic_prompt = "Offline synthetic task: return a short synthetic answer."

    def __init__(self, task_id: int, _records: object) -> None:
        self.task_id, self.answer, self.evaluations, self.successful_queries, self.failed_queries = task_id, None, 0, 0, 0

    def query_sql(self, sql: str) -> str:
        self.successful_queries += 1
        return json.dumps({"synthetic_sql": sql})

    def submit_answer(self, answer: str) -> str:
        self.answer = answer
        return "Synthetic task completed."

    def evaluate_native(self):
        self.evaluations += 1
        return type("SyntheticEvaluation", (), {"score": 1.0, "metrics": {"correct": True, "score": 1.0}})()


class MemoryReadingFake(ProviderAdapter):
    """Synthetic model behavior reads listed resource files without a label hint."""
    def __init__(self) -> None:
        self.requests: list[tuple[list[dict[str, object]], object]] = []

    def stream(self, **_kwargs: object):
        raise TypeError()

    def complete_configured(self, *, model_name: str, messages: list[dict[str, object]], tools: object, generation_options: object) -> AdapterResponse:
        del model_name, generation_options
        self.requests.append((messages, tools))
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if not tool_messages:
            return AdapterResponse(tool_calls=[call("list", "list_dir", {"path": "/memory"})], usage={"prompt_tokens": 20, "completion_tokens": 2}, stop_reason="tool_calls")
        last = str(tool_messages[-1].get("content", ""))
        if len(tool_messages) == 1 and '"entries": []' not in last and '"name"' in last:
            entries = json.loads(last)["entries"]
            return AdapterResponse(tool_calls=[call("read", "read_file", {"path": "/memory/" + entries[0]["name"]})], usage={"prompt_tokens": 20, "completion_tokens": 2}, stop_reason="tool_calls")
        return AdapterResponse(content="synthetic-answer", usage={"prompt_tokens": 20, "completion_tokens": 2}, stop_reason="stop")


class FifteenSqlFake(ProviderAdapter):
    def stream(self, **_kwargs: object):
        raise TypeError()

    def complete_configured(self, *, messages: list[dict[str, object]], **_kwargs: object) -> AdapterResponse:
        count = sum(message.get("role") == "tool" for message in messages)
        if count < 15:
            return AdapterResponse(tool_calls=[call(str(count), "query_sql", {"sql": "SELECT 1"})], usage={"prompt_tokens": 1, "completion_tokens": 1}, stop_reason="tool_calls")
        return AdapterResponse(content="synthetic-answer", usage={"prompt_tokens": 1, "completion_tokens": 1}, stop_reason="stop")


class FormalReceiverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bindings = receiver.verify_frozen_bindings()
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "artifacts/experience_value")
        self.out = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_sealed_bindings_estimator_pricing_and_plan(self) -> None:
        config, prices = receiver.receiver_config(self.bindings)
        self.assertEqual(self.bindings["tool_schema_hash"], "cb9348286035ae1db212e0d5f737b3ced1ede25d7691c709f1cb0d2a914da4ce")
        self.assertEqual(config.max_requests_per_episode, 24)
        self.assertEqual(config.max_input_tokens_per_request, 24000)
        self.assertEqual(config.max_output_tokens_per_request, 8192)
        self.assertEqual(config.worst_case_request_cost(prices), receiver.Decimal("0.03206016"))
        self.assertEqual(config.worst_case_request_cost(prices) * 240, receiver.Decimal("7.69443840"))
        plan = receiver.execution_plan(self.bindings)
        blocks = receiver.block_definition(self.bindings, plan)
        self.assertEqual(len(plan["episodes"]), 30)
        self.assertEqual([row["frozen_token"] for row in plan["episodes"]], self.bindings["manifest"]["execution_order"])
        self.assertEqual([block["probe_task_id"] for block in blocks["blocks"]], [15, 16, 17, 18, 19, 20])
        self.assertTrue(all(block["episode_count"] == 5 and not block["automatically_starts_next_block"] for block in blocks["blocks"]))

    def test_resource_clone_shapes_and_empty(self) -> None:
        runner = receiver.ExperimentRunner(self.out / "resources")
        snapshots = {name: receiver._source_snapshot(name, runner, self.bindings) for name in ("EMPTY", "M_F", "M_U", "RAW_F", "RAW_U")}
        self.assertEqual(snapshots["EMPTY"].files, ())
        self.assertNotIn("experience_006.md", snapshots["M_U"].files)
        self.assertEqual(receiver.sha(snapshots["RAW_F"].path / "raw_f.txt"), self.bindings["addendum"]["receiver_resources"]["RAW_F"]["payload_sha256"])
        self.assertEqual(receiver.sha(snapshots["RAW_U"].path / "raw_u.txt"), self.bindings["addendum"]["receiver_resources"]["RAW_U"]["payload_sha256"])
        before = receiver._resource_tree(snapshots["M_F"].path)
        session = runner.manager.start_task(condition="E*", replicate="test", task_id="synthetic", parent=snapshots["M_F"])
        runner.manager.write_agent_file(session, "/memory/new_local.txt", b"local only")
        self.assertEqual(receiver._resource_tree(snapshots["M_F"].path), before)

    def test_complete_fake_r1_isolated_and_no_public_probe(self) -> None:
        fake = MemoryReadingFake()
        report_path = receiver.execute_block(bindings=self.bindings, block_id="formal_receiver_block_01", output_root=self.out / "fake", mode="fake", adapter=fake, task_factory=SyntheticTask)
        report = json.loads(report_path.read_text())
        self.assertEqual(report["status"], "COMPLETED_OFFLINE_FAKE")
        self.assertEqual(report["formal_native_evaluator_calls"], 0)
        self.assertEqual(report["synthetic_evaluator_invocations"], 5)
        self.assertFalse(report["probe_content_read"])
        self.assertEqual(len(report["episodes"]), 5)
        self.assertEqual([e["frozen_token"] for e in report["episodes"]], ["t15-EMPTY", "t15-M_F", "t15-M_U", "t15-RAW_F", "t15-RAW_U"])
        self.assertEqual(len({e["episode_id"] for e in report["episodes"]}), 5)
        self.assertTrue(all(e["clone_equality_on_start"] and e["sealed_resource_unchanged"] for e in report["episodes"]))
        empty, mounted = report["episodes"][0], report["episodes"][1:]
        self.assertFalse(empty["resource_use"]["resource_present"])
        self.assertFalse(empty["resource_use"]["resource_used"])
        self.assertTrue(all(e["resource_use"]["resource_used"] and e["resource_use"]["files_read"] for e in mounted))
        self.assertTrue(all(e["native_answer_submitted"] and e["evaluator_ran"] and e["post_evaluation_model_calls"] == 0 and not e["consolidation"] for e in report["episodes"]))
        prompts = [str(messages[1]["content"]) for messages, _tools in fake.requests if len(messages) >= 2]
        self.assertTrue(all("M_F" not in prompt and "M_U" not in prompt and "RAW_" not in prompt for prompt in prompts))

    def test_terminal_only_after_sql15_and_unsigned_modes(self) -> None:
        adapter = FifteenSqlFake()
        report_path = receiver.execute_block(bindings=self.bindings, block_id="formal_receiver_block_01", output_root=self.out / "terminal", mode="fake", adapter=adapter, task_factory=SyntheticTask)
        # All five fixtures take the terminal-only path: no SQL16, decision 16 is text.
        report = json.loads(report_path.read_text())
        self.assertTrue(all(e["sql_queries"] == 15 and e["model_decisions"] == 16 for e in report["episodes"]))
        with self.assertRaises(receiver.AuthorizationError):
            receiver.execute_block(bindings=self.bindings, block_id="formal_receiver_block_01", output_root=self.out / "unsigned", mode="live", adapter=adapter, task_factory=SyntheticTask)
        before = len(adapter.__dict__.get("requests", []))
        plan = receiver.execute_block(bindings=self.bindings, block_id="formal_receiver_block_01", output_root=self.out / "plan", mode="plan-only")
        self.assertEqual(json.loads(plan.read_text())["provider_requests"], 0)
        self.assertEqual(len(adapter.__dict__.get("requests", [])), before)


if __name__ == "__main__":
    unittest.main()
