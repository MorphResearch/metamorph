"""Common tool-result utilities.

Analogous to scilink-agent's ``tools/utils.py``. Keeps tool output within
bounds and provides a placeholder for empty results so the agent loop always
receives a usable string.
"""

from __future__ import annotations

MAX_RESULT_CHARS: int = 8_000


def process_tool_result(result: object) -> str:
    """Normalise a tool result into a bounded, non-empty string.

    - ``None`` / empty result → placeholder text.
    - Over ``MAX_RESULT_CHARS`` → keep 60% head + 40% tail with an omission
      marker, splitting on line boundaries where possible.
    - Otherwise → ``str(result)`` unchanged.
    """
    text = "" if result is None else str(result)
    if not text:
        return "(工具未返回内容)"
    if len(text) <= MAX_RESULT_CHARS:
        return text
    head_end = int(MAX_RESULT_CHARS * 0.6)
    tail_start = head_end
    tail = text[tail_start:]
    return f"{text[:head_end]}\n...[省略 {len(text) - MAX_RESULT_CHARS} 字符]...\n{tail}"
