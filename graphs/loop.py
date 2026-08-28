"""Core agent loop: agent -> tools -> agent orchestration.

Drives the LLM client through ``max_turns`` iterations, dispatches tool calls,
feeds results back into the conversation, and emits events (``model.decision``,
``reasoning``, ``tool.completed``) to both the ``EventLogger`` and an optional
``emit`` callback for live UI streaming.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from prompts.system_prompt import SYSTEM_PROMPT
from tools import dispatch, tool_schemas
from memory.formatter import format_memories

from .streaming import iter_stream


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
    ctx: dict[str, Path],
) -> str:
    """Execute the agent loop. Returns the final assistant answer."""
    answer = ""
    for turn in range(1, max_turns + 1):
        reasoning_parts: list[str] = []
        assistant_content = ""
        tool_calls: list[dict[str, Any]] = []

        try:
            stream = client.chat.completions.create(
                model=model_name,
                messages=convo,
                tools=tool_schemas(),
                tool_choice="auto",
                stream=True,
                max_tokens=4096,
            )
        except TypeError:
            stream = None

        if stream is not None:
            for chunk in iter_stream(stream):
                if chunk.reasoning:
                    reasoning_parts.append(chunk.reasoning)
                    logger.emit("reasoning", text=chunk.reasoning)
                    if emit:
                        emit("reasoning", {"text": chunk.reasoning})
                if chunk.content:
                    assistant_content += chunk.content
                if chunk.tool_call is not None:
                    tool_calls.append(chunk.tool_call)
        else:
            resp = client.chat.completions.create(
                model=model_name,
                messages=convo,
                tools=tool_schemas(),
                tool_choice="auto",
                max_tokens=4096,
            )
            msg = resp.choices[0].message
            assistant_content = msg.content or ""
            for tc in (msg.tool_calls or []):
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })

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
            result = dispatch(name, arguments, ctx)
            logger.emit(
                "tool.completed",
                step=turn,
                tool=name,
                arguments=arguments,
                result={"ok": True, "output": result},
            )
            convo.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    return answer
