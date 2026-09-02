"""Core agent loop: agent -> tools -> agent orchestration.

Drives the LLM client through ``max_turns`` iterations, dispatches tool calls,
feeds results back into the conversation, and emits events (``model.decision``,
``reasoning``, ``tool.completed``) to both the ``EventLogger`` and an optional
``emit`` callback for live UI streaming.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from prompts.system_prompt import SYSTEM_PROMPT
from tools import dispatch, tool_schemas
from memory.formatter import format_memories

from llm.adapters import OpenAICompatibleAdapter


def _build_conversation(
    messages: list[dict[str, str]],
    data_dir: Path,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Prepend the system prompt (with memory injection) to user messages.

    ``history`` is a list of prior ``role``/``content`` messages from the
    same conversation.  They are spliced in *before* the newest user turn so
    the model sees the full conversation context.
    """
    system_content = SYSTEM_PROMPT
    memories = format_memories(data_dir)
    if memories:
        system_content += "\n\n# 已知的用户长期记忆\n" + memories
    convo: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    if history:
        convo.extend(list(history))
    convo.extend(list(messages))
    return convo


def run_loop(
    *,
    client: Any,
    model_name: str,
    convo: list[dict[str, Any]],
    logger: Any,
    max_turns: int,
    emit: Callable[[str, dict[str, Any]], None] | None,
    ctx: dict[str, Any],
    adapter: Any | None = None,
    metrics: dict[str, Any] | None = None,
    allowed_tool_names: set[str] | None = None,
    max_tool_calls: int | None = None,
    max_total_tokens: int | None = None,
    max_latency_seconds: float | None = None,
) -> str:
    """Execute the agent loop. Returns the final assistant answer."""
    adapter = adapter or OpenAICompatibleAdapter(client)
    run_metrics = metrics if metrics is not None else {}
    started = time.perf_counter()
    run_metrics.update({
        "llm_calls": 0,
        "tool_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "success": False,
    })
    answer = ""
    try:
        for turn in range(1, max_turns + 1):
            budget_reasons: list[str] = []
            if max_total_tokens is not None and run_metrics["total_tokens"] >= max_total_tokens:
                budget_reasons.append("token budget exhausted")
            if max_latency_seconds is not None and time.perf_counter() - started >= max_latency_seconds:
                budget_reasons.append("latency budget exhausted")
            if budget_reasons:
                logger.emit("budget.stopped", step=turn, reasons=budget_reasons)
                break
            reasoning_parts: list[str] = []
            assistant_content = ""
            tool_calls: list[dict[str, Any]] = []
            usage: dict[str, int] = {}
            remaining_tool_calls = (
                None
                if max_tool_calls is None
                else max(0, max_tool_calls - run_metrics["tool_calls"])
            )

            try:
                available_tools = [] if remaining_tool_calls == 0 else tool_schemas(allowed_tool_names)
                for chunk in adapter.stream(model_name=model_name, messages=convo, tools=available_tools):
                    if chunk.reasoning:
                        reasoning_parts.append(chunk.reasoning)
                        logger.emit("reasoning", text=chunk.reasoning)
                        if emit:
                            emit("reasoning", {"text": chunk.reasoning})
                    if chunk.content:
                        assistant_content += chunk.content
                        # 回答增量实时落盘，前端轮询即可获得打字机流式效果
                        logger.emit("answer.delta", step=turn, text=chunk.content)
                        if emit:
                            emit("answer.delta", {"text": chunk.content, "step": turn})
                    if chunk.tool_call is not None:
                        tool_calls.append(chunk.tool_call)
                    if chunk.usage:
                        usage.update(chunk.usage)
            except (TypeError, NotImplementedError):
                # Preserve stage-level tool isolation on non-streaming fallback.
                response = adapter.complete(
                    model_name=model_name,
                    messages=convo,
                    tools=available_tools,
                )
                assistant_content = response.content
                reasoning_parts.append(response.reasoning)
                tool_calls.extend(response.tool_calls)
                usage.update(response.usage)
                # 非流式回退路径：整段回答作为一次增量下发，保持前端渲染一致
                if assistant_content:
                    logger.emit("answer.delta", step=turn, text=assistant_content)
                    if emit:
                        emit("answer.delta", {"text": assistant_content, "step": turn})

            if remaining_tool_calls is not None and len(tool_calls) > remaining_tool_calls:
                logger.emit(
                    "tool.budget_truncated",
                    step=turn,
                    requested=len(tool_calls),
                    permitted=remaining_tool_calls,
                )
                tool_calls = tool_calls[:remaining_tool_calls]

            run_metrics["llm_calls"] += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                run_metrics[key] += usage.get(key, 0)

            reasoning = "".join(reasoning_parts)
            logger.emit(
                "model.decision",
                step=turn,
                action="tool_call" if tool_calls else "finish",
                summary=assistant_content[:200] or "(调用工具)",
                reasoning=reasoning,
            )
            if emit and reasoning:
                emit("reasoning", {"text": "", "done": True})

            if not tool_calls:
                answer = assistant_content
                break

            run_metrics["tool_calls"] += len(tool_calls)
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            }
            convo.append(assistant_msg)

            for tc in tool_calls:
                name = tc["name"]
                try:
                    arguments = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = dispatch(name, arguments, ctx, allowed_tool_names)
                result = __import__("tools.utils", fromlist=["process_tool_result"]).process_tool_result(result)
                ok = not result.startswith(("参数校验失败：", "工具执行失败：", "工具不存在：", "工具执行被拒绝："))
                logger.emit(
                    "tool.completed",
                    step=turn,
                    tool=name,
                    arguments=arguments,
                    result={"ok": ok, "output": result} if ok else {"ok": False, "error": result},
                )
                convo.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
        run_metrics["success"] = bool(answer)
        return answer
    finally:
        run_metrics["total_tokens"] = run_metrics["prompt_tokens"] + run_metrics["completion_tokens"] or run_metrics["total_tokens"]
        run_metrics["latency_seconds"] = round(time.perf_counter() - started, 6)
