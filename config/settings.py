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
    max_steps: int = 12
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
            max_steps=int(os.getenv("METAMORPH_MAX_STEPS", "12")),
            max_read_bytes=int(os.getenv("METAMORPH_MAX_READ_BYTES", "100000")),
            allow_write=os.getenv("METAMORPH_ALLOW_WRITE", "0").lower() in {"1", "true", "yes"},
        )
