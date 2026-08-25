"""Format user memories into a system-prompt section.

Each memory type gets a human-readable Chinese heading, making the injected
content self-documenting for the LLM.
"""

from __future__ import annotations

from pathlib import Path

from .user_memory import read_user_memories


_MEMORY_LABELS: dict[str, str] = {
    "user": "用户画像",
    "feedback": "反馈偏好",
    "project": "项目背景",
    "reference": "参考资料",
}


def format_memories(data_dir: Path) -> str:
    """Return a markdown-formatted memory block, or ``""`` if empty."""
    grouped = read_user_memories(data_dir)
    if not grouped:
        return ""
    lines: list[str] = []
    for mem_type, entries in grouped.items():
        lines.append(f"## { _MEMORY_LABELS.get(mem_type, mem_type) }")
        for entry in entries:
            lines.append(f"- {entry.get('content', '')}")
    return "\n".join(lines)
