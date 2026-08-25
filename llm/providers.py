"""Provider defaults registry: model, base_url, and api-key env per provider.

This is the single source of truth for provider configuration, referenced by
``config.Settings`` (default resolution) and ``llm.client.build_client``.
Adding a new provider means adding one entry here.
"""

from __future__ import annotations

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "model": "gpt-5.6-terra",
        "api_key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "minimax": {
        "model": "MiniMax-M2.7",
        "base_url": "https://api.minimax.io/v1",
        "api_key_env": "MINIMAX_API_KEY",
    },
    "glm": {
        "model": "glm-5.1",
        "base_url": "https://api.z.ai/api/paas/v4/",
        "api_key_env": "ZAI_API_KEY",
    },
    "claude": {
        "model": "claude-opus-4-6",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "sensenova": {
        "model": "deepseek-v4-flash",
        "base_url": "https://token.sensenova.cn/v1",
        "api_key_env": "SENSENOVA_API_KEY",
    },
}


def get_supported_providers() -> list[str]:
    """Return the sorted list of registered provider keys."""
    return sorted(PROVIDER_DEFAULTS.keys())
