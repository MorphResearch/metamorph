import json
import tempfile
import unittest
from pathlib import Path

from metamorph.events import EventLogger
from metamorph.config import Settings
from metamorph.model import PROVIDER_DEFAULTS, build_model
from metamorph.model import MockModelAdapter
from metamorph.runtime import AgentRuntime
from metamorph.sandbox import WorkspaceSandbox


class SandboxTests(unittest.TestCase):
    def test_path_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = WorkspaceSandbox(Path(directory))
            result = sandbox.read_file("../secret.txt")
            self.assertFalse(result.ok)
            self.assertIn("escapes", result.error)

    def test_write_is_denied_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = WorkspaceSandbox(Path(directory))
            result = sandbox.write_file("note.txt", "hello")
            self.assertFalse(result.ok)
            self.assertIn("approval", result.error)


class RuntimeTests(unittest.TestCase):
    def test_mock_runtime_records_evidence_and_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            result = AgentRuntime(MockModelAdapter()).run(
                task="inspect this workspace",
                workspace=root / "workspace",
                logger=EventLogger(run_dir),
                run_id="test-run",
            )
            self.assertEqual(result["status"], "passed")
            self.assertTrue((run_dir / "events.jsonl").exists())
            self.assertTrue((run_dir / "result.json").exists())
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
            self.assertEqual(events[0]["type"], "run.started")
            self.assertEqual(events[-1]["type"], "run.evaluated")

    def test_settings_use_a_dedicated_workspace_root(self):
        settings = Settings.from_environment(Path("/tmp/metamorph-test-data"))
        self.assertEqual(settings.workspace_root, Path("workspace"))

    def test_provider_defaults_cover_requested_families(self):
        for provider in ("openai", "deepseek", "minimax", "claude", "glm"):
            self.assertIn("model", PROVIDER_DEFAULTS[provider])
            self.assertIn("api_key_env", PROVIDER_DEFAULTS[provider])

    def test_mock_provider_factory_is_dependency_free(self):
        model = build_model("mock")
        self.assertEqual(model.model_name, "mock-v0")
        self.assertEqual(model.provider, "mock")


if __name__ == "__main__":
    unittest.main()
