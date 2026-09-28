from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from llm.adapters import AdapterResponse, ProviderAdapter

from experiments.experience_value.file_positive_control_run import evaluate_terminal_result_v2, execute, execute_atomic
from experiments.experience_value.records import AuthorizationError


ROOT = Path(__file__).resolve().parents[3]
PENDING = ROOT / "experiments/experience_value/file_positive_control.pending.json"
TASKS = ROOT / "experiments/experience_value/file_positive_control.tasks.md"
AUTHORIZATION = ROOT / "experiments/experience_value/file_positive_control.authorized_20260921T111831Z.json"
ATOMIC_PENDING = ROOT / "experiments/experience_value/atomic_file_io_control.pending.json"
ATOMIC_TASKS = ROOT / "experiments/experience_value/atomic_file_io_control.tasks.md"
ATOMIC_AUTHORIZATION = ROOT / "experiments/experience_value/atomic_file_io_control.authorization.pending.json"


class FakePositiveControlAdapter(ProviderAdapter):
    """Offline model script; all file and SQLite effects still go through the real loop."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.generation_options = []

    def stream(self, **_kwargs):  # type: ignore[override]
        raise TypeError("fake PC transport uses the non-streaming configured path")

    def complete(self, **_kwargs):  # type: ignore[override]
        raise AssertionError("the entry must use complete_configured")

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        self.requests.append({"model_name": model_name, "messages": deepcopy(messages), "tools": deepcopy(tools)})
        self.generation_options.append(deepcopy(generation_options))
        return self.responses.pop(0)


class CallbackAdapter(ProviderAdapter):
    def __init__(self, callback):
        self.callback, self.requests = callback, []

    def stream(self, **_kwargs):  # type: ignore[override]
        raise TypeError("offline callback adapter")

    def complete(self, **_kwargs):  # type: ignore[override]
        raise AssertionError("configured completion required")

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        self.requests.append({"model_name": model_name, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options)})
        return self.callback(self.requests[-1])


def response(*, content="", tool_calls=None):
    return AdapterResponse(
        content=content, tool_calls=tool_calls or [], usage={"prompt_tokens": 10, "completion_tokens": 5},
        stop_reason="tool_calls" if tool_calls else "stop", request_metadata={"fake": True},
    )


def call(call_id, name, arguments):
    return {"id": call_id, "name": name, "arguments": json.dumps(arguments)}


class FilePositiveControlEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pending = self.root / "pending.json"
        self.tasks = self.root / "tasks.md"
        self.authorization = self.root / "authorization.json"
        shutil.copyfile(PENDING, self.pending)
        shutil.copyfile(TASKS, self.tasks)
        shutil.copyfile(AUTHORIZATION, self.authorization)

    def tearDown(self):
        self.temp.cleanup()

    def _adapter(self):
        return FakePositiveControlAdapter([
            # PC-SOURCE: SQLite feedback, then a model-decided artifact write.
            response(tool_calls=[call("source-sql", "query_sql", {"sql": "SELECT region, cluster FROM regions ORDER BY region"})]),
            response(tool_calls=[call("source-write", "write_file", {"path": "/memory/model-evidence.txt", "content": "coastal is south; observations are 5 and 7."})]),
            response(content="Saved a concise SQLite-derived record."),
            # PC-MEMORY: directory discovery precedes the model-decided read.
            response(tool_calls=[call("memory-list", "list_dir", {"path": "/memory"})]),
            response(tool_calls=[call("memory-read", "read_file", {"path": "/memory/model-evidence.txt"})]),
            response(tool_calls=[call("memory-sql", "query_sql", {"sql": "SELECT AVG(o.value) FROM observations o JOIN regions r ON o.region = r.region WHERE r.cluster = 'coastal'"})]),
            response(content="6. The coastal observations are 5 and 7, whose mean is 6."),
            # PC-EMPTY gets the same probe prompt and tools but has an empty /memory.
            response(tool_calls=[call("empty-list", "list_dir", {"path": "/memory"})]),
            response(tool_calls=[call("empty-sql", "query_sql", {"sql": "SELECT AVG(o.value) FROM observations o JOIN regions r ON o.region = r.region WHERE r.cluster = 'coastal'"})]),
            response(content="6. The coastal observations are 5 and 7, whose mean is 6."),
        ])

    def test_fake_transport_runs_the_frozen_three_episode_entry(self):
        adapter = self._adapter()
        report_path = execute(
            pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization,
            output_root=self.root / "artifacts", mode="fake", adapter=adapter,
        )
        report = json.loads(report_path.read_text(encoding="utf-8").split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual([item["episode_id"] for item in report["episodes"]], ["pc_source_optional_filename", "pc_probe_memory", "pc_probe_empty"])
        self.assertEqual(report["provider_requests_sent"], 10)
        self.assertTrue(report["episodes"][0]["source_artifact_nonempty"])
        self.assertEqual(report["episodes"][0]["source_artifacts"][0]["path"], "model-evidence.txt")
        self.assertTrue(report["episodes"][0]["source_write_sql_feedback_provenance"][0]["preceding_sql_feedback"]["ok"])
        self.assertEqual(report["episodes"][1]["memory_read_source_artifact_paths"], ["/memory/model-evidence.txt"])
        self.assertTrue(report["episodes"][2]["empty_listing_observed"])
        self.assertTrue(report["source_snapshot_unchanged_after_all_probes"])
        self.assertTrue(report["episodes"][1]["parent_snapshot_unchanged"])
        self.assertTrue(report["episodes"][2]["parent_snapshot_unchanged"])
        self.assertTrue(report["episodes"][1]["task_score"]["correct"])
        self.assertTrue(report["episodes"][2]["task_score"]["correct"])
        self.assertEqual(report["episodes"][0]["tool_counts"]["write_file"], {"proposed": 1, "dispatched": 1, "succeeded": 1, "failed": 0})
        self.assertEqual(report["episodes"][1]["tool_counts"]["read_file"]["succeeded"], 1)
        self.assertEqual(report["episodes"][2]["tool_counts"]["list_dir"]["succeeded"], 1)
        # Initial E* user prompts are identical and carry no source path/content or answer.
        memory_initial, empty_initial = adapter.requests[3]["messages"], adapter.requests[7]["messages"]
        self.assertEqual(memory_initial[1]["content"], empty_initial[1]["content"])
        self.assertNotIn("model-evidence.txt", memory_initial[1]["content"])
        self.assertNotIn("coastal is south", memory_initial[1]["content"])
        self.assertNotIn("mean is 6", memory_initial[1]["content"])
        for options in adapter.generation_options:
            self.assertEqual(options["max_tokens"], 512)
            self.assertEqual(options["timeout"], 30)
            self.assertEqual(options["reasoning_effort"], "low")
            self.assertEqual(options["extra_body"], {"thinking": {"type": "enabled"}})
            self.assertTrue(options["omit_tool_choice"])

    def test_hash_mismatch_prevents_any_fake_provider_call(self):
        authorization = json.loads(self.authorization.read_text(encoding="utf-8"))
        authorization["frozen_pending_config"]["sha256"] = "0" * 64
        self.authorization.write_text(json.dumps(authorization), encoding="utf-8")
        adapter = self._adapter()
        with self.assertRaises(AuthorizationError):
            execute(pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization,
                    output_root=self.root / "artifacts", mode="fake", adapter=adapter)
        self.assertEqual(adapter.requests, [])

    def test_plan_only_uses_the_same_parser_and_sends_zero_requests(self):
        plan = execute(pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization,
                       output_root=self.root / "artifacts", mode="plan-only")
        data = json.loads(plan.read_text(encoding="utf-8"))
        self.assertEqual(data["requests_sent"], 0)
        self.assertEqual([episode["id"] for episode in data["episodes"]], ["pc_source_optional_filename", "pc_probe_memory", "pc_probe_empty"])

    def test_terminal_assessment_keeps_correct_terminal_answer_distinct_from_tool_cap(self):
        completed = {"type": "tool.completed", "tool_call_id": "a"}
        feedback = {"type": "tool.feedback_appended", "tool_call_id": "a"}
        finished = {"type": "provider.request_finished"}
        valid = evaluate_terminal_result_v2(answer="6", raw_answer_correct=True, metrics={"tool_calls": 1, "runner_stop_reason": "tool_budget_exhausted"}, events=[completed, feedback, finished, finished], max_requests=2, max_tools=1)
        self.assertTrue(valid["raw_answer_correct"])
        self.assertTrue(valid["answer_format_and_interaction_protocol_valid"])
        self.assertTrue(valid["tool_limit_reached"])
        self.assertFalse(valid["authorization_range_exceeded"])
        self.assertTrue(valid["joint_pass_v2"])
        dsml = evaluate_terminal_result_v2(answer="<tool_calls><invoke>SELECT 1</invoke></tool_calls>", raw_answer_correct=True, metrics={"tool_calls": 1, "runner_stop_reason": "tool_budget_exhausted"}, events=[completed, feedback, finished], max_requests=2, max_tools=1)
        self.assertFalse(dsml["answer_format_and_interaction_protocol_valid"])
        rejected = evaluate_terminal_result_v2(answer="6", raw_answer_correct=True, metrics={"tool_calls": 1, "runner_stop_reason": "tool_budget_exhausted"}, events=[completed, feedback, {"type": "tool.rejected", "tool_call_id": "over"}, finished], max_requests=2, max_tools=1)
        self.assertFalse(rejected["answer_format_and_interaction_protocol_valid"])
        self.assertFalse(rejected["authorization_range_exceeded"])
        unpaired = evaluate_terminal_result_v2(answer="6", raw_answer_correct=True, metrics={"tool_calls": 1, "runner_stop_reason": "model_finished"}, events=[completed, finished], max_requests=2, max_tools=1)
        self.assertFalse(unpaired["answer_format_and_interaction_protocol_valid"])

    def test_atomic_fake_transport_carries_only_sql_returned_marker_across_sessions(self):
        state = {"step": 0, "marker": None}
        def next_response(request):
            step = state["step"]
            state["step"] += 1
            if step == 0:
                return response(tool_calls=[call("write-query", "query_sql", {"sql": "SELECT payload FROM io_probe"})])
            if step == 1:
                tool = next(message for message in request["messages"] if message.get("role") == "tool")
                state["marker"] = json.loads(tool["content"])[0][0]
                return response(tool_calls=[call("write-file", "write_file", {"path": "/memory/saved.txt", "content": state["marker"]})])
            if step == 2:
                return response(content="saved")
            if step == 3:
                return response(tool_calls=[call("read-list", "list_dir", {"path": "/memory"})])
            if step == 4:
                return response(tool_calls=[call("read-file", "read_file", {"path": "/memory/saved.txt"})])
            if step == 5:
                tool = next(message for message in reversed(request["messages"]) if message.get("role") == "tool")
                return response(content=tool["content"])
            raise AssertionError("unexpected fake atomic request")
        adapter = CallbackAdapter(next_response)
        report_path = execute_atomic(pending_path=ATOMIC_PENDING, tasks_path=ATOMIC_TASKS, authorization_path=ATOMIC_AUTHORIZATION,
                                     output_root=self.root / "atomic-artifacts", mode="fake", adapter=adapter)
        report = json.loads(report_path.read_text().split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        write, read = report["episodes"]
        self.assertEqual(report["status"], "COMPLETED")
        self.assertTrue(write["sql_feedback_contained_marker"])
        self.assertTrue(write["source_saved_exact_marker"])
        self.assertTrue(write["marker_was_absent_from_prompt"])
        self.assertEqual(write["tool_counts"]["query_sql"]["succeeded"], 1)
        self.assertEqual(write["tool_counts"]["write_file"]["succeeded"], 1)
        self.assertTrue(read["marker_was_absent_from_initial_prompt"])
        self.assertTrue(read["source_filename_was_absent_from_initial_prompt"])
        self.assertEqual(read["read_source_paths"], ["/memory/saved.txt"])
        self.assertTrue(read["returned_exact_marker"])
        self.assertTrue(read["source_snapshot_unchanged"])
        self.assertNotIn(state["marker"], adapter.requests[3]["messages"][1]["content"])
        self.assertNotIn("saved.txt", adapter.requests[3]["messages"][1]["content"])

    def test_atomic_source_failure_blocks_read_without_a_replacement_file(self):
        adapter = FakePositiveControlAdapter([
            response(tool_calls=[call("write-query", "query_sql", {"sql": "SELECT payload FROM io_probe"})]),
            response(content="I did not save a file."),
        ])
        report_path = execute_atomic(pending_path=ATOMIC_PENDING, tasks_path=ATOMIC_TASKS, authorization_path=ATOMIC_AUTHORIZATION,
                                     output_root=self.root / "atomic-failed", mode="fake", adapter=adapter)
        report = json.loads(report_path.read_text().split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        self.assertFalse(report["episodes"][0]["source_saved_exact_marker"])
        self.assertEqual(report["episodes"][1]["status"], "BLOCKED_SOURCE_ARTIFACT")
        self.assertEqual(report["episodes"][1]["model_requests"], 0)
        self.assertEqual(len(adapter.requests), 2)

    def test_atomic_pending_authorization_rejects_live_before_transport_use(self):
        adapter = CallbackAdapter(lambda _request: (_ for _ in ()).throw(AssertionError("must not call provider")))
        with self.assertRaises(AuthorizationError):
            execute_atomic(pending_path=ATOMIC_PENDING, tasks_path=ATOMIC_TASKS, authorization_path=ATOMIC_AUTHORIZATION,
                           output_root=self.root / "atomic-live-denied", mode="live", adapter=adapter)
        self.assertEqual(adapter.requests, [])


if __name__ == "__main__":
    unittest.main()
