"""Data-access layer for cross-session user memory (JSONL on disk).

Mirrors scilink-agent's ``db/user_memory.py``. Memory entries are grouped by
type: ``user`` / ``feedback`` / ``project`` / ``reference``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def memory_path(data_dir: Path) -> Path:
    """Return the JSONL memory file path, creating directories as needed."""
    resolved = Path(data_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved / "user_memories.jsonl"


def read_user_memories(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Return ``{type: [entries]}`` grouped by memory type."""
    path = memory_path(data_dir)
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        return grouped
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        grouped.setdefault(entry.get("type", "user"), []).append(entry)
    return grouped


def _append_memory(data_dir: Path, entry: dict[str, Any]) -> None:
    """Append a single memory entry to the JSONL file."""
    path = memory_path(data_dir)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _overwrite_memory_type(data_dir: Path, mem_type: str, entries: list[dict[str, Any]]) -> None:
    """Replace all entries of ``mem_type`` with ``entries`` (upsert)."""
    path = memory_path(data_dir)
    all_entries: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                all_entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    kept = [e for e in all_entries if e.get("type") != mem_type]
    kept.extend(entries)
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept),
        encoding="utf-8",
    )
