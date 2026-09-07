"""Provider adapters with one normalized interface for the agent loop.

The runtime only needs a small subset of provider behavior: text, reasoning,
tool calls, and token usage.  Keeping that protocol here prevents provider
specific SDK details from leaking into ``graphs.loop``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterator

from .thinking import thinking_params_for


@dataclass
class AdapterChunk:
    content: str = ""
    reasoning: str = ""
    tool_call: dict[str, Any] | None = None
    usage: dict[str, int] | None = None


@dataclass
class AdapterResponse:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


def _usage(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    result: dict[str, int] = {}
    for source, target in (
        ("prompt_tokens", "prompt_tokens"),
        ("input_tokens", "prompt_tokens"),
        ("completion_tokens", "completion_tokens"),
        ("output_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        raw = value.get(source) if isinstance(value, dict) else getattr(value, source, None)
        if raw is not None:
            try:
                result[target] = int(raw)
            except (TypeError, ValueError):
                continue
    if "total_tokens" not in result and {"prompt_tokens", "completion_tokens"} <= result.keys():
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    return result


def _tool_call_dict(tool_call: Any) -> dict[str, Any]:
    function = getattr(tool_call, "function", None)
    return {
        "id": getattr(tool_call, "id", ""),
        "name": getattr(function, "name", "") or "",
        "arguments": getattr(function, "arguments", "") or "{}",
    }


class ProviderAdapter:
    """Minimal normalized protocol consumed by the agent executor."""

    def stream(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[AdapterChunk]:
        raise NotImplementedError

    def complete(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AdapterResponse:
        raise NotImplementedError

    def complete_configured(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        generation_options: dict[str, Any],
    ) -> AdapterResponse:
        """Optional experiment path with frozen decoding parameters."""

        del generation_options
        return self.complete(model_name=model_name, messages=messages, tools=tools)


class OpenAICompatibleAdapter(ProviderAdapter):
    """Adapter for OpenAI and OpenAI-compatible providers."""

    def __init__(self, client: Any, provider: str = "openai") -> None:
        self.client = client
        self.provider = provider

    def _kwargs(
        self,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        stream: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max(1, int(os.getenv("METAMORPH_MAX_OUTPUT_TOKENS", "4096"))),
            "stream": stream,
        }
        # Several OpenAI-compatible providers reject an explicitly empty tools
        # array. Router and tool-selection phases are intentionally tool-free.
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        kwargs.update(thinking_params_for(model_name))
        # Usage is emitted in the final chunk by modern OpenAI-compatible APIs.
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        return kwargs

    def stream(self, *, model_name: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Iterator[AdapterChunk]:
        raw_stream = self.client.chat.completions.create(**self._kwargs(model_name, messages, tools, True))
        # Import lazily to avoid a package import cycle during startup.
        from graphs.streaming import iter_stream

        for chunk in iter_stream(raw_stream):
            yield AdapterChunk(
                content=chunk.content,
                reasoning=chunk.reasoning,
                tool_call=chunk.tool_call,
                usage=chunk.usage,
            )

    def complete(self, *, model_name: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AdapterResponse:
        response = self.client.chat.completions.create(**self._kwargs(model_name, messages, tools, False))
        message = response.choices[0].message
        return AdapterResponse(
            content=message.content or "",
            reasoning=getattr(message, "reasoning_content", "") or "",
            tool_calls=[_tool_call_dict(tc) for tc in (getattr(message, "tool_calls", None) or [])],
            usage=_usage(getattr(response, "usage", None)),
        )

    def complete_configured(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        generation_options: dict[str, Any],
    ) -> AdapterResponse:
        kwargs = self._kwargs(model_name, messages, tools, False)
        request_client = self.client
        timeout = generation_options.get("timeout")
        # The OpenAI SDK applies timeout/retry settings reliably through an
        # options-bound client.  Passing only a method kwarg was insufficient
        # with the installed OpenAI-compatible transport when a response body
        # stalled.  Keep the kwarg fallback for lightweight test clients.
        if hasattr(self.client, "with_options"):
            options: dict[str, Any] = {"max_retries": 0}
            if timeout is not None:
                options["timeout"] = timeout
            request_client = self.client.with_options(**options)
        elif timeout is not None:
            kwargs["timeout"] = timeout
        for key in ("temperature", "seed", "max_tokens", "response_format"):
            if generation_options.get(key) is not None:
                kwargs[key] = generation_options[key]
        response = request_client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        return AdapterResponse(
            content=message.content or "",
            reasoning=getattr(message, "reasoning_content", "") or "",
            tool_calls=[_tool_call_dict(tc) for tc in (getattr(message, "tool_calls", None) or [])],
            usage=_usage(getattr(response, "usage", None)),
        )


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for tool in tools:
        function = tool.get("function", {})
        result.append({
            "name": function.get("name", ""),
            "description": function.get("description", ""),
            "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            system_parts.append(str(message.get("content", "")))
        elif role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id", ""),
                    "content": str(message.get("content", "")),
                }],
            })
        elif role == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": str(message["content"])})
            for call in message["tool_calls"]:
                function = call.get("function", {})
                try:
                    arguments = json.loads(function.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}
                blocks.append({
                    "type": "tool_use",
                    "id": call.get("id", ""),
                    "name": function.get("name", ""),
                    "input": arguments,
                })
            converted.append({"role": "assistant", "content": blocks})
        else:
            converted.append({"role": "assistant" if role == "assistant" else "user", "content": str(message.get("content", ""))})
    return "\n\n".join(system_parts), converted


class AnthropicAdapter(ProviderAdapter):
    """Normalize Anthropic's Messages API into the agent loop protocol."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _create(self, model_name: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        system, converted = _anthropic_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "max_tokens": max(1, int(os.getenv("METAMORPH_MAX_OUTPUT_TOKENS", "4096"))),
            "messages": converted,
        }
        if tools:
            kwargs["tools"] = _anthropic_tools(tools)
        if system:
            kwargs["system"] = system
        return self.client.messages.create(**kwargs)

    def complete(self, *, model_name: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AdapterResponse:
        response = self._create(model_name, messages, tools)
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        reasoning_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                content_parts.append(getattr(block, "text", "") or "")
            elif block_type in {"thinking", "redacted_thinking"}:
                reasoning_parts.append(getattr(block, "thinking", "") or "")
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "arguments": json.dumps(getattr(block, "input", {}) or {}, ensure_ascii=False),
                })
        return AdapterResponse(
            content="".join(content_parts),
            reasoning="".join(reasoning_parts),
            tool_calls=tool_calls,
            usage=_usage(getattr(response, "usage", None)),
        )

    def complete_configured(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        generation_options: dict[str, Any],
    ) -> AdapterResponse:
        system, converted = _anthropic_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "max_tokens": int(generation_options.get("max_tokens") or os.getenv("METAMORPH_MAX_OUTPUT_TOKENS", "4096")),
            "messages": converted,
        }
        if tools:
            kwargs["tools"] = _anthropic_tools(tools)
        if generation_options.get("temperature") is not None:
            kwargs["temperature"] = generation_options["temperature"]
        if system:
            kwargs["system"] = system
        response = self.client.messages.create(**kwargs)
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        reasoning_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                content_parts.append(getattr(block, "text", "") or "")
            elif block_type in {"thinking", "redacted_thinking"}:
                reasoning_parts.append(getattr(block, "thinking", "") or "")
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "arguments": json.dumps(getattr(block, "input", {}) or {}, ensure_ascii=False),
                })
        return AdapterResponse(
            content="".join(content_parts),
            reasoning="".join(reasoning_parts),
            tool_calls=tool_calls,
            usage=_usage(getattr(response, "usage", None)),
        )

    def stream(self, *, model_name: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Iterator[AdapterChunk]:
        # The protocol is uniform even when a provider SDK has no compatible
        # stream implementation. This can be upgraded to native event parsing
        # without changing the graph layer.
        response = self.complete(model_name=model_name, messages=messages, tools=tools)
        if response.reasoning or response.content:
            yield AdapterChunk(content=response.content, reasoning=response.reasoning, usage=response.usage)
        for tool_call in response.tool_calls:
            yield AdapterChunk(tool_call=tool_call)


def build_adapter(provider: str, client: Any) -> ProviderAdapter:
    if provider == "claude":
        return AnthropicAdapter(client)
    return OpenAICompatibleAdapter(client, provider=provider)
