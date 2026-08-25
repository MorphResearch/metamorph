"""Memory layer: cross-session user memory persistence and formatting.

Replaces scilink-agent's Postgres ``user_memories`` table with a local JSONL
file. The data-access logic lives in ``user_memory.py``; prompt formatting
lives in ``formatter.py``. The ``tools/memory.py`` module is a thin wrapper
that exposes the write path as a registered agent tool.
"""

from .formatter import format_memories
from .user_memory import (
    read_user_memories,
    _append_memory,
    _overwrite_memory_type,
    memory_path,
)

__all__ = [
    "_append_memory",
    "_overwrite_memory_type",
    "format_memories",
    "memory_path",
    "read_user_memories",
]
