from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import types
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from llm.adapters import AdapterResponse, ProviderAdapter

from experiments.experience_value.clbench_database_exploration import DatabaseExplorationAdapter
from experiments.experience_value.live import estimate_input_tokens
from experiments.experience_value.public_calibration_run import _analysis_outcome, _code_hashes, _offpeak_status, execute
from experiments.experience_value.records import AuthorizationError


ROOT = Path(__file__).resolve().parents[3]
PENDING = ROOT / "experiments/experience_value/public_calibration.pending.json"
TASKS = ROOT / "experiments/experience_value/public_calibration.tasks.md"
AUTHORIZATION = ROOT / "experiments/experience_value/public_calibration.authorization.pending.json"
OFFPEAK_PENDING = ROOT / "experiments/experience_value/public_calibration.offpeak.pending.json"
REVISION_PENDING = ROOT / "experiments/experience_value/public_calibration.revision.pending.json"
REVISION_AUTHORIZATION = ROOT / "experiments/experience_value/public_calibration.revision.authorization.pending.json"
REVISION_V2_PENDING = ROOT / "experiments/experience_value/public_calibration.revision_v2.pending.json"
REVISION_V2_AUTHORIZATION = ROOT / "experiments/experience_value/public_calibration.revision_v2.authorization.pending.json"
REVISION_V3_PENDING = ROOT / "experiments/experience_value/public_calibration.revision_v3.pending.json"
REVISION_V3_AUTHORIZATION = ROOT / "experiments/experience_value/public_calibration.revision_v3.authorization.pending.json"


def bind_test_authorization(pending: Path, tasks: Path, authorization: Path) -> None:
    """Bind copied test fixtures to the current local code, never source records."""
    import hashlib

    payload = json.loads(authorization.read_text(encoding="utf-8"))
    payload["frozen_pending_config"]["sha256"] = hashlib.sha256(pending.read_bytes()).hexdigest()
    payload["frozen_task_manifest"]["sha256"] = hashlib.sha256(tasks.read_bytes()).hexdigest()
    payload["entry_code"]["sha256"] = hashlib.sha256((ROOT / "experiments/experience_value/public_calibration_run.py").read_bytes()).hexdigest()
    payload["code_dependencies"] = _code_hashes()
    authorization.write_text(json.dumps(payload), encoding="utf-8")


def tool_call(identifier: str, name: str, arguments: dict[str, str]) -> dict[str, str]:
    return {"id": identifier, "name": name, "arguments": json.dumps(arguments)}


class FakePublicAdapter(ProviderAdapter):
    """Fake provider only; all public task SQL/evaluation remains real."""

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.steps: dict[str, int] = {}

    def stream(self, **_kwargs):  # type: ignore[override]
        raise TypeError("test uses configured non-streaming provider path")

    def complete(self, **_kwargs):  # type: ignore[override]
        raise AssertionError("public calibration must use complete_configured")

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        user = next(message["content"] for message in messages if message.get("role") == "user")
        episode = re.search(r"Task ID: (dev-[123]-[fu]0)", user).group(1)  # type: ignore[union-attr]
        step = self.steps.get(episode, 0)
        self.steps[episode] = step + 1
        self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options), "model": model_name})
        if episode == "dev-2-u0" and step < 15:
            return AdapterResponse(tool_calls=[tool_call(f"{episode}-sql-{step}", "query_sql", {"sql": ".tables"})], usage={"prompt_tokens": 20, "completion_tokens": 8}, stop_reason="tool_calls")
        # Exercise the independent aggregate file quota.  The ninth file request
        # is intentionally proposed so the loop must reject it while retaining
        # capacity for the subsequent native SQL action and terminal answer.
        if episode == "dev-3-u0" and step < 9:
            return AdapterResponse(tool_calls=[tool_call(f"{episode}-file-{step}", "list_dir", {"path": "/memory"})], usage={"prompt_tokens": 20, "completion_tokens": 8}, stop_reason="tool_calls")
        if episode == "dev-3-u0" and step == 9:
            return AdapterResponse(tool_calls=[tool_call(f"{episode}-sql", "query_sql", {"sql": ".tables"})], usage={"prompt_tokens": 20, "completion_tokens": 8}, stop_reason="tool_calls")
        if episode == "dev-1-f0" and step == 0:
            return AdapterResponse(tool_calls=[tool_call(f"{episode}-list", "list_dir", {"path": "/memory"})], usage={"prompt_tokens": 20, "completion_tokens": 8}, stop_reason="tool_calls")
        if (episode == "dev-1-f0" and step == 1) or (episode != "dev-2-u0" and step == 0):
            return AdapterResponse(tool_calls=[tool_call(f"{episode}-sql", "query_sql", {"sql": ".tables"})], usage={"prompt_tokens": 20, "completion_tokens": 8}, stop_reason="tool_calls")
        return AdapterResponse(content="__development_fake_answer__", usage={"prompt_tokens": 20, "completion_tokens": 8}, stop_reason="stop")


