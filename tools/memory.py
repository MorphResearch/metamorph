"""Cross-session memory tool (thin wrapper around ``memory/`` package).

The data-access and formatting logic lives in ``memory/user_memory.py`` and
``memory/formatter.py``. This module only exposes the write path as a
registered agent tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory import (
    _append_memory,
    _overwrite_memory_type,
    format_memories,
    read_user_memories,
)

from .base import register


# Re-export for backward-compatible imports from ``tools`` package.
read_user_memories = read_user_memories  # noqa: PLW0127
_format_memories = format_memories


class UpdateUserMemoryInput(BaseModel):
    mode: str = Field(..., description="create=新增, update=按 type 覆盖, delete=清空该类型")
    type: str = Field("user", description="user / feedback / project / reference")
    content: str = Field("", description="要写入的记忆内容（mode=create/update 时必填）")


def update_user_memory(
    mode: str,
    data_dir: Path,
    type: str = "user",
    content: str = "",
) -> str:
    """Persist long-term memory to a local JSONL file (cross-session)."""
    if mode == "delete":
        _overwrite_memory_type(data_dir, type, [])
        return f"已清空 {type} 类型记忆。"
    if mode == "create":
        if not content:
            return "create 模式需要 content。"
        _append_memory(data_dir, {"type": type, "content": content})
        return f"已新增 {type} 记忆。"
    if mode == "update":
        existing = read_user_memories(data_dir).get(type, [])
        existing.append({"type": type, "content": content})
        _overwrite_memory_type(data_dir, type, existing)
        return f"已更新 {type} 记忆。"
    return "mode 必须是 create/update/delete。"


register("update_user_memory", UpdateUserMemoryInput, update_user_memory, pass_ctx=True)
