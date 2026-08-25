"""Model-specific thinking / reasoning configuration.

Analogous to scilink-agent's ``llm/thinking_config.py``. Returns extra kwargs
to pass into the LLM call so reasoning / thinking is enabled per-model.
"""

from __future__ import annotations


def thinking_params_for(model_name: str) -> dict[str, object]:
    """Return extra kwargs to enable thinking for the given model.

    DeepSeek V4 series have thinking enabled by default (return ``{}``).
    DeepSeek V3 needs explicit ``thinking: {type: enabled}`` in ``extra_body``.
    All other models return ``{}`` (no special handling required).
    """
    lower = model_name.lower()
    if "v4" in lower:
        # DeepSeek V4 series: thinking on by default
        return {}
    if lower.startswith("deepseek"):
        # DeepSeek V3: explicit thinking enable
        return {"extra_body": {"thinking": {"type": "enabled"}}}
    return {}
