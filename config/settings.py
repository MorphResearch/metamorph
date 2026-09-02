"""Runtime settings derived from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from llm.providers import PROVIDER_DEFAULTS


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    workspace_root: Path = Path("workspace")
    provider: str = "deepseek"
    model_name: str = PROVIDER_DEFAULTS["deepseek"]["model"]
    mode: str = "single"
    base_url: str | None = None
    api_key_env: str | None = None
    api_token_env: str = "METAMORPH_API_TOKEN"
    max_steps: int = 50
    max_parallel_agents: int = 8
    max_causal_audits: int = 2
    max_total_tokens: int | None = None
    max_latency_seconds: float | None = None
    max_tool_calls: int | None = None
    max_read_bytes: int = 100_000
    allow_write: bool = False

    @classmethod
    def from_environment(cls, data_dir: Path | None = None) -> "Settings":
        selected_dir = data_dir or Path(os.getenv("METAMORPH_DATA_DIR", ".metamorph"))
        provider = os.getenv("METAMORPH_PROVIDER", os.getenv("METAMORPH_MODEL_MODE", "deepseek"))
        model_name = os.getenv("METAMORPH_MODEL") or PROVIDER_DEFAULTS.get(provider, {}).get("model", "")
        return cls(
            data_dir=selected_dir,
            workspace_root=Path(os.getenv("METAMORPH_WORKSPACE_ROOT", "workspace")),
            provider=provider,
            model_name=model_name,
            mode=os.getenv("METAMORPH_MODE", "single"),
            base_url=os.getenv("METAMORPH_BASE_URL") or None,
            api_key_env=os.getenv("METAMORPH_API_KEY_ENV") or None,
            api_token_env=os.getenv("METAMORPH_API_TOKEN_ENV", "METAMORPH_API_TOKEN"),
            max_steps=int(os.getenv("METAMORPH_MAX_STEPS", "50")),
            max_parallel_agents=max(1, int(os.getenv("METAMORPH_MAX_PARALLEL_AGENTS", "8"))),
            max_causal_audits=max(0, int(os.getenv("METAMORPH_MAX_CAUSAL_AUDITS", "2"))),
            max_total_tokens=(int(os.getenv("METAMORPH_MAX_TOTAL_TOKENS", "0")) or None),
            max_latency_seconds=(float(os.getenv("METAMORPH_MAX_LATENCY_SECONDS", "0")) or None),
            max_tool_calls=(int(os.getenv("METAMORPH_MAX_TOOL_CALLS", "0")) or None),
            max_read_bytes=int(os.getenv("METAMORPH_MAX_READ_BYTES", "100000")),
            allow_write=os.getenv("METAMORPH_ALLOW_WRITE", "0").lower() in {"1", "true", "yes"},
        )
