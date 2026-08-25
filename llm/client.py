"""OpenAI-compatible client construction.

The capability/config layer (scilink-agent's "字段提取层" equivalent):
imports ``PROVIDER_DEFAULTS`` from :mod:`llm.providers`, then builds a
ready-to-use client for the requested provider. The agent executor drives it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

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
    try:
        from openai import OpenAI
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "LLM providers require the optional dependency: pip install -e '.[openai]'"
        ) from exc

    if provider not in PROVIDER_DEFAULTS:
        raise ValueError(
            "Unknown provider: %r; choose from %s"
            % (provider, ", ".join(get_supported_providers()))
        )

    defaults = PROVIDER_DEFAULTS[provider]
    selected_model = model_name or defaults["model"]
    selected_key_env = api_key_env or defaults["api_key_env"]
    selected_base_url = base_url or defaults.get("base_url")

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
