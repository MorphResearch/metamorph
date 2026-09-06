from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from adapters.appworld_adapter import AppWorldController, _artifact_action_name, isolated_provider_request
from adapters.appworld_budget import AppWorldBudgetLedger, BudgetExhausted, BudgetLimits
from adapters.appworld_code_executor import (
    CODE_EXECUTOR_MARKER,
    CODE_EXECUTOR_NAME,
    BatchCodeRejected,
    instrument_batch_code,
    validate_batch_code,
)
from adapters.appworld_contracts import SCHEMA_VERSION, PlannerArtifact, validate_artifact
from adapters.appworld_experiment import AppWorldExperimentRunner, default_world_factory, validate_experiment_config, validate_task_manifest
from adapters.appworld_manifest import stratified_task_ids
from adapters.appworld_dag import Intervention, registered_dags
from llm.adapters import OpenAICompatibleAdapter
from scripts.analyze_appworld_results import e3_profile_rows, paired_task_values


def _function(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


class FakeApiDocs(dict):
    def function_calling(self):
        return [_function(f"{app}__{api}") for app, docs in self.items() for api in docs]


class FakeTracker:
    def __init__(self, success: bool):
        self.success = success

    def to_dict(self, stats_only=False):
        del stats_only
        return {
            "success": self.success,
            "difficulty": 1,
            "num_tests": 1,
            "passes": [{"requirement": "done", "label": None}] if self.success else [],
            "failures": [] if self.success else [{"requirement": "done", "label": None, "trace": ""}],
        }


class FakeWorld:
    def __init__(self, root: Path):
        self.root = root
        self.output_checkpoints_directory = str(root / "checkpoints")
        Path(self.output_checkpoints_directory).mkdir(parents=True, exist_ok=True)
        docs = FakeApiDocs({
            "fake": {
                "read": {"app_name": "fake", "api_name": "read", "method": "GET", "description": "read state"},
                "write": {"app_name": "fake", "api_name": "write", "method": "POST", "description": "write state"},
                "login": {"app_name": "fake", "api_name": "login", "method": "POST", "description": "login"},
            },
            "supervisor": {
                "show_active_task": {"app_name": "supervisor", "api_name": "show_active_task", "method": "GET", "description": "show task"},
                "complete_task": {"app_name": "supervisor", "api_name": "complete_task", "method": "POST", "description": "complete task"},
            },
        })
        self.task = SimpleNamespace(
            instruction="Set done to true.",
            api_docs=docs,
            allowed_apps=["fake", "supervisor"],
        )
        self.state = {"done": False}
        self.executed: list[str] = []

    def execute(self, code: str) -> str:
        self.executed.append(code)
        if "fake__write" in code:
            self.state["done"] = True
            return "written"
        if "fake__read" in code:
            return json.dumps(self.state)
        return "ok"

    def save_state(self, state_id: str):
        path = Path(self.output_checkpoints_directory) / state_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "state.json").write_text(json.dumps(self.state, sort_keys=True), encoding="utf-8")
        return state_id

    def load_state(self, state_id: str):
        path = Path(self.output_checkpoints_directory) / state_id / "state.json"
        self.state = json.loads(path.read_text(encoding="utf-8"))

    def save(self):
        return None

    def evaluate(self, suppress_errors=True):
        del suppress_errors
        return FakeTracker(bool(self.state["done"]))

    def close(self):
        return None


