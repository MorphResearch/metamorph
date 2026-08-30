"""OpenAI-compatible client construction.

The capability/config layer (scilink-agent's "字段提取层" equivalent):
imports ``PROVIDER_DEFAULTS`` from :mod:`llm.providers`, then builds a
ready-to-use client for the requested provider. The agent executor drives it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from types import SimpleNamespace

from .providers import PROVIDER_DEFAULTS, get_supported_providers


@dataclass
class LLMClient:
    """A constructed, ready-to-call client plus its identity metadata."""

    provider: str
    model_name: str
    client: Any
    base_url: str | None = None


def build_client(
    provider: str,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> LLMClient:
    """Build an OpenAI-compatible client for the given provider.

    Raises RuntimeError if the optional ``openai`` dependency is missing or the
    required API key is not set in the environment.
    """
    if provider not in PROVIDER_DEFAULTS:
        raise ValueError(
            "Unknown provider: %r; choose from %s"
            % (provider, ", ".join(get_supported_providers()))
        )

    defaults = PROVIDER_DEFAULTS[provider]
    selected_model = model_name or defaults["model"]
    selected_key_env = api_key_env or defaults["api_key_env"]
    selected_base_url = base_url or defaults.get("base_url")

    if provider == "mock":
        return LLMClient(provider="mock", model_name=selected_model, client=_MockClient())

    try:
        from openai import OpenAI
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "LLM providers require the optional dependency: pip install -e '.[openai]'"
        ) from exc

    api_key = os.getenv(selected_key_env)
    if not api_key:
        raise RuntimeError(f"{provider} mode requires the {selected_key_env} environment variable")

    # Anthropic is handled by its own SDK; everything else is OpenAI-compatible.
    if provider == "claude":
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError("Claude mode requires: pip install -e '.[anthropic]'") from exc
        client = Anthropic(api_key=api_key)
        return LLMClient(provider="claude", model_name=selected_model, client=client)

    client = OpenAI(api_key=api_key, base_url=selected_base_url)
    return LLMClient(
        provider=provider,
        model_name=selected_model,
        client=client,
        base_url=selected_base_url,
    )


class _MockCompletions:
    def create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            raise TypeError("mock client uses the non-streaming fallback")
        messages = kwargs.get("messages") or []
        user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
        task = str(user_messages[-1] if user_messages else "")
        message = SimpleNamespace(content=f"[mock] 已完成任务：{task[:240]}", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _MockClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_MockCompletions())
