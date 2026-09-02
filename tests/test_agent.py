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
from multiagent.routing import heuristic_route, load_oracle_labels, task_features
from multiagent.orchestrator import MultiAgentOrchestrator
from multiagent.models import AgentRole, ArchitecturePlan, BudgetPolicy
from multiagent.contracts import compile_plan
from multiagent.lessons import LessonStore
from api.middleware import safe_workspace_id
from tools.web import _validate_fetch_url
from multiagent.utility import aggregate_metrics


class ToolRegistryTests(unittest.TestCase):
    def test_registry_has_expected_tools(self):
        names = set(get_registered_tools())
        self.assertEqual(
            names,
            {"web_search", "web_fetch", "list_files", "read_document", "write_file", "update_user_memory", "update_task_list"},
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
            update_user_memory("create", data_dir, "user", "喜欢用简体中文", allow_write=True)
            update_user_memory("create", data_dir, "project", "在做通用 agent", allow_write=True)
            mem = read_user_memories(data_dir)
            self.assertIn("user", mem)
            self.assertIn("project", mem)
            # update appends under the same type
            update_user_memory("update", data_dir, "user", "追加偏好", allow_write=True)
            mem = read_user_memories(data_dir)
            self.assertEqual(len(mem["user"]), 2)
            # delete clears the type
            update_user_memory("delete", data_dir, "user", allow_write=True)
            mem = read_user_memories(data_dir)
            self.assertNotIn("user", mem)

    def test_context_tools_receive_only_their_declared_context(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            workspace = data_dir / "workspace"
            workspace.mkdir()
            (workspace / "note.txt").write_text("hello", encoding="utf-8")
            ctx = {"data_dir": data_dir, "workspace_root": workspace, "max_read_bytes": 100, "allow_write": True}
            self.assertEqual(dispatch("read_document", {"path": "note.txt"}, ctx), "hello")
            self.assertIn("已新增", dispatch("update_user_memory", {"mode": "create", "content": "x"}, ctx))

    def test_write_tools_are_denied_without_write_policy(self):
        with tempfile.TemporaryDirectory() as d:
            result = dispatch("update_user_memory", {"mode": "create", "content": "x"}, {"data_dir": Path(d)})
            self.assertTrue(result.startswith("工具执行被拒绝："))


class WriteFileToolTests(unittest.TestCase):
    def test_write_file_creates_dirs_and_content(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d)
            ctx = {"workspace_root": workspace, "allow_write": True}
            result = dispatch(
                "write_file",
                {"path": "reports/sub/summary.md", "content": "# 摘要\n内容"},
                ctx,
            )
            self.assertIn("已写入", result)
            target = workspace / "reports" / "sub" / "summary.md"
            self.assertEqual(target.read_text(encoding="utf-8"), "# 摘要\n内容")

    def test_write_file_denied_without_write_policy(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = {"workspace_root": Path(d)}
            result = dispatch("write_file", {"path": "a.txt", "content": "x"}, ctx)
            self.assertTrue(result.startswith("工具执行被拒绝："))

    def test_write_file_rejects_workspace_escape(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d) / "ws"
            workspace.mkdir()
            ctx = {"workspace_root": workspace, "allow_write": True}
            result = dispatch("write_file", {"path": "../escape.txt", "content": "x"}, ctx)
            self.assertIn("不允许访问工作区之外的路径", result)
            self.assertFalse((Path(d) / "escape.txt").exists())


class ListFilesToolTests(unittest.TestCase):
    def _make_tree(self, workspace: Path) -> None:
        (workspace / "myproj" / "src").mkdir(parents=True)
        (workspace / "myproj" / "docs").mkdir()
        (workspace / "myproj" / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
        (workspace / "myproj" / "README.md").write_text("# demo", encoding="utf-8")
        (workspace / "top.txt").write_text("top", encoding="utf-8")

    def test_list_files_non_recursive(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d)
            self._make_tree(workspace)
            ctx = {"workspace_root": workspace}
            result = dispatch("list_files", {}, ctx)
            self.assertIn("[目录] myproj/", result)
            self.assertIn("[文件] top.txt", result)

    def test_list_files_recursive_and_pattern(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d)
            self._make_tree(workspace)
            ctx = {"workspace_root": workspace}
            result = dispatch("list_files", {"recursive": True}, ctx)
            self.assertIn("myproj/src/main.py", result)
            self.assertIn("myproj/README.md", result)
            # 通配符只保留匹配的文件，目录项仍在
            only_py = dispatch("list_files", {"recursive": True, "pattern": "*.py"}, ctx)
            self.assertIn("myproj/src/main.py", only_py)
            self.assertNotIn("README.md", only_py)

    def test_list_files_rejects_escape(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d) / "ws"
            workspace.mkdir()
            ctx = {"workspace_root": workspace}
            result = dispatch("list_files", {"path": ".."}, ctx)
            self.assertIn("不允许访问工作区之外的路径", result)

    def test_workspace_folder_is_discoverable_and_readable(self):
        """端到端：本地工作空间里的目录（无需上传），Agent 可 list_files 发现并 read_document 读取。"""
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "myproj" / "src"
            target.mkdir(parents=True)
            (target / "app.py").write_text("print('v1')", encoding="utf-8")

            ctx = {"workspace_root": Path(d), "max_read_bytes": 100_000, "allow_write": True}
            listing = dispatch("list_files", {"recursive": True}, ctx)
            self.assertIn("myproj/src/app.py", listing)
            self.assertEqual(dispatch("read_document", {"path": "myproj/src/app.py"}, ctx), "print('v1')")


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
    def test_routing_features_do_not_depend_on_gold_outcome(self):
        features = task_features("If the first meeting is cancelled, move all related tasks", domain_count=2)
        self.assertTrue(features["has_condition"])
        self.assertEqual(features["domain_count"], 2)
        route, _ = heuristic_route("If the first meeting is cancelled, move all related tasks", domain_count=2)
        self.assertEqual(route, "complex")

    def test_oracle_labels_are_strict(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "labels.json"
            path.write_text('{"labels":{"calendar:0":"simple"}}', encoding="utf-8")
            self.assertEqual(load_oracle_labels(path)["calendar:0"], "simple")

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

    def test_task_success_is_unknown_without_task_scorer(self):
        from multiagent.models import AgentResult

        report = deterministic_report(
            ArchitecturePlan("test", [], [AgentRole("a", "A", "", "")]),
            [AgentResult("a", "A", "non-empty answer")],
        )
        self.assertIsNone(report.task_success_rate)
        self.assertIsNone(report.agents[0].task_success_rate)

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
            self.assertIn("causal_audits", result)
            self.assertIn("architecture.designed", [event[0] for event in events])

    def test_dag_compiler_rejects_cycles_and_bad_dependencies(self):
        cyclic = ArchitecturePlan("cycle", [], [
            AgentRole("a", "A", "", "", ["b"]),
            AgentRole("b", "B", "", "", ["a"]),
        ])
        compiled = compile_plan(cyclic)
        self.assertFalse(compiled["valid"])
        self.assertIn("dependency graph is cyclic", compiled["issues"])

    def test_causal_edge_audit_uses_typed_null_and_promotes_repeated_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            prompts = []

            class Logger:
                def emit(self, event_type, **payload):
                    pass

            def runner(prompt, agent_id):
                prompts.append(prompt)
                if "typed-null-artifact" in prompt or "BROKEN" in prompt:
                    answer = "BROKEN"
                else:
                    answer = "GOOD"
                return {"answer": answer, "metrics": {"total_tokens": 1, "tool_calls": 0}}

            scorer = lambda answer: 0.0 if "BROKEN" in answer else 1.0
            orchestrator = MultiAgentOrchestrator(
                runner,
                Path(d),
                Logger(),
                task_scorer=scorer,
                budget_policy=BudgetPolicy(max_causal_audits=1, uncertainty_penalty=0.01),
            )
            first = orchestrator.run("研究一个问题", source_run="run-1")
            second = orchestrator.run("研究一个问题", source_run="run-2")
            self.assertTrue(any("typed-null-artifact" in prompt for prompt in prompts))
            self.assertEqual(first["causal_audits"][0]["status"], "completed")
            self.assertGreater(
                first["causal_audits"][0]["intervention_metrics"]["token_cost"],
                first["causal_audits"][0]["replay_metrics"]["token_cost"],
            )
            lessons = LessonStore(Path(d)).all()
            self.assertEqual(len(lessons), 1)
            self.assertEqual(lessons[0]["status"], "Active")
            self.assertGreater(lessons[0]["strength"], 0.0)
            self.assertEqual(second["lesson_admissions"][0]["status"], "Active")

    def test_budget_gate_stops_causal_audits_before_replay(self):
        with tempfile.TemporaryDirectory() as d:
            prompts = []

            class Logger:
                def emit(self, event_type, **payload):
                    pass

            def runner(prompt, agent_id):
                prompts.append(prompt)
                return {"answer": "answer", "metrics": {"total_tokens": 1}}

            result = MultiAgentOrchestrator(
                runner,
                Path(d),
                Logger(),
                budget_policy=BudgetPolicy(max_total_tokens=3, max_causal_audits=2),
            ).run("研究一个问题")
            self.assertTrue(all(item["status"] == "stopped" for item in result["causal_audits"]))
            self.assertFalse(any("typed-null-artifact" in prompt for prompt in prompts))

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

    def test_unscored_run_does_not_claim_task_success(self):
        with tempfile.TemporaryDirectory() as d:
            class Logger:
                def emit(self, event_type, **payload):
                    pass

            result = MultiAgentOrchestrator(
                lambda prompt, agent_id: {"answer": "non-empty", "metrics": {"total_tokens": 1}},
                Path(d),
                Logger(),
                enable_evaluator=False,
            ).run("研究一个问题")
            report = result["contribution_report"]
            self.assertIsNone(report["task_success_rate"])
            self.assertEqual(report["utility"]["quality_source"], "unscored")
            self.assertTrue(all(item["status"] == "skipped" for item in report["ablation_results"]))

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

    def test_critical_path_is_independent_of_role_list_order(self):
        from multiagent.models import AgentResult, AgentRole, ArchitecturePlan

        plan = ArchitecturePlan("ordered", [], [
            AgentRole("b", "B", "", "", ["a"]),
            AgentRole("a", "A", "", ""),
        ])
        metrics = aggregate_metrics(plan, [
            AgentResult("a", "A", "a", metrics={"latency_seconds": 1.0}),
            AgentResult("b", "B", "b", ["a"], metrics={"latency_seconds": 2.0}),
        ])
        self.assertEqual(metrics["critical_path_latency"], 3.0)


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

    def test_non_streaming_fallback_preserves_tool_allowlist(self):
        from llm.adapters import AdapterResponse

        with tempfile.TemporaryDirectory() as d:
            seen = []

            class FallbackAdapter:
                def stream(self, **kwargs):
                    raise TypeError("stream unavailable")

                def complete(self, **kwargs):
                    seen.extend(item["function"]["name"] for item in kwargs["tools"])
                    return AdapterResponse(content="fallback answer")

            answer = run_agent(
                client=object(),
                model_name="fake",
                messages=[{"role": "user", "content": "hi"}],
                logger=EventLogger(Path(d) / "run"),
                data_dir=Path(d),
                workspace_root=Path("."),
                max_turns=1,
                adapter=FallbackAdapter(),
                allowed_tool_names={"web_search"},
            )
            self.assertEqual(answer, "fallback answer")
            self.assertEqual(seen, ["web_search"])

    def test_fallback_does_not_reopen_tools_after_tool_budget(self):
        from llm.adapters import AdapterResponse

        with tempfile.TemporaryDirectory() as d:
            seen = []

            class FallbackAdapter:
                def stream(self, **kwargs):
                    raise TypeError("stream unavailable")

                def complete(self, **kwargs):
                    seen.append(kwargs["tools"])
                    return AdapterResponse(content="budget exhausted")

            answer = run_agent(
                client=object(),
                model_name="fake",
                messages=[{"role": "user", "content": "hi"}],
                logger=EventLogger(Path(d) / "run"),
                data_dir=Path(d),
                workspace_root=Path("."),
                max_turns=1,
                adapter=FallbackAdapter(),
                allowed_tool_names={"web_search"},
                max_tool_calls=0,
            )
            self.assertEqual(answer, "budget exhausted")
            self.assertEqual(seen, [[]])


if __name__ == "__main__":
    unittest.main()
