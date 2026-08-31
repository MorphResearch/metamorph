"""Tests for the metamorph agent (no network / no API key required)."""

import json
import tempfile
import unittest
from pathlib import Path

from graphs.agent import run_agent
from tools import (
    get_registered_tools,
    dispatch,
    tool_schemas,
    update_user_memory,
    read_user_memories,
)
from config import Settings
from state.events import EventLogger
from llm.providers import PROVIDER_DEFAULTS, get_supported_providers
from llm.client import build_client
from state.store import RunStore
from multiagent.evaluator import deterministic_report, propose_adjustment
from multiagent.morphology import classify_task
from multiagent.orchestrator import MultiAgentOrchestrator
from api.middleware import safe_workspace_id
from tools.web import _validate_fetch_url


class ToolRegistryTests(unittest.TestCase):
    def test_registry_has_expected_tools(self):
        names = set(get_registered_tools())
        self.assertEqual(
            names,
            {"web_search", "web_fetch", "read_document", "update_user_memory"},
        )

    def test_tool_schemas_are_well_formed(self):
        schemas = {s["function"]["name"]: s for s in tool_schemas()}
        for name in get_registered_tools():
            self.assertIn("parameters", schemas[name]["function"])
            self.assertIn("properties", schemas[name]["function"]["parameters"])