class BatchFakeWorld(FakeWorld):
    """Small request-tracked world that exposes code-batch audit behavior."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.requester = SimpleNamespace(request_tracker=SimpleNamespace(max_num_requests=50))

    def execute(self, code: str) -> str:
        self.executed.append(code)
        calls = []
        # The source calls read inside a loop twice; the transformed code has
        # one static reference but the audit marker reports the runtime count.
        if "'fake__read'" in code:
            calls.extend([("fake__read", {}, True, None), ("fake__read", {}, True, None)])
        if "'fake__write'" in code:
            self.state["done"] = True
            calls.append(("fake__write", {}, True, None))
        return "batch summary\n" + CODE_EXECUTOR_MARKER + repr(calls)


class ScriptedModel:
    model_name = "scripted"

    def __init__(self):
        self.calls: dict[str, int] = {}
        self.messages_by_phase: dict[str, list[dict]] = {}

    def complete(self, *, phase, messages, tools, max_output_tokens):
        del max_output_tokens
        self.messages_by_phase[phase] = deepcopy(messages)
        index = self.calls.get(phase, 0)
        self.calls[phase] = index + 1
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        if phase == "tool_selector":
            return {"content": json.dumps({"schema_version": SCHEMA_VERSION, "tools": ["fake__read", "fake__write", "supervisor__complete_task"], "reason": "needed"}), "usage": usage}
        if phase == "planner" or phase in {"dag_inspect", "dag_inspect_a", "dag_inspect_b", "dag_join"}:
            return {"content": json.dumps({
                "schema_version": SCHEMA_VERSION,
                "status": "READY",
                "task_interpretation": "set done",
                "ordered_actions": [{"app": "fake", "api": "write", "arguments": {}, "purpose": "finish", "expected_state_change": "done"}],
                "verification_criteria": ["done is true"],
                "evidence": [],
                "risks": [],
                "blocked_reason": None,
            }), "usage": usage}
        if phase in {"executor", "repair", "replay_executor", "replay_repair", "dag_act", "dag_repair"} and index == 0:
            available = {item["function"]["name"] for item in tools}
            assert "fake__write" in available
            return {"tool_calls": [{"id": "w", "name": "fake__write", "arguments": "{}"}], "usage": usage}
        if phase in {"executor", "repair", "replay_executor", "replay_repair", "dag_act", "dag_repair"}:
            return {"content": json.dumps({
                "schema_version": SCHEMA_VERSION,
                "status": "COMPLETED",
                "executed_actions": [{"app": "fake", "api": "write", "arguments": {}, "observation": "written", "success": True}],
                "claimed_state_changes": ["done"],
                "errors": [],
                "final_answer": None,
            }), "usage": usage}
        if "verifier" in phase or phase in {"dag_check", "dag_final_check"}:
            return {"content": json.dumps({
                "schema_version": SCHEMA_VERSION,
                "status": "VERIFIED",
                "checks": [{"criterion": "done is true", "evidence": "read state", "passed": True}],
                "discrepancies": [],
                "repair_instructions": [],
            }), "usage": usage}
        raise AssertionError(phase)


class CodeBatchClaimModel(ScriptedModel):
    """Models a valid artifact that names the synthetic batch tool itself."""

    def complete(self, *, phase, messages, tools, max_output_tokens):
        if phase == "dag_act":
            index = self.calls.get(phase, 0)
            self.calls[phase] = index + 1
            self.messages_by_phase[phase] = deepcopy(messages)
            usage = {"prompt_tokens": 10, "completion_tokens": 5}
            if index == 0:
                return {"tool_calls": [{"id": "batch", "name": CODE_EXECUTOR_NAME, "arguments": json.dumps({"code": "value = fake__read()\nprint(value)"})}], "usage": usage}
            return {"content": json.dumps({
                "schema_version": SCHEMA_VERSION, "status": "COMPLETED",
                "executed_actions": [{"app": "metamorph", "api": "execute_code", "arguments": {}, "observation": "batch", "success": True}],
                "claimed_state_changes": [], "errors": [], "final_answer": None,
            }), "usage": usage}
        return super().complete(phase=phase, messages=messages, tools=tools, max_output_tokens=max_output_tokens)


class CapturingCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content="{}", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class OptionsClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)
        self.options = None

    def with_options(self, **kwargs):
        self.options = kwargs
        return self


class MissingUsageModel:
    model_name = "missing-usage"

    def complete(self, **kwargs):
        del kwargs
        return {"content": "answer"}


def limits(**overrides):
    values = dict(max_steps=50, max_errors=5, max_total_tokens=100_000, max_tool_calls=50, max_latency_seconds=300.0, allow_write=True)
    values.update(overrides)
    return BudgetLimits(**values)


class AppWorldContractTests(unittest.TestCase):
    def test_contract_action_accepts_qualified_or_split_api_name(self):
        self.assertEqual(_artifact_action_name("file_system", "login"), "file_system__login")
        self.assertEqual(_artifact_action_name("file_system", "file_system__login"), "file_system__login")

    def test_isolated_provider_request_uses_spawn_safe_worker(self):
        response = isolated_provider_request(
            provider="mock",
            model_name="mock-v0",
            base_url=None,
            api_key_env=None,
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            generation_options={"max_tokens": 10},
            seconds=3,
        )
        self.assertIn("[mock]", response.content)

    def test_code_batch_validator_rejects_dynamic_or_unsafe_python(self):
        with self.assertRaises(BatchCodeRejected):
            validate_batch_code("import os\nos.system('echo unsafe')", allowed_api_names={"fake__read"})
        with self.assertRaises(BatchCodeRejected):
            validate_batch_code("getattr(x, 'run')()", allowed_api_names={"fake__read"})
        with self.assertRaises(BatchCodeRejected):
            validate_batch_code("fake__write()", allowed_api_names={"fake__read"})

    def test_code_batch_instruments_loop_calls_and_accounts_individually(self):
        with tempfile.TemporaryDirectory() as directory:
            world = BatchFakeWorld(Path(directory) / "world")
            code = "for item in range(2):\n    result = fake__read()\nprint(result)"
            validation = validate_batch_code(code, allowed_api_names={"fake__read", "fake__write"})
            self.assertIn("_metamorph_api_call", instrument_batch_code(validation))

            class OneBatchModel:
                model_name = "one-batch"

                def __init__(self):
                    self.calls = 0

                def complete(self, **kwargs):
                    self.calls += 1
                    if self.calls == 1:
                        return {"tool_calls": [{"id": "batch", "name": CODE_EXECUTOR_NAME, "arguments": json.dumps({"code": code})}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
                    return {"content": "done", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

            controller = AppWorldController(
                world=world,
                model=OneBatchModel(),
                limits=limits(max_tool_calls=3),
                trace_dir=Path(directory) / "trace-batch",
            )
            trace, answer = controller._run_phase("probe", "probe", controller._tools(["fake__read"], read_only=True))
            self.assertEqual(answer, "done")
            self.assertEqual(trace.status, "completed")
            self.assertEqual([item["name"] for item in trace.tool_calls], ["fake__read", "fake__read"])
            self.assertEqual(controller.ledger.snapshot()["tool_calls"], 2)
            self.assertEqual(trace.code_batches[0]["api_calls_observed"], 2)

    def test_strict_contract_rejects_markdown_and_missing_fields(self):
        artifact, errors = validate_artifact("```json\n{}\n```", PlannerArtifact)
        self.assertIsNone(artifact)
        self.assertTrue(errors)

    def test_global_tool_budget_cannot_overshoot(self):
        ledger = AppWorldBudgetLedger(limits(max_tool_calls=1))
        ledger.before_tool_call(is_write=False)
        with self.assertRaises(BudgetExhausted):
            ledger.before_tool_call(is_write=False)
        self.assertEqual(ledger.tool_calls, 1)

    def test_global_error_budget_cannot_overshoot(self):
        ledger = AppWorldBudgetLedger(limits(max_errors=1))
        ledger.record_error(tool=True)
        with self.assertRaises(BudgetExhausted):
            ledger.record_error(contract=True)
        self.assertEqual(ledger.errors, 1)
        self.assertEqual(ledger.tool_errors, 1)
        self.assertEqual(ledger.json_contract_violations, 0)

    def test_disabled_gate_records_soft_violation_and_keeps_hard_cap(self):
        ledger = AppWorldBudgetLedger(limits(max_tool_calls=1, enforce=False, emergency_multiplier=2.0))
        ledger.before_tool_call(is_write=False)
        ledger.before_tool_call(is_write=False)
        self.assertIn("max_tool_calls", ledger.snapshot()["violations"])
        with self.assertRaises(BudgetExhausted):
            ledger.before_tool_call(is_write=False)
        self.assertEqual(ledger.tool_calls, 2)

    def test_post_call_token_accounting_stops_completed_phase(self):
        ledger = AppWorldBudgetLedger(limits(max_total_tokens=10))
        ledger.before_model_call(estimated_input_tokens=1, max_output_tokens=1)
        with self.assertRaises(BudgetExhausted):
            ledger.record_model_call({"prompt_tokens": 8, "completion_tokens": 3})
        self.assertTrue(ledger.snapshot()["budget_exhausted"])

    def test_concurrent_model_calls_reserve_shared_token_budget(self):
        ledger = AppWorldBudgetLedger(limits(max_total_tokens=10))
        ledger.before_model_call(estimated_input_tokens=0, max_output_tokens=6)

        def reserve_second_call() -> str:
            try:
                ledger.before_model_call(estimated_input_tokens=0, max_output_tokens=6)
                ledger.cancel_model_call()
                return "reserved"
            except BudgetExhausted:
                return "rejected"

        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual("rejected", pool.submit(reserve_second_call).result())
        ledger.cancel_model_call()

    def test_formal_controller_rejects_missing_token_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = AppWorldController(
                world=FakeWorld(Path(directory) / "world"),
                model=MissingUsageModel(),
                limits=limits(),
                trace_dir=Path(directory) / "trace",
                require_token_usage=True,
            )
            with self.assertRaises(RuntimeError):
                controller._run_phase("probe", "probe", [])
            self.assertEqual(controller.traces["probe"].status, "failed")
            self.assertEqual(controller.ledger.snapshot()["missing_token_usage_calls"], 1)

    def test_fixed_s3_uses_expected_roles_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            world = FakeWorld(Path(directory) / "world")
            model = ScriptedModel()
            controller = AppWorldController(
                world=world,
                model=model,
                limits=limits(),
                trace_dir=Path(directory) / "trace",
            )
            result = controller.run_fixed_s3()
            self.assertTrue(world.state["done"])
            self.assertEqual(set(result["artifacts"]), {"planner", "executor", "verifier", "repair", "verifier_after_repair"})
            self.assertEqual(set(controller.checkpoints), {"initial", "pre_executor", "post_executor", "final"})
            self.assertIn("planner", controller.traces)
            self.assertIn("executor", controller.traces)
            self.assertIn("verifier", controller.traces)
            verifier_prompt = str(model.messages_by_phase["verifier"][-1]["content"])
            self.assertNotIn("PLANNER ARTIFACT", verifier_prompt)
            self.assertIn("EXECUTOR ARTIFACT", verifier_prompt)

    def test_dag_runtime_is_the_new_task_workflow_path(self):
        with tempfile.TemporaryDirectory() as directory:
            world = FakeWorld(Path(directory) / "world")
            controller = AppWorldController(
                world=world,
                model=ScriptedModel(),
                limits=limits(),
                trace_dir=Path(directory) / "trace",
            )
            result = controller.run_dag(registered_dags()["G2"])
            self.assertTrue(world.state["done"])
            execution = result["dag_execution"]
            self.assertEqual("G2", execution["dag_id"])
            self.assertEqual({"inspect_a", "inspect_b", "join", "act", "check"}, set(execution["checkpoints"]))
            self.assertEqual({"initial", "node-inspect_a", "node-inspect_b", "node-join", "node-act", "node-check", "final"}, set(controller.checkpoints))

    def test_executor_accepts_observed_synthetic_code_batch_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = AppWorldController(
                world=BatchFakeWorld(Path(directory) / "world"),
                model=CodeBatchClaimModel(), limits=limits(), trace_dir=Path(directory) / "trace",
            )
            result = controller.run_dag(registered_dags()["G0"])
            self.assertTrue(result["protocol_valid"])
            self.assertEqual("completed", controller.traces["dag_act"].status)

    def test_dag_e1_config_accepts_only_registered_graphs(self):
        config = {
            "benchmark": "AppWorld", "experiment": "DAG_E1", "task_set": "dev",
            "lessons": {"enabled": False}, "seeds": [1],
            "model": {"temperature": 0.0, "prompt_version": "dag-v1", "tool_schema_version": "v1", "max_output_tokens_per_call": 1, "request_timeout_seconds": 1},
            "budget": {"max_steps": 1, "max_errors": 1, "max_total_tokens": 1, "max_tool_calls": 1, "max_latency_seconds": 1, "allow_write": True},
            "conditions": [{"id": "G2", "dag_id": "G2"}],
        }
        validate_experiment_config(config, formal=False)
        config["conditions"] = [{"id": "invalid", "dag_id": "not-a-dag"}]
        with self.assertRaises(ValueError):
            validate_experiment_config(config, formal=False)

    def test_formal_single_seed_requires_explicit_limitation(self):
        config = {
            "benchmark": "AppWorld", "experiment": "DAG_E1", "task_set": "dev",
            "lessons": {"enabled": False}, "seeds": [1],
            "model": {"temperature": 0.0, "prompt_version": "dag-v1", "tool_schema_version": "v1", "max_output_tokens_per_call": 1, "request_timeout_seconds": 1},
            "budget": {"max_steps": 1, "max_errors": 1, "max_total_tokens": 1, "max_tool_calls": 1, "max_latency_seconds": 1, "allow_write": True},
            "conditions": [{"id": "G0", "dag_id": "G0"}],
        }
        with self.assertRaises(ValueError):
            validate_experiment_config(config, formal=True)
        config["statistical_limitations"] = {"single_seed": True}
        validate_experiment_config(config, formal=True)

    def test_default_world_factory_uses_minimal_ground_truth(self):
        observed = {}

        class CapturingAppWorld:
            def __init__(self, **kwargs):
                observed.update(kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"appworld": SimpleNamespace(AppWorld=CapturingAppWorld)}):
            default_world_factory(
                appworld_dir=Path(directory), task_id="task", experiment_name="experiment", seed=1, limits=limits()
            )
        self.assertTrue(observed["load_ground_truth"])
        self.assertEqual("minimal", observed["ground_truth_mode"])

    def test_constrained_model_code_cannot_access_ground_truth_object(self):
        with self.assertRaises(BatchCodeRejected):
            validate_batch_code("world.task.ground_truth.answer", allowed_api_names={"fake__read"})

    def test_dag_checkpoint_replay_uses_upstream_artifact_and_downstream_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_world = FakeWorld(root / "baseline")
            baseline_controller = AppWorldController(
                world=baseline_world, model=ScriptedModel(), limits=limits(), trace_dir=root / "baseline-trace"
            )
            baseline = baseline_controller.run_dag(registered_dags()["G2"])
            source = Path(baseline_controller.checkpoints["node-inspect_a"]["path"])
            source_bytes = (source / "state.json").read_bytes()
            replay_world = FakeWorld(root / "replay")
            imported = Path(replay_world.output_checkpoints_directory) / "source"
            imported.mkdir(parents=True)
            (imported / "state.json").write_bytes(source_bytes)
            replay_world.load_state("source")
            replay_controller = AppWorldController(
                world=replay_world,
                model=ScriptedModel(),
                limits=limits(),
                initial_usage=baseline_controller.checkpoints["node-inspect_a"]["budget"],
                trace_dir=root / "replay-trace",
            )
            replay = replay_controller.run_dag(
                registered_dags()["G2"],
                intervention=Intervention(skipped_nodes=frozenset({"inspect_a", "inspect_b"})),
                initial_artifacts={"inspect_a": baseline["dag_execution"]["artifacts"]["inspect_a"]},
                selected_tools=baseline_controller.selected_tool_names,
            )
            self.assertEqual("skipped_intervention", replay["dag_execution"]["nodes"]["inspect_b"]["status"])
            self.assertEqual("completed", replay["dag_execution"]["nodes"]["join"]["status"])
            self.assertNotIn("dag_inspect_b", replay_controller.traces)
            self.assertEqual(source_bytes, (source / "state.json").read_bytes())

    def test_masked_replay_only_runs_downstream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            world = FakeWorld(root / "baseline")
            baseline_controller = AppWorldController(world=world, model=ScriptedModel(), limits=limits(), trace_dir=root / "base-trace")
            baseline = baseline_controller.run_fixed_s3()
            replay_world = FakeWorld(root / "replay")
            source = Path(baseline_controller.checkpoints["post_executor"]["path"])
            destination = Path(replay_world.output_checkpoints_directory) / "source"
            destination.mkdir(parents=True)
            (destination / "state.json").write_bytes((source / "state.json").read_bytes())
            replay_world.load_state("source")
            replay_controller = AppWorldController(
                world=replay_world,
                model=ScriptedModel(),
                limits=limits(),
                initial_usage=baseline_controller.checkpoints["post_executor"]["budget"],
                trace_dir=root / "replay-trace",
            )
            replay = replay_controller.replay_masked_edge(
                edge=("executor", "verifier"),
                baseline_artifacts=baseline["artifacts"],
                selected_tools=baseline_controller.selected_tool_names,
            )
            self.assertTrue(replay["typed_null_used"])
            self.assertNotIn("replay_executor", replay_controller.traces)
            self.assertIn("replay_verifier", replay_controller.traces)
            self.assertTrue(replay_world.state["done"])

    def test_stratified_selection_is_deterministic(self):
        ids = ["a1", "a2", "b1", "b2", "c1"]
        scenario = lambda item: item[0]
        first = stratified_task_ids(ids, 4, 7, scenario)
        second = stratified_task_ids(list(reversed(ids)), 4, 7, scenario)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertGreaterEqual(len({item[0] for item in first}), 3)

    def test_task_manifest_integrity_rejects_edits(self):
        payload = {
            "schema_version": "appworld.task-manifest.v1",
            "task_ids": ["a"],
            "task_count": 1,
            "splits": {"dev": ["a"]},
        }
        unsigned = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        import hashlib

        payload["selection_hash"] = hashlib.sha256(unsigned.encode("utf-8")).hexdigest()
        validate_task_manifest(payload)
        payload["task_ids"] = ["b"]
        with self.assertRaises(ValueError):
            validate_task_manifest(payload)

    def test_tool_free_provider_phase_omits_empty_tools(self):
        completions = CapturingCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        OpenAICompatibleAdapter(client).complete_configured(
            model_name="test-model",
            messages=[{"role": "user", "content": "route"}],
            tools=[],
            generation_options={"temperature": 0.0, "seed": 7, "max_tokens": 10, "timeout": 12.5},
        )
        self.assertNotIn("tools", completions.kwargs)
        self.assertNotIn("tool_choice", completions.kwargs)
        self.assertEqual(completions.kwargs["timeout"], 12.5)

    def test_provider_phase_binds_timeout_and_disables_sdk_retries(self):
        completions = CapturingCompletions()
        client = OptionsClient(completions)
        OpenAICompatibleAdapter(client).complete_configured(
            model_name="test-model",
            messages=[{"role": "user", "content": "run"}],
            tools=[],
            generation_options={"timeout": 12.5},
        )
        self.assertEqual(client.options, {"max_retries": 0, "timeout": 12.5})
        self.assertNotIn("timeout", completions.kwargs)

    def test_e2_edge_subset_materializes_baseline_and_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "e2.json"
            config_path.write_text(json.dumps({
                "benchmark": "AppWorld",
                "experiment": "E2",
                "experiment_id": "test-e2",
                "task_set": "test",
                "model": {
                    "temperature": 0.0,
                    "prompt_version": "v1",
                    "tool_schema_version": "v1",
                    "max_output_tokens_per_call": 4096,
                    "request_timeout_seconds": 120,
                },
                "lessons": {"enabled": False},
                "budget": {
                    "max_steps": 50,
                    "max_errors": 5,
                    "max_total_tokens": 100000,
                    "max_tool_calls": 50,
                    "max_latency_seconds": 300,
                    "allow_write": True,
                },
                "seeds": [1],
                "base_condition": "Full",
                "component_conditions": [{"id": "Full", "intervention": None}],
                "edge_conditions": [{
                    "id": "Mask-planner-to-executor",
                    "masked_edge": ["planner", "executor"],
                }],
            }), encoding="utf-8")
            unsigned_manifest = {
                "schema_version": "appworld.task-manifest.v1",
                "benchmark": "AppWorld",
                "task_set": "test",
                "appworld_commit": "commit",
                "splits": {"dev": ["task-1"]},
                "task_ids": ["task-1"],
                "task_count": 1,
            }
            import hashlib

            canonical = json.dumps(unsigned_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            unsigned_manifest["selection_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            task_manifest_path = root / "tasks.json"
            task_manifest_path.write_text(json.dumps(unsigned_manifest), encoding="utf-8")

            def world_factory(**kwargs):
                return FakeWorld(root / "worlds" / kwargs["experiment_name"])

            with patch("adapters.appworld_experiment.git_commit", return_value="commit"):
                runner = AppWorldExperimentRunner(
                    config_path=config_path,
                    task_manifest_path=task_manifest_path,
                    appworld_dir=root,
                    output_root=root / "results",
                    model=ScriptedModel(),
                    world_factory=world_factory,
                )
                runner.write_manifest()
                results = runner.run_task("task-1", 1, {"Mask-planner-to-executor"})
            self.assertTrue((root / "results" / "task_manifest.json").exists())
            self.assertEqual([item["condition"] for item in results], ["Full", "Mask-planner-to-executor"])
            self.assertTrue(all(item["status"] == "completed" for item in results))
            self.assertEqual(results[1]["split"], "dev")
            self.assertFalse(results[1]["replay"]["replay_contamination"])
            state = json.loads((root / "results" / "runs" / "Full" / "task-1" / "1" / "run_state.json").read_text())
            self.assertEqual("finished", state["status"])
            self.assertTrue((root / "results" / "runs" / "Full" / "task-1" / "1" / "arm.log").exists())
            self.assertIsNone(results[0]["failure_reason"])

            self.assertIsNone(runner._begin_arm("Probe", "task-1", 1))
            with self.assertRaisesRegex(RuntimeError, "ARM_ALREADY_RUNNING"):
                runner._begin_arm("Probe", "task-1", 1)
            runner.arm_timeout_seconds = 0.01
            timeout_result = runner._safe_run("Timeout", "task-1", 1, lambda: time.sleep(0.05))
            self.assertEqual("timeout", timeout_result["status"])
            self.assertEqual("arm_timeout", timeout_result["failure_reason"])
            timeout_state = json.loads((root / "results" / "runs" / "Timeout" / "task-1" / "1" / "run_state.json").read_text())
            self.assertEqual("timeout", timeout_state["status"])

            self.assertIsNone(runner._begin_arm("ParallelProbe", "task-1", 1))
            runner._active_run_dir = runner._run_dir("ParallelProbe", "task-1", 1)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(
                    lambda phase: runner._arm_event("STAGE_START", {"phase": phase}),
                    ["dag_inspect_a", "dag_inspect_b"],
                ))
            parallel_state = json.loads((runner._active_run_dir / "run_state.json").read_text())
            self.assertEqual("running", parallel_state["status"])
            runner._active_run_dir = None

    def test_paired_analysis_requires_matching_seeds(self):
        results = [
            {"condition": "A", "task_id": "task", "seed": 1, "official_reward": 1},
            {"condition": "A", "task_id": "task", "seed": 2, "official_reward": 1},
            {"condition": "B", "task_id": "task", "seed": 1, "official_reward": 0},
            {"condition": "B", "task_id": "task", "seed": 3, "official_reward": 0},
        ]
        values, missing = paired_task_values(results, "A", "B", "official_reward")
        self.assertEqual(values, [])
        self.assertEqual(missing, ["task"])

    def test_paired_cost_excludes_unknown_cost_instead_of_treating_it_as_zero(self):
        results = [
            {"condition": "G1", "task_id": "a", "seed": 1, "budget": {"total_tokens": 10}},
            {"condition": "G0", "task_id": "a", "seed": 1, "budget": {}},
        ]
        values, missing = paired_task_values(results, "G1", "G0", "total_tokens")
        self.assertEqual([], values)
        self.assertEqual(["a"], missing)

    def test_e3_profile_uses_frozen_family_mapping_not_test_outcomes(self):
        results = [
            {"condition": "G0", "task_id": "a", "seed": 1, "strict_success": False, "cost_usd": 0.1, "protocol_valid": True},
            {"condition": "G2", "task_id": "a", "seed": 1, "strict_success": True, "cost_usd": 0.2, "protocol_valid": True},
            {"condition": "G3", "task_id": "a", "seed": 1, "strict_success": True, "cost_usd": 0.3, "protocol_valid": True},
        ]
        rows, summary = e3_profile_rows(results, {
            "task_family": {"a": "complex"},
            "family_to_dag": {"complex": "G2"},
            "lambda_cost_usd": [1.0],
        })
        self.assertEqual("G2", rows[0]["profile_condition"])
        self.assertEqual(0.8, rows[0]["profile_utility_lambda_1"])
        self.assertEqual(0.8, summary[0]["mean_profile_utility"])


if __name__ == "__main__":
    unittest.main()
