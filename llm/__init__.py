"""LLM layer: provider configuration, thinking config, and client construction.

Mirrors the scilink-agent ``llm/`` layering: ``providers.py`` holds the
single-source default table, ``thinking.py`` handles model-specific thinking
parameters, and ``client.py`` builds the ready-to-use client.
"""

from .client import build_client, LLMClient
from .providers import PROVIDER_DEFAULTS, get_supported_providers
from .thinking import thinking_params_for
from .adapters import AdapterChunk, AdapterResponse, ProviderAdapter, build_adapter

__all__ = [
    "PROVIDER_DEFAULTS",
    "build_client",
    "get_supported_providers",
    "LLMClient",
    "thinking_params_for",
    "AdapterChunk",
    "AdapterResponse",
    "ProviderAdapter",
    "build_adapter",
]
