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
        self._reap_orphan_runs()
        self._client = build_client(
            settings.provider,
            model_name=settings.model_name,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
        )
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._cancel_flags: dict[str, threading.Event] = {}

    @property
    def client(self) -> Any:
        return self._client

    def _reap_orphan_runs(self) -> None:
        """进程启动时收尾：上一个进程遗留的未终态 run（线程已随进程消失）标记为 cancelled，
        避免前端对孤儿 run 无限轮询、取消接口 404。"""
        try:
            for run in self.store.list_recent(200):
                if run.get("status") in {"queued", "running", "cancelling"}:
                    self.store.update(run["run_id"], "cancelled")
        except Exception:
            pass  # 收尾失败不阻塞服务启动

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
        with self._lock:
            self._cancel_flags[run_id] = threading.Event()
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

    def cancel(self, run_id: str) -> bool:
        """请求停止一个运行中的任务（立即生效，幂等）。返回是否受理。"""
        with self._lock:
            event = self._cancel_flags.get(run_id)
        if event is not None:
            event.set()
            # 立即落盘 cancelled，前端无需等待 cancelling→cancelled 转换
            run = self.store.get(run_id)
            if run and run.get("status") in {"queued", "running", "cancelling"}:
                self.store.update(run_id, "cancelled")
            return True
        # 内存无取消标记的两种情况，只要 run 存在都幂等受理（不 404）：
        # 1) 孤儿 run：线程已随上个进程消失，磁盘状态卡在非终态 → 落盘 cancelled 收敛
        # 2) 已结束的 run：标记被 finally 清理，点停止晚于任务完成 → 本来就已停止
        run = self.store.get(run_id)
        if run is None:
            return False  # 只有真正不存在的 run 才 404
        if run.get("status") in {"queued", "running", "cancelling"}:
            self.store.update(run_id, "cancelled")
        return True

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
        with self._lock:
            cancel_event = self._cancel_flags.get(run_id)
        should_stop = (lambda: cancel_event.is_set()) if cancel_event is not None else None
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
                        should_stop=should_stop,
                    )
                    return {"answer": answer, "metrics": role_metrics}

                multi_result = MultiAgentOrchestrator(
                    runner=run_role,
                    data_dir=self.settings.data_dir,
                    logger=logger,
                    max_parallelism=self.settings.max_parallel_agents,
                    should_stop=should_stop,
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
                    should_stop=should_stop,
                )
            # Persist both sides of the exchange to conversation history.
            was_cancelled = should_stop is not None and should_stop()
            self.store.append_message(conversation_id, "user", task)
            if answer or not was_cancelled:
                self.store.append_message(conversation_id, "assistant", answer)
            # 状态判定：取消 > 未完成（轮次用尽等）> 完成
            if was_cancelled:
                run_status = "cancelled"
            elif not answer:
                run_status = "failed"
            else:
                run_status = "completed"
            result: dict[str, Any] = {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "status": run_status,
                "answer": answer,
                "provider": self.client.provider,
                "model": self.client.model_name,
                "mode": mode,
            }
            if run_status == "failed":
                result["error"] = "达到最大执行轮次，任务未完成（可尝试拆分任务或提高 METAMORPH_MAX_STEPS）"
            if multi_result is None:
                result["metrics"] = run_metrics
            if multi_result is not None:
                result.update({k: v for k, v in multi_result.items() if k != "answer"})
            logger.emit("run.evaluated", result=result)
            logger.write_json("result.json", result)
            # 若用户已取消（cancel() 已落盘 cancelled），不允许 completed/failed 覆盖
            current = self.store.get(run_id)
            if current and current.get("status") == "cancelled":
                result["status"] = "cancelled"
                result.pop("error", None)
            self.store.update(run_id, result["status"], result)
        except Exception as exc:
            logger.emit("run.error", error=str(exc))
            current = self.store.get(run_id)
            if current and current.get("status") == "cancelled":
                result = {"run_id": run_id, "conversation_id": conversation_id, "status": "cancelled"}
            else:
                result = {"run_id": run_id, "conversation_id": conversation_id, "status": "failed", "error": str(exc)}
            self.store.update(run_id, result["status"], result)
        finally:
            with self._lock:
                self._cancel_flags.pop(run_id, None)

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