class InputBudgetThenContinueAdapter(FakePublicAdapter):
    """Make only the first episode cross the new token estimate before dispatch."""

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        user = next(message["content"] for message in messages if message.get("role") == "user")
        episode = re.search(r"Task ID: (dev-[123]-[fu]0)", user).group(1)  # type: ignore[union-attr]
        step = self.steps.get(episode, 0)
        if episode == "dev-1-f0" and step == 0:
            self.steps[episode] = 1
            self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options), "model": model_name})
            return AdapterResponse(tool_calls=[tool_call("large-feedback", "query_sql", {"sql": "SELECT quote(zeroblob(30000))"})], usage={"prompt_tokens": 20, "completion_tokens": 8}, stop_reason="tool_calls")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class SystemicFailureAdapter(FakePublicAdapter):
    def complete_configured(self, **_kwargs):  # type: ignore[override]
        raise RuntimeError("injected systemic adapter failure")


class LengthResponseAdapter(FakePublicAdapter):
    """Expose the provider's terminal length response without a retry."""

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        user = next(message["content"] for message in messages if message.get("role") == "user")
        episode = re.search(r"Task ID: (dev-[123]-[fu]0)", user).group(1)  # type: ignore[union-attr]
        step = self.steps.get(episode, 0)
        if episode == "dev-1-f0" and step == 0:
            self.steps[episode] = 1
            self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options), "model": model_name})
            return AdapterResponse(content="", usage={"prompt_tokens": 20, "completion_tokens": 8192}, stop_reason="length")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class APITimeoutError(Exception):
    """Name matches the reviewed provider transport exception without an SDK call."""


