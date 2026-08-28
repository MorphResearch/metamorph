"""Agent executor: high-level entry point for the tool-using LLM loop.

Composes ``streaming.py`` (chunk parsing) and ``loop.py`` (main orchestration)
into a single ``run_agent`` function. The public API is unchanged; the internal
split makes each piece independently testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .loop import _build_conversation, run_loop


def run_agent(
    *,
    client: Any,
    model_name: str,
    messages: list[dict[str, str]],
    logger: Any,
    data_dir: Path,
    workspace_root: Path,
    max_turns: int = 12,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Run the agent loop. Returns the final assistant answer text.

    ``history`` is the conversation message history (role/content pairs) to
    splice in before the newest user turn.  ``emit`` (optional) is called
    with ``(event_name, payload)`` for live streaming to the UI; otherwise
    events go through ``logger``.
    """
    ctx = {"data_dir": Path(data_dir), "workspace_root": Path(workspace_root)}
    convo = _build_conversation(messages, ctx["data_dir"], history=history)
    return run_loop(
        client=client,
        model_name=model_name,
        convo=convo,
        logger=logger,
        max_turns=max_turns,
        emit=emit,
        ctx=ctx,
    )
