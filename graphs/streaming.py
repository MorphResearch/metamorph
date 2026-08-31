"""Streaming chunk parser: extract content, reasoning, and tool calls from a
streaming LLM response.

Mirrors scilink-agent's ``llm/reasoning_patch.py`` approach: reads
``reasoning_content`` directly from streamed deltas without any SDK monkey-patch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator


@dataclass
class ParsedChunk:
    """Fields extracted from a single streamed delta."""
    content: str = ""
    reasoning: str = ""
    tool_call: dict[str, Any] | None = None
    usage: dict[str, int] | None = None


def iter_stream(
    stream: Generator[Any, None, None],
) -> Generator[ParsedChunk, None, None]:
    """Yield ``ParsedChunk`` instances from a raw streaming response.

    Accumulates partial ``tool_calls`` across chunks (indexed by ``delta.index``)
    so that the full tool-call JSON is available when the stream ends.
    """
    tool_calls: list[dict[str, Any]] = []
    for chunk in stream:
        usage = _parse_usage(getattr(chunk, "usage", None))
        if not chunk.choices:
            if usage:
                yield ParsedChunk(usage=usage)
            continue
        delta = chunk.choices[0].delta

        piece_reasoning = getattr(delta, "reasoning_content", None) or ""
        piece_content = getattr(delta, "content", None) or ""
        if piece_reasoning or piece_content:
            yield ParsedChunk(content=piece_content, reasoning=piece_reasoning, usage=usage or None)
        elif usage:
            yield ParsedChunk(usage=usage)

        raw_tool_calls = getattr(delta, "tool_calls", None)
        if raw_tool_calls:
            for tc in raw_tool_calls:
                idx = tc.index
                while len(tool_calls) <= idx:
                    tool_calls.append({"id": "", "name": "", "arguments": ""})
                if tc.id:
                    tool_calls[idx]["id"] = tc.id
                if tc.function and tc.function.name:
                    tool_calls[idx]["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    tool_calls[idx]["arguments"] += tc.function.arguments

    # Yield the fully accumulated tool calls at end of stream.
    for tc in tool_calls:
        yield ParsedChunk(tool_call=tc)


def _parse_usage(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    result: dict[str, int] = {}
    aliases = {
        "prompt_tokens": "prompt_tokens",
        "input_tokens": "prompt_tokens",
        "completion_tokens": "completion_tokens",
        "output_tokens": "completion_tokens",
        "total_tokens": "total_tokens",
    }
    for source, target in aliases.items():
        raw = value.get(source) if isinstance(value, dict) else getattr(value, source, None)
        if raw is not None:
            try:
                result[target] = int(raw)
            except (TypeError, ValueError):
                pass
    if "total_tokens" not in result and {"prompt_tokens", "completion_tokens"} <= result.keys():
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    return result


def non_streaming_call(
    client: Any,
    model_name: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Non-streaming fallback: invoke once, parse ``content`` + ``tool_calls``."""
    resp = client.chat.completions.create(
        model=model_name,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=4096,
    )
    msg = resp.choices[0].message
    tool_calls = []
    for tc in (msg.tool_calls or []):
        tool_calls.append({
            "id": tc.id,
            "name": tc.function.name,
            "arguments": tc.function.arguments,
        })
    return msg.content or "", tool_calls