class MemoryToolTests(unittest.TestCase):
    def test_memory_persists_and_updates(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            update_user_memory("create", data_dir, "user", "喜欢用简体中文")
            update_user_memory("create", data_dir, "project", "在做通用 agent")
            mem = read_user_memories(data_dir)
            self.assertIn("user", mem)
            self.assertIn("project", mem)
            # update appends under the same type
            update_user_memory("update", data_dir, "user", "追加偏好")
            mem = read_user_memories(data_dir)
            self.assertEqual(len(mem["user"]), 2)
            # delete clears the type
            update_user_memory("delete", data_dir, "user")
            mem = read_user_memories(data_dir)
            self.assertNotIn("user", mem)

    def test_context_tools_receive_only_their_declared_context(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            workspace = data_dir / "workspace"
            workspace.mkdir()
            (workspace / "note.txt").write_text("hello", encoding="utf-8")
            ctx = {"data_dir": data_dir, "workspace_root": workspace, "max_read_bytes": 100}
            self.assertEqual(dispatch("read_document", {"path": "note.txt"}, ctx), "hello")
            self.assertIn("已新增", dispatch("update_user_memory", {"mode": "create", "content": "x"}, ctx))


class ConfigTests(unittest.TestCase):
    def test_supported_providers(self):
        self.assertIn("mock", get_supported_providers())
        for provider in ("openai", "deepseek", "minimax", "claude", "glm", "sensenova"):
            self.assertIn(provider, get_supported_providers())
            self.assertIn("model", PROVIDER_DEFAULTS[provider])
            self.assertIn("api_key_env", PROVIDER_DEFAULTS[provider])

    def test_settings_defaults(self):
        settings = Settings(data_dir=Path(".metamorph"))
        self.assertEqual(settings.provider, "deepseek")

    def test_security_guards(self):
        with self.assertRaises(ValueError):
            safe_workspace_id("../outside")
        with self.assertRaises(ValueError):
            _validate_fetch_url("http://127.0.0.1:8787/v1/info")
        with self.assertRaises(ValueError):
            _validate_fetch_url("file:///etc/passwd")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_run_lifecycle(self):
        store = RunStore(Path(self._tmp))
        run_id, conv_id = store.create("hello", Path("."))
        self.assertIsNotNone(store.get(run_id))
        self.assertIsNotNone(conv_id)
        store.update(run_id, "completed", {"answer": "hi"})
        self.assertEqual(store.get(run_id)["status"], "completed")

    def test_conversation_history(self):
        store = RunStore(Path(self._tmp))
        _, conv_id = store.create("first question", Path("."))
        store.append_message(conv_id, "user", "Hi, I'm Alice")
        store.append_message(conv_id, "assistant", "Hello Alice!")
        history = store.get_conversation(conv_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Hi, I'm Alice")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["content"], "Hello Alice!")

    def test_conversation_continuity(self):
        store = RunStore(Path(self._tmp))
        _, conv_id = store.create("q1", Path("."))
        store.append_message(conv_id, "user", "What is 1+1?")
        store.append_message(conv_id, "assistant", "2")
        # Same conversation_id → second run picks up history
        _, second_conv_id = store.create("q2", Path("."), conversation_id=conv_id)
        self.assertEqual(second_conv_id, conv_id)
        history = store.get_conversation(conv_id)
        self.assertEqual(len(history), 2)

    def test_conversation_runs_include_results_in_order(self):
        store = RunStore(Path(self._tmp))
        first, conv_id = store.create("q1", Path("."))
        second, _ = store.create("q2", Path("."), conversation_id=conv_id)
        store.update(first, "completed", {"answer": "a1"})
        store.update(second, "completed", {"answer": "a2"})
        runs = store.list_conversation_runs(conv_id)
        self.assertEqual([run["run_id"] for run in runs], [first, second])
        self.assertEqual(runs[1]["result"]["answer"], "a2")


class MultiAgentTests(unittest.TestCase):
    def test_morphology_selects_coding_structure(self):
        morphology = classify_task("分析这个 Python 项目并增加测试，然后检查错误")
        self.assertEqual(morphology.task_kind, "coding")
        self.assertTrue(morphology.needs_verification)

    def test_contribution_report_and_adjustment(self):
        from multiagent.models import AgentResult, AgentRole, ArchitecturePlan

        plan = ArchitecturePlan("test", [], [
            AgentRole("a", "A", "", ""),
            AgentRole("b", "B", "", "", ["a"]),
        ])
        report = deterministic_report(plan, [
            AgentResult("a", "A", "same answer"),
            AgentResult("b", "B", "same answer", ["a"]),
        ])
        self.assertEqual(len(report.agents), 2)
        adjustment = propose_adjustment(plan, report, "medium")
        self.assertTrue(adjustment["requires_human_approval"])

    def test_orchestrator_records_lessons_and_returns_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            events = []

            class Logger:
                def emit(self, event_type, **payload):
                    events.append((event_type, payload))

            def runner(prompt, agent_id):
                return f"{agent_id} result with verification and useful evidence"

            result = MultiAgentOrchestrator(runner, Path(d), Logger()).run("研究并比较两个方案")
            self.assertEqual(result["mode"], "multiagent")
            self.assertIn("contribution_report", result)
            self.assertTrue((Path(d) / "multiagent_lessons.jsonl").exists())
            self.assertIn("architecture.designed", [event[0] for event in events])

    def test_multiagent_report_contains_metrics_and_ablations(self):
        with tempfile.TemporaryDirectory() as d:
            class Logger:
                def emit(self, event_type, **payload):
                    pass

            def runner(prompt, agent_id):
                return {
                    "answer": f"{agent_id} answer",
                    "metrics": {"total_tokens": 10, "latency_seconds": 0.01, "tool_calls": 2},
                }

            result = MultiAgentOrchestrator(runner, Path(d), Logger()).run("研究两个方案")
            report = result["contribution_report"]
            self.assertGreaterEqual(len(report["ablation_results"]), 1)
            self.assertEqual(report["token_cost"], 30)
            self.assertEqual(report["tool_calls"], 6)
            self.assertIn("ablation_performance_delta", report["agents"][0])

    def test_multiagent_role_prompt_includes_conversation_history(self):
        with tempfile.TemporaryDirectory() as d:
            prompts = []

            class Logger:
                def emit(self, event_type, **payload):
                    pass

            def runner(prompt, agent_id):
                prompts.append(prompt)
                return "answer"

            MultiAgentOrchestrator(runner, Path(d), Logger()).run(
                "分析这个方案",
                history=[{"role": "user", "content": "前一个问题"}, {"role": "assistant", "content": "前一个回答"}],
            )
            self.assertTrue(any("前一个问题" in prompt for prompt in prompts))

    def test_task_scorer_drives_ablation_performance_delta(self):
        with tempfile.TemporaryDirectory() as d:
            class Logger:
                def emit(self, event_type, **payload):
                    pass

            def runner(prompt, agent_id):
                return f"{agent_id} answer"

            scorer = lambda answer: 1.0 if answer.strip() == "synthesizer answer" else 0.0
            result = MultiAgentOrchestrator(runner, Path(d), Logger(), task_scorer=scorer).run("分析这个方案")
            ablations = {item["agent_id"]: item for item in result["contribution_report"]["ablation_results"]}
            self.assertEqual(ablations["synthesizer"]["performance_delta"], -1.0)

    def test_dag_executes_independent_roles_in_parallel(self):
        from multiagent.models import AgentRole, ArchitecturePlan, TaskMorphology
        import time

        with tempfile.TemporaryDirectory() as d:
            class Logger:
                def emit(self, event_type, **payload):
                    pass

            active = 0
            peak = 0
            lock = __import__("threading").Lock()

            def runner(prompt, agent_id):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.03)
                with lock:
                    active -= 1
                return f"{agent_id} output"

            orchestrator = MultiAgentOrchestrator(runner, Path(d), Logger(), max_parallelism=2)
            plan = ArchitecturePlan("dag", [], [
                AgentRole("a", "A", "", ""),
                AgentRole("b", "B", "", ""),
                AgentRole("c", "C", "", "", ["a", "b"]),
            ])
            morphology = TaskMorphology("general", "low", True, False, False, True, "low")
            _, results = orchestrator._execute_plan("task", morphology, plan, [], None)
            self.assertEqual([item.agent_id for item in results], ["a", "b", "c"])
            self.assertEqual(peak, 2)


class ExecutorLoopTests(unittest.TestCase):
    """Drive the agent loop with a fake streaming client to verify the
    reasoning / tool / decision event flow without calling any real LLM."""

    def _fake_client(self):
        import types
        calls = {"n": 0}

        class Delta:
            def __init__(self, content=None, reasoning=None, tool_calls=None):
                self.content = content
                self.reasoning_content = reasoning
                self.tool_calls = tool_calls

        class Choice:
            def __init__(self, delta):
                self.delta = delta

        class Chunk:
            def __init__(self, delta):
                self.choices = [Choice(delta)]

        class Stream:
            def __init__(self, chunks):
                self._c = chunks

            def __iter__(self):
                return iter(self._c)

        class Completions:
            def __init__(self, client):
                self.client = client

            def create(self, **kw):
                calls["n"] += 1
                if calls["n"] == 1:
                    tc = types.SimpleNamespace(
                        index=0, id="c1",
                        function=types.SimpleNamespace(
                            name="web_search",
                            arguments=json.dumps({"query": "x", "max_results": 2}),
                        ),
                    )
                    return Stream([
                        Chunk(Delta(reasoning="thinking")),
                        Chunk(Delta(tool_calls=[tc])),
                    ])
                return Stream([Chunk(Delta(content="final answer"))])

        class Chat:
            def __init__(self, client):
                self.completions = Completions(client)

        class Client:
            def __init__(self):
                self.chat = Chat(self)

        return Client()

    def test_agent_loop_runs_tools_then_answers(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            logger = EventLogger(data_dir / "run")
            answer = run_agent(
                client=self._fake_client(),
                model_name="fake",
                messages=[{"role": "user", "content": "hi"}],
                logger=logger,
                data_dir=data_dir,
                workspace_root=Path("."),
                max_turns=5,
            )
            events = logger.read_all()
            types = [e["type"] for e in events]
            self.assertIn("reasoning", types)
            self.assertIn("tool.completed", types)
            self.assertEqual(types.count("model.decision"), 2)
            self.assertEqual(answer, "final answer")


if __name__ == "__main__":
    unittest.main()
