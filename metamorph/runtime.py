from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .events import EventLogger
from .evaluator import evaluate_run
from .model import ModelAdapter
from .sandbox import WorkspaceSandbox


class AgentRuntime:
    def __init__(self, model: ModelAdapter, max_steps: int = 12, max_read_bytes: int = 100_000, allow_write: bool = False):
        self.model = model
        self.max_steps = max_steps
        self.max_read_bytes = max_read_bytes
        self.allow_write = allow_write

    def run(self, task: str, workspace: Path, logger: EventLogger, run_id: str) -> dict[str, Any]:
        sandbox = WorkspaceSandbox(workspace, max_read_bytes=self.max_read_bytes, allow_write=self.allow_write)
        started = time.monotonic()
        history: list[dict[str, Any]] = []
        observation = sandbox.list_files().output
        logger.emit(
            "run.started",
            run_id=run_id,
            task=task,
            workspace=str(sandbox.root),
            provider=getattr(self.model, "provider", "unknown"),
            model=self.model.model_name,
        )
        logger.emit("observation.created", step=0, observation=observation)
        answer = ""
        finished = False
        tool_errors = 0

        for step in range(1, self.max_steps + 1):
            try:
                decision = self.model.decide(task, observation, history)
            except Exception as exc:
                tool_errors += 1
                logger.emit("model.error", step=step, error=str(exc))
                break

            logger.emit("model.decision", step=step, action=decision.action, arguments=decision.arguments, summary=decision.summary)
            if decision.action == "finish":
                answer = decision.answer
                finished = True
                break

            result = self._execute(sandbox, decision.action, decision.arguments)
            if not result.ok:
                tool_errors += 1
            tool_event = logger.emit("tool.completed", step=step, tool=decision.action, arguments=decision.arguments, result=result.to_dict())
            observation = result.output if result.ok else f"ERROR: {result.error}"
            history.append({"step": step, "action": decision.action, "summary": decision.summary, "result": result.to_dict()})
            logger.emit("observation.created", step=step, observation=observation)
            if not tool_event:
                break

        evaluation = evaluate_run(
            finished=finished,
            answer=answer,
            tool_errors=tool_errors,
            steps=len(history) + (1 if finished else 0),
            max_steps=self.max_steps,
        )
        result = {
            "run_id": run_id,
            "status": evaluation.status,
            "answer": answer,
            "provider": getattr(self.model, "provider", "unknown"),
            "model": self.model.model_name,
            "steps": len(history) + (1 if finished else 0),
            "tool_errors": tool_errors,
            "duration_seconds": round(time.monotonic() - started, 3),
            "evaluation": evaluation.to_dict(),
        }
        logger.emit("run.evaluated", result=result)
        logger.write_json("result.json", result)
        return result

    @staticmethod
    def _execute(sandbox: WorkspaceSandbox, action: str, arguments: dict[str, Any]):
        if action == "list_files":
            return sandbox.list_files(str(arguments.get("path", ".")))
        if action == "read_file":
            return sandbox.read_file(str(arguments.get("path", "")))
        if action == "write_file":
            return sandbox.write_file(str(arguments.get("path", "")), str(arguments.get("content", "")))
        from .schemas import ToolResult

        return ToolResult(False, error=f"Unsupported runtime action: {action}")
