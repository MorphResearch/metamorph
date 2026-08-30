"""Durable lesson storage for architecture adaptation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LessonStore:
    """Append-only JSONL store under the existing Metamorph data directory."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "multiagent_lessons.jsonl"

    def append(self, lesson: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(lesson, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 8) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries[-limit:]
