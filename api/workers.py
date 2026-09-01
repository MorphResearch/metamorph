"""Task worker management: daemon threads that execute agent runs.

Analogous to scilink-agent's scheduler design — each submitted task spawns
a daemon thread that runs the agent loop to completion. This module tracks
active workers and ensures graceful shutdown behaviour.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from config import Settings
from graphs.agent import run_agent as _run_agent
from llm.client import build_client
from state.events import EventLogger
from state.store import RunStore
from multiagent.orchestrator import MultiAgentOrchestrator
from multiagent.models import BudgetPolicy


class TaskWorker:
    """Manages the lifecycle of submitted agent runs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = RunStore(settings.data_dir)
        self._client = build_client(
            settings.provider,
            model_name=settings.model_name,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
        )
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()

    @property
    def client(self) -> Any:
        return self._client

    def submit(
        self,
        task: str,
        workspace: Path,
        conversation_id: str | None = None,
        mode: str | None = None,
    ) -> tuple[str, str]:
        """Register a new run and start a background worker thread.

        If ``conversation_id`` is provided, prior messages from that
        conversation are merged into the prompt so the model has full
        dialogue context.  Returns ``(run_id, conversation_id)``.
        """
        resolved = workspace.expanduser().resolve()
        selected_mode = mode or self.settings.mode
        if selected_mode not in {"single", "multiagent"}:
            raise ValueError("mode must be single or multiagent")
        run_id, conv_id = self.store.create(task, resolved, conversation_id=conversation_id)
        history = self.store.get_conversation(conv_id) if conv_id else []
        thread = threading.Thread(
            target=self._run,
            args=(run_id, conv_id, task, resolved, history, selected_mode),
            daemon=True,
            name=f"worker-{run_id}",
        )
        with self._lock:
            self._workers.append(thread)
        thread.start()
        return run_id, conv_id

    def _run(
        self,
        run_id: str,
        conversation_id: str,
        task: str,
        workspace: Path,
        history: list[dict[str, str]],
        mode: str,
    ) -> None:
        run_dir = self.store.runs_dir / run_id
        logger = EventLogger(run_dir)
        self.store.update(run_id, "running")
        try:
            if mode == "multiagent":
                def run_role(prompt: str, agent_id: str) -> dict[str, Any]:
                    role_logger = EventLogger(run_dir / "agents" / agent_id)
                    role_metrics: dict[str, Any] = {}
                    answer = _run_agent(
                        client=self.client.client,
                        model_name=self.client.model_name,
                        messages=[{"role": "user", "content": prompt}],
                        logger=role_logger,
                        data_dir=self.settings.data_dir,
                        workspace_root=workspace,
                        max_turns=self.settings.max_steps,
                        adapter=self.client.adapter,
                        metrics=role_metrics,
                        max_read_bytes=self.settings.max_read_bytes,
                        max_tool_calls=self.settings.max_tool_calls,
                        max_total_tokens=self.settings.max_total_tokens,
                        max_latency_seconds=self.settings.max_latency_seconds,
                        allow_write=self.settings.allow_write,
                    )
                    return {"answer": answer, "metrics": role_metrics}

                multi_result = MultiAgentOrchestrator(
                    runner=run_role,
                    data_dir=self.settings.data_dir,
                    logger=logger,
                    max_parallelism=self.settings.max_parallel_agents,
                    budget_policy=BudgetPolicy(
                        max_total_tokens=self.settings.max_total_tokens,
                        max_latency_seconds=self.settings.max_latency_seconds,
                        max_tool_calls=self.settings.max_tool_calls,
                        max_causal_audits=self.settings.max_causal_audits,
                        allow_write=self.settings.allow_write,
                    ),
                ).run(task, source_run=run_id, history=history)
                answer = multi_result["answer"]
            else:
                multi_result = None
                run_metrics: dict[str, Any] = {}
                answer = _run_agent(
                    client=self.client.client,
                    model_name=self.client.model_name,
                    messages=[{"role": "user", "content": task}],
                    logger=logger,
                    data_dir=self.settings.data_dir,
                    workspace_root=workspace,
                    max_turns=self.settings.max_steps,
                    history=history,
                    adapter=self.client.adapter,
                    metrics=run_metrics,
                    max_read_bytes=self.settings.max_read_bytes,
                    max_total_tokens=self.settings.max_total_tokens,
                    max_latency_seconds=self.settings.max_latency_seconds,
                    max_tool_calls=self.settings.max_tool_calls,
                    allow_write=self.settings.allow_write,
                )
            # Persist both sides of the exchange to conversation history.
            self.store.append_message(conversation_id, "user", task)
            self.store.append_message(conversation_id, "assistant", answer)
            result: dict[str, Any] = {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "status": "completed",
                "answer": answer,
                "provider": self.client.provider,
                "model": self.client.model_name,
                "mode": mode,
            }
            if multi_result is None:
                result["metrics"] = run_metrics
            if multi_result is not None:
                result.update({k: v for k, v in multi_result.items() if k != "answer"})
            logger.emit("run.evaluated", result=result)
            logger.write_json("result.json", result)
            self.store.update(run_id, result["status"], result)
        except Exception as exc:
            logger.emit("run.error", error=str(exc))
            result = {"run_id": run_id, "conversation_id": conversation_id, "status": "failed", "error": str(exc)}
            self.store.update(run_id, "failed", result)

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get(run_id)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_recent(limit)

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.get_conversations(limit)

    def conversation(self, conversation_id: str) -> dict[str, Any] | None:
        runs = self.store.list_conversation_runs(conversation_id)
        if not runs:
            return None
        return {
            "conversation_id": conversation_id,
            "messages": self.store.get_conversation(conversation_id),
            "runs": runs,
        }

    def events(self, run_id: str) -> list[dict[str, Any]]:
        logger = EventLogger(self.store.runs_dir / run_id)
        return logger.read_all()