class FirstTimeoutThenRecoverAdapter(FakePublicAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.first_failure_sent = False

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        user = next(message["content"] for message in messages if message.get("role") == "user")
        episode = re.search(r"Task ID: (dev-[123]-[fu]0)", user).group(1)  # type: ignore[union-attr]
        if episode == "dev-1-f0" and not self.first_failure_sent:
            self.first_failure_sent = True
            self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options), "model": model_name})
            raise APITimeoutError("injected pre-response timeout")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class RetryTwiceTimeoutAdapter(FakePublicAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 0

    def complete_configured(self, *, model_name, messages, tools, generation_options):  # type: ignore[override]
        user = next(message["content"] for message in messages if message.get("role") == "user")
        episode = re.search(r"Task ID: (dev-[123]-[fu]0)", user).group(1)  # type: ignore[union-attr]
        if episode == "dev-1-f0" and self.failures < 2:
            self.failures += 1
            self.requests.append({"episode": episode, "messages": deepcopy(messages), "tools": deepcopy(tools), "options": deepcopy(generation_options), "model": model_name})
            raise APITimeoutError("injected retry timeout")
        return super().complete_configured(model_name=model_name, messages=messages, tools=tools, generation_options=generation_options)


class PublicCalibrationEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.pending, self.tasks, self.authorization = root / "pending.json", root / "tasks.md", root / "authorization.json"
        shutil.copyfile(PENDING, self.pending)
        shutil.copyfile(TASKS, self.tasks)
        shutil.copyfile(AUTHORIZATION, self.authorization)
        bind_test_authorization(self.pending, self.tasks, self.authorization)
        self.output = root / "artifacts"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fake_transport_executes_all_six_public_episodes(self):
        transport = FakePublicAdapter()
        report_path = execute(pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization, output_root=self.output, mode="fake", adapter=transport)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual([episode["episode_id"] for episode in report["episodes"]], ["dev-1-f0", "dev-1-u0", "dev-2-u0", "dev-2-f0", "dev-3-f0", "dev-3-u0"])
        self.assertEqual([episode["task_id"] for episode in report["episodes"]], ["1", "1", "2", "2", "3", "3"])
        self.assertEqual(len({episode["conversation_id"] for episode in report["episodes"]}), 6)
        self.assertEqual(len({episode["attempt_id"] for episode in report["episodes"]}), 6)
        events = [json.loads(line) for line in (report_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
        prepared_events = [event for event in events if event.get("type") == "task.prepared"]
        self.assertEqual(len(prepared_events), 6)
        self.assertTrue(all(event["parent_snapshot_id"] is None for event in prepared_events))
        self.assertEqual(report["paid_evaluator_requests_sent"], 0)
        endpoint = next(episode for episode in report["episodes"] if episode["episode_id"] == "dev-2-u0")
        self.assertEqual(endpoint["sql_queries"], 15)
        self.assertEqual(endpoint["tool_counts"]["query_sql"]["dispatched"], 15)
        self.assertEqual(endpoint["file_operations"], 0)
        self.assertEqual(endpoint["runner_stop_reason"], "PER_EPISODE_RESOURCE_STOP")
        self.assertEqual(endpoint["resource_stop_reason"], "query_sql_budget_reached")
        self.assertIsNone(endpoint["native_score"])
        separated = next(episode for episode in report["episodes"] if episode["episode_id"] == "dev-3-u0")
        self.assertEqual(separated["file_operations"], 8)
        self.assertEqual(separated["sql_queries"], 0)
        self.assertEqual(separated["runner_stop_reason"], "PER_EPISODE_RESOURCE_STOP")
        self.assertEqual(separated["resource_stop_reason"], "file_operations_budget_reached")
        source = next(episode for episode in report["episodes"] if episode["episode_id"] == "dev-1-f0")
        self.assertEqual(source["file_operations"], 1)
        self.assertEqual(source["sql_queries"], 1)
        self.assertTrue(all(episode["sql_queries"] <= 15 and episode["file_operations"] <= 8 for episode in report["episodes"]))
        f0 = next(request for request in transport.requests if request["episode"] == "dev-1-f0")["messages"]
        u0 = next(request for request in transport.requests if request["episode"] == "dev-1-u0")["messages"]
        f0_user = next(message["content"] for message in f0 if message.get("role") == "user")
        u0_user = next(message["content"] for message in u0 if message.get("role") == "user")
        self.assertNotEqual(f0_user, u0_user)
        self.assertIn("Question 1/1", f0_user)
        self.assertIn("Question 1/1", u0_user)
        serialized = json.dumps(transport.requests, ensure_ascii=False)
        self.assertNotIn("Ground truth", serialized)
        self.assertNotIn("reference SQL", serialized)
        self.assertTrue(all(request["options"]["max_tokens"] == 2048 for request in transport.requests))
        self.assertEqual({episode["request_config_hash"] for episode in report["episodes"]}, {report["episodes"][0]["request_config_hash"]})

    def test_token_estimator_does_not_treat_characters_as_tokens(self):
        estimate = estimate_input_tokens([{"role": "user", "content": "word " * 6000}], [])
        self.assertGreater(estimate["message_characters"], 24_000)
        self.assertLess(estimate["estimated_tokens"], 24_000)
        self.assertEqual(estimate["estimator"], "calibrated_utf8_half_bytes_plus_chat_tool_overhead_v1")

    def test_revision_candidate_uses_token_budget_through_same_entry(self):
        pending, authorization = Path(self.temp.name) / "revision.json", Path(self.temp.name) / "revision.auth.json"
        shutil.copyfile(REVISION_PENDING, pending)
        shutil.copyfile(REVISION_AUTHORIZATION, authorization)
        bind_test_authorization(pending, self.tasks, authorization)
        report_path = execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision", mode="fake", adapter=FakePublicAdapter())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(len(report["episodes"]), 6)
        self.assertTrue(all(episode["request_config_hash"] == report["episodes"][0]["request_config_hash"] for episode in report["episodes"]))
        with self.assertRaises(AuthorizationError):
            execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-live", mode="live")

    def test_revision_v2_sends_8192_to_boundary_and_records_length_without_retry(self):
        pending, authorization = Path(self.temp.name) / "revision-v2.json", Path(self.temp.name) / "revision-v2.auth.json"
        shutil.copyfile(REVISION_V2_PENDING, pending)
        shutil.copyfile(REVISION_V2_AUTHORIZATION, authorization)
        bind_test_authorization(pending, self.tasks, authorization)
        normal = FakePublicAdapter()
        report_path = execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-v2", mode="fake", adapter=normal)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "COMPLETED")
        self.assertTrue(normal.requests)
        self.assertTrue(all(request["options"]["max_tokens"] == 8192 for request in normal.requests))
        self.assertEqual({episode["request_config_hash"] for episode in report["episodes"]}, {report["episodes"][0]["request_config_hash"]})
        length = LengthResponseAdapter()
        length_report = json.loads(execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-v2-length", mode="fake", adapter=length).read_text(encoding="utf-8"))
        first = length_report["episodes"][0]
        self.assertEqual(first["runner_stop_reason"], "PER_EPISODE_RESOURCE_STOP")
        self.assertEqual(first["resource_stop_reason"], "output_token_limit_reached")
        self.assertEqual(len([request for request in length.requests if request["episode"] == "dev-1-f0"]), 1)
        events = [json.loads(line) for line in (self.output / "revision-v2-length" / length_report["run_id"] / "research_records" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        finished = [event for event in events if event.get("type") == "provider.request_finished" and event.get("attempt_id") == first["attempt_id"]]
        self.assertEqual(finished[-1]["stop_reason"], "length")
        with self.assertRaises(AuthorizationError):
            execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-v2-live", mode="live")

    def test_revision_v3_retries_exactly_once_and_counts_only_response_as_decision(self):
        pending, authorization = Path(self.temp.name) / "revision-v3.json", Path(self.temp.name) / "revision-v3.auth.json"
        shutil.copyfile(REVISION_V3_PENDING, pending)
        shutil.copyfile(REVISION_V3_AUTHORIZATION, authorization)
        bind_test_authorization(pending, self.tasks, authorization)
        transport = FirstTimeoutThenRecoverAdapter()
        report_path = execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-v3-recovered", mode="fake", adapter=transport)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "COMPLETED")
        first = report["episodes"][0]
        self.assertTrue(first["transport_retry"]["transport_retry_attempted"])
        self.assertTrue(first["transport_retry"]["infra_recovered"])
        self.assertEqual(first["model_requests_attempted"], first["model_requests_completed"] + 1)
        first_calls = [request for request in transport.requests if request["episode"] == "dev-1-f0"]
        self.assertGreaterEqual(len(first_calls), 2)
        self.assertEqual(first_calls[0]["messages"], first_calls[1]["messages"])
        self.assertEqual(first_calls[0]["tools"], first_calls[1]["tools"])
        self.assertEqual(first_calls[0]["options"], first_calls[1]["options"])
        self.assertTrue(all(request["options"]["timeout"] == 120 for request in transport.requests))
        events = [json.loads(line) for line in (report_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        starts = [event for event in events if event.get("type") == "provider.request_started" and event.get("attempt_id") == first["attempt_id"]]
        self.assertEqual(starts[0]["request_body_hash"], starts[1]["request_body_hash"])
        decisions = [event for event in events if event.get("type") == "model.decision"]
        completed_responses = [event for event in events if event.get("type") == "provider.request_finished"]
        self.assertEqual(len(decisions), len(completed_responses))
        self.assertEqual({episode["request_config_hash"] for episode in report["episodes"]}, {report["episodes"][0]["request_config_hash"]})
        manifest = json.loads((report_path.parent / "public_calibration_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["max_transport_retries"], 1)

    def test_revision_v3_second_transport_failure_is_invalid_infra_without_third_attempt(self):
        pending, authorization = Path(self.temp.name) / "revision-v3.json", Path(self.temp.name) / "revision-v3.auth.json"
        shutil.copyfile(REVISION_V3_PENDING, pending)
        shutil.copyfile(REVISION_V3_AUTHORIZATION, authorization)
        bind_test_authorization(pending, self.tasks, authorization)
        transport = RetryTwiceTimeoutAdapter()
        report = json.loads(execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-v3-timeout", mode="fake", adapter=transport).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "INFRA_FAILURE")
        self.assertEqual(len(report["episodes"]), 1)
        first = report["episodes"][0]
        self.assertEqual(first["analysis_status"], "INVALID_INFRA")
        self.assertIsNone(first["analysis_score"])
        self.assertEqual(first["model_requests_attempted"], 2)
        self.assertEqual(first["model_requests_completed"], 0)
        self.assertEqual(len(transport.requests), 2)

    def test_revision_v3_length_response_is_not_transport_retried_and_scoring_is_frozen(self):
        pending, authorization = Path(self.temp.name) / "revision-v3.json", Path(self.temp.name) / "revision-v3.auth.json"
        shutil.copyfile(REVISION_V3_PENDING, pending)
        shutil.copyfile(REVISION_V3_AUTHORIZATION, authorization)
        bind_test_authorization(pending, self.tasks, authorization)
        length = LengthResponseAdapter()
        report = json.loads(execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-v3-length", mode="fake", adapter=length).read_text(encoding="utf-8"))
        first = report["episodes"][0]
        self.assertEqual(first["analysis_status"], "RESOURCE_LIMITED_FAILURE")
        self.assertEqual(first["analysis_score"], 0)
        self.assertEqual(len([request for request in length.requests if request["episode"] == "dev-1-f0"]), 1)
        for reason in ("input_token_budget_reached", "output_token_limit_reached", "max_turns_reached", "file_operations_budget_reached", "latency budget exhausted", "query_sql_budget_reached"):
            outcome = _analysis_outcome(resource_stop_reason=reason)
            self.assertEqual(outcome, {"analysis_score": 0, "analysis_status": "RESOURCE_LIMITED_FAILURE"})
        self.assertEqual(_analysis_outcome(infrastructure_failure=True), {"analysis_score": None, "analysis_status": "INVALID_INFRA"})
        self.assertEqual(_analysis_outcome(system_failure=True), {"analysis_score": None, "analysis_status": "INVALID_SYSTEM"})
        self.assertEqual(_analysis_outcome(native_score=0, evaluator_ran=True), {"analysis_score": 0, "analysis_status": "EVALUATED_NATIVE"})
        with self.assertRaises(AuthorizationError):
            execute(pending_path=pending, tasks_path=self.tasks, authorization_path=authorization, output_root=self.output / "revision-v3-live", mode="live")

    def test_input_token_resource_stop_continues_with_fresh_next_episode(self):
        transport = InputBudgetThenContinueAdapter()
        report_path = execute(pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization, output_root=self.output, mode="fake", adapter=transport)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        first = report["episodes"][0]
        self.assertEqual(first["runner_stop_reason"], "PER_EPISODE_RESOURCE_STOP")
        self.assertEqual(first["resource_stop_reason"], "input_token_budget_reached")
        self.assertEqual(first["model_requests_attempted"], 1)
        self.assertEqual(len(report["episodes"]), 6)
        self.assertEqual(report["episodes"][1]["episode_id"], "dev-1-u0")
        events = [json.loads(line) for line in (report_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        prepared = [event for event in events if event.get("type") == "task.prepared"]
        self.assertEqual(len(prepared), 6)
        self.assertTrue(all(event["parent_snapshot_id"] is None for event in prepared))
        blocked = [event for event in events if event.get("type") == "provider.request_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertGreaterEqual(blocked[0]["input_token_estimate"]["estimated_tokens"], 24_000)

    def test_batch_level_failure_still_stops_all_later_episodes(self):
        transport = SystemicFailureAdapter()
        report_path = execute(pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization, output_root=self.output, mode="fake", adapter=transport)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "STOPPED")
        self.assertEqual([episode["episode_id"] for episode in report["episodes"]], ["dev-1-f0"])
        self.assertEqual(transport.requests, [])

    def test_hash_mismatch_and_pending_live_authorization_send_zero_provider_requests(self):
        payload = json.loads(self.authorization.read_text(encoding="utf-8"))
        payload["frozen_pending_config"]["sha256"] = "0" * 64
        self.authorization.write_text(json.dumps(payload), encoding="utf-8")
        transport = FakePublicAdapter()
        with self.assertRaises(AuthorizationError):
            execute(pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization, output_root=self.output, mode="fake", adapter=transport)
        self.assertEqual(transport.requests, [])
        shutil.copyfile(AUTHORIZATION, self.authorization)
        with self.assertRaises(AuthorizationError):
            execute(pending_path=self.pending, tasks_path=self.tasks, authorization_path=self.authorization, output_root=self.output, mode="live")

    def test_live_dependency_check_rejects_an_import_shim(self):
        original = sys.modules.get("litellm")
        sys.modules["litellm"] = types.ModuleType("litellm")
        try:
            with self.assertRaises(RuntimeError):
                DatabaseExplorationAdapter.assert_real_litellm_available()
        finally:
            if original is None:
                del sys.modules["litellm"]
            else:
                sys.modules["litellm"] = original

    def test_offpeak_window_uses_asia_shanghai_and_preserves_episode_margin(self):
        pending = json.loads(OFFPEAK_PENDING.read_text(encoding="utf-8"))
        start = _offpeak_status(pending, for_new_episode=True, now=datetime(2026, 9, 21, 18, 5, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertTrue(start["request_allowed"])
        self.assertTrue(start["new_episode_allowed"])
        near_end = _offpeak_status(pending, for_new_episode=True, now=datetime(2026, 9, 22, 8, 38, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertTrue(near_end["request_allowed"])
        self.assertFalse(near_end["new_episode_allowed"])
        outside = _offpeak_status(pending, now=datetime(2026, 9, 22, 10, 7, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertFalse(outside["request_allowed"])
        self.assertEqual(outside["timezone"], "Asia/Shanghai")


if __name__ == "__main__":
    unittest.main()
