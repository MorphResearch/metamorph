"""Thin, tool-only bridge to CL-Bench Database Exploration.

The adapter deliberately exposes the upstream task's QUERY/ANSWER loop rather
than SQLite files, question JSON, reference SQL, or evaluator internals.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .records import RunRecords


@dataclass(frozen=True)
class PublicTaskView:
    task_id: str
    task_index: int
    prompt: str
    query_budget: int


class DatabaseExplorationAdapter:
    """Run one public task instance through its native QUERY/ANSWER evaluator."""

    def __init__(
        self,
        *,
        upstream_root: Path,
        db_path: Path,
        questions_path: Path,
        records: RunRecords,
        seed: int = 42,
        max_queries_per_question: int = 15,
        task_index: int = 0,
        allow_no_model_import_shim: bool = True,
    ) -> None:
        self.upstream_root = Path(upstream_root).resolve()
        self.db_path = Path(db_path).resolve()
        self.questions_path = Path(questions_path).resolve()
        self.records = records
        self.seed = seed
        self.max_queries_per_question = max_queries_per_question
        self.task_index = task_index
        self.allow_no_model_import_shim = allow_no_model_import_shim
        self._task: Any | None = None
        self._response_type: Any | None = None
        self._action_type: Any | None = None
        self._completed = False

    def _load_upstream_types(self) -> tuple[Any, Any, Any]:
        if self.allow_no_model_import_shim:
            self._install_no_model_usage_import_shim()
        else:
            self.assert_real_litellm_available()
        root = str(self.upstream_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        from src.interface import Response  # type: ignore[import-not-found]
        from src.tasks.database_exploration.task import DatabaseAction, DatabaseExploration  # type: ignore[import-not-found]
        return DatabaseExploration, DatabaseAction, Response

    @staticmethod
    def _install_no_model_usage_import_shim() -> None:
        """Allow task-only imports without pulling the provider client stack.

        ``src.interface`` imports ``UsageEvent`` from upstream ``src.usage``;
        the latter imports LiteLLM eagerly even though the Database Exploration
        task and its native evaluator do not call any LiteLLM function.  The
        shim is only for this no-model, task-only bridge.  A live provider run
        must install and use the upstream dependency, never this shim.
        """
        if "litellm" not in sys.modules and importlib.util.find_spec("litellm") is None:
            shim = types.ModuleType("litellm")
            shim.model_cost = {}
            sys.modules.setdefault("litellm", shim)

    @staticmethod
    def assert_real_litellm_available() -> str:
        """Reject the no-model shim before a provider-capable run begins."""
        module = importlib.import_module("litellm")
        if getattr(module, "__spec__", None) is None or not getattr(module, "__file__", None):
            raise RuntimeError("live public calibration forbids the no-model LiteLLM import shim")
        try:
            from importlib.metadata import version
            return version("litellm")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("live public calibration requires an installed LiteLLM distribution") from exc

    @classmethod
    def setup_database_exploration(cls, upstream_root: Path, records: RunRecords) -> None:
        """Run the upstream database-only setup with no provider invocation."""
        bridge = cls(
            upstream_root=upstream_root,
            db_path=Path(upstream_root) / "data/database_exploration/products.db",
            questions_path=Path(upstream_root) / "data/database_exploration/questions.json",
            records=records,
        )
        task_type, _, _ = bridge._load_upstream_types()
        task_type.setup()

    def reset(self) -> PublicTaskView:
        task_type, action_type, response_type = self._load_upstream_types()
        if self.task_index < 0:
            raise ValueError("task_index must be non-negative")
        self._task = task_type(
            db_path=str(self.db_path), questions_path=str(self.questions_path), num_questions=self.task_index + 1,
            max_queries_per_question=self.max_queries_per_question, seed=self.seed,
        )
        self._task.build_canonical_run_state()
        self._task._current_question_idx = self.task_index
        self._action_type, self._response_type, self._completed = action_type, response_type, False
        query = self._task.get_query()
        view = PublicTaskView(
            task_id=str(query.instance_id), task_index=int(query.instance_index or 0), prompt=query.prompt,
            query_budget=int((query.metadata or {}).get("query_budget", self.max_queries_per_question)),
        )
        self.records.emit("public_env.task_loaded", task_id=view.task_id, task_index=view.task_index,
                          query_budget=view.query_budget, upstream="continual-learning-bench/database_exploration")
        return view

    def query_sql(self, sql: str) -> str:
        return self._dispatch("QUERY", sql)

    def submit_answer(self, answer: str) -> str:
        return self._dispatch("ANSWER", answer)

    @property
    def completed(self) -> bool:
        """Whether the native task has already completed this instance."""
        return self._completed

    def _dispatch(self, action: str, content: str) -> str:
        if self._task is None or self._action_type is None or self._response_type is None:
            raise RuntimeError("reset must be called before dispatch")
        if self._completed:
            raise RuntimeError("the public task instance is already complete")
        step = self._task.step(self._response_type(action=self._action_type(action=action, content=content)))
        observation = step.observation
        self._completed = bool(step.done)
        self.records.emit(
            "public_env.action", action=action, content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            sql=content if action == "QUERY" else None, instance_complete=observation.instance_complete,
            done=step.done, native_reward=step.instance_outcome.reward if step.instance_outcome else None,
        )
        # Upstream terminal ANSWER feedback contains the ground-truth answer
        # (and, on failure, reference SQL).  The task is complete at this
        # point, so retaining it offers no tool-loop benefit and would expose
        # evaluator material to a possible next model turn or transcript.
        # QUERY feedback, including actual SQL errors, remains unmodified.
        if action == "ANSWER":
            return "Task instance completed; native evaluation recorded."
        return observation.content

    def evaluate_native(self) -> Any:
        if self._task is None:
            raise RuntimeError("reset must be called before evaluation")
        result = self._task.evaluate()
        metrics = result.metrics
        # ``question_history`` has the hidden reference answer.  Preserve the
        # native aggregate outcome while keeping evaluator material outside
        # generic research events and agent-visible artifacts.
        summary = {
            key: metrics[key]
            for key in (
                "accuracy", "correct", "total_questions", "total_queries",
                "avg_queries_per_question", "cumulative_regret",
                "normalized_regret", "score",
            )
            if key in metrics
        }
        self.records.emit("public_env.native_evaluator", score=result.score, metrics=summary)
        return result
