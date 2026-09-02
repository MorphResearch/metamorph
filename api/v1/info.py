"""GET /v1/info — server metadata endpoint."""

from __future__ import annotations

from api import __version__
from api.middleware import json_response
from config import Settings


def handle_get(handler: object, settings: Settings) -> None:
    """Return version, provider, model, and workspace metadata."""
    json_response(handler, 200, {
        "version": __version__,
        "provider": settings.provider,
        "model_name": settings.model_name,
        "mode": settings.mode,
        "allow_write": settings.allow_write,
        "max_steps": settings.max_steps,
        "workspace_root": str(settings.workspace_root),
    })
