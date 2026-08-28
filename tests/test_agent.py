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


class ConfigTests(unittest.TestCase):
    def test_supported_providers(self):
        for provider in ("openai", "deepseek", "minimax", "claude", "glm", "sensenova"):
            self.assertIn(provider, get_supported_providers())
            self.assertIn("model", PROVIDER_DEFAULTS[provider])
            self.assertIn("api_key_env", PROVIDER_DEFAULTS[provider])

    def test_settings_defaults(self):
        settings = Settings(data_dir=Path(".metamorph"))
        self.assertEqual(settings.provider, "sensenova")


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
