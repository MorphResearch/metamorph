from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .schemas import Decision


class ModelAdapter(Protocol):
    provider: str
    model_name: str

    def decide(self, task: str, observation: str, history: list[dict[str, Any]]) -> Decision:
        """Return one validated next action. The adapter must not execute tools."""


@dataclass
class MockModelAdapter:
    provider: str = "mock"
    model_name: str = "mock-v0"

    def decide(self, task: str, observation: str, history: list[dict[str, Any]]) -> Decision:
        return Decision(
            action="finish",
            answer=(
                "Mock mode completed the control loop. "
                f"Task received: {task}. No external model or write operation was used."
            ),
            summary="Return a deterministic answer so the runtime can be tested without an API key.",
        )


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


class OpenAIResponsesAdapter:
    def __init__(self, model_name: str = "gpt-5.6-terra"):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI mode requires the optional dependency: pip install -e '.[openai]'") from exc
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OpenAI mode requires OPENAI_API_KEY")
        self.client = OpenAI()
        self.provider = "openai"
        self.model_name = model_name

    def decide(self, task: str, observation: str, history: list[dict[str, Any]]) -> Decision:
        instructions = (
            "You are the planning model inside a safe local agent runtime. "
            "Return exactly one JSON object and do not use markdown. "
            "Allowed actions: list_files, read_file, write_file, finish. "
            "For list_files/read_file/write_file use arguments. "
            "Use finish with an answer when the task is complete. "
            "Do not invent tool results. Do not request shell, network, or paths outside the workspace."
        )
        payload = {
            "task": task,
            "latest_observation": observation,
            "history": history[-8:],
            "output_schema": {
                "action": "list_files | read_file | write_file | finish",
                "arguments": "object",
                "answer": "string",
                "summary": "short explanation of the action",
            },
        }
        response = self.client.responses.create(
            model=self.model_name,
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
        )
        return Decision.from_dict(_extract_json(response.output_text))


class OpenAICompatibleChatAdapter:
    """Adapter for providers exposing OpenAI Chat Completions compatibility."""

    def __init__(self, provider: str, model_name: str, base_url: str, api_key_env: str):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("This provider requires: pip install -e '.[openai]'") from exc
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"{provider} mode requires the {api_key_env} environment variable")
        self.provider = provider
        self.model_name = model_name
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def decide(self, task: str, observation: str, history: list[dict[str, Any]]) -> Decision:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": _SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": json.dumps({
                    "task": task,
                    "latest_observation": observation,
                    "history": history[-8:],
                }, ensure_ascii=False)},
            ],
            max_tokens=1200,
        )
        content = response.choices[0].message.content or ""
        return Decision.from_dict(_extract_json(content))


class AnthropicMessagesAdapter:
    """Adapter for Claude and Anthropic Messages-compatible providers."""

    def __init__(self, model_name: str, api_key_env: str = "ANTHROPIC_API_KEY"):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("Claude mode requires: pip install -e '.[anthropic]'") from exc
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"Claude mode requires the {api_key_env} environment variable")
        self.provider = "claude"
        self.model_name = model_name
        self.client = Anthropic(api_key=api_key)

    def decide(self, task: str, observation: str, history: list[dict[str, Any]]) -> Decision:
        message = self.client.messages.create(
            model=self.model_name,
            max_tokens=1200,
            system=_SYSTEM_INSTRUCTIONS,
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "task": task,
                    "latest_observation": observation,
                    "history": history[-8:],
                }, ensure_ascii=False),
            }],
        )
        content = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        return Decision.from_dict(_extract_json(content))


_SYSTEM_INSTRUCTIONS = (
    "You are the planning model inside a safe local agent runtime. "
    "Return exactly one JSON object and do not use markdown. "
    "Allowed actions: list_files, read_file, write_file, finish. "
    "For list_files/read_file/write_file use arguments. "
    "Use finish with an answer when the task is complete. "
    "Do not invent tool results. Do not request shell, network, or paths outside the workspace."
)


PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {"model": "gpt-5.6-terra", "api_key_env": "OPENAI_API_KEY"},
    "deepseek": {"model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com", "api_key_env": "DEEPSEEK_API_KEY"},
    "minimax": {"model": "MiniMax-M2.7", "base_url": "https://api.minimax.io/v1", "api_key_env": "MINIMAX_API_KEY"},
    "glm": {"model": "glm-5.1", "base_url": "https://api.z.ai/api/paas/v4/", "api_key_env": "ZAI_API_KEY"},
    "claude": {"model": "claude-opus-4-6", "api_key_env": "ANTHROPIC_API_KEY"},
    "sensenova": {"model": "deepseek-v4-flash", "base_url": "https://token.sensenova.cn/v1", "api_key_env": "SENSENOVA_API_KEY"},
}


def build_model(provider: str, model_name: str | None = None, base_url: str | None = None, api_key_env: str | None = None) -> ModelAdapter:
    if provider == "mock":
        return MockModelAdapter()
    if provider not in PROVIDER_DEFAULTS:
        raise ValueError(f"Unknown provider: {provider!r}; choose mock, openai, deepseek, minimax, claude, glm, or sensenova")
    defaults = PROVIDER_DEFAULTS[provider]
    selected_model = model_name or defaults["model"]
    selected_key_env = api_key_env or defaults["api_key_env"]
    if provider == "openai":
        return OpenAIResponsesAdapter(model_name=selected_model)
    if provider == "claude":
        return AnthropicMessagesAdapter(model_name=selected_model, api_key_env=selected_key_env)
    return OpenAICompatibleChatAdapter(
        provider=provider,
        model_name=selected_model,
        base_url=base_url or defaults["base_url"],
        api_key_env=selected_key_env,
    )


# Backwards-compatible name for code written against the first v0.1 adapter.
OpenAIModelAdapter = OpenAIResponsesAdapter
