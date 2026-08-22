from __future__ import annotations

import json
from pathlib import Path

from .schemas import ToolResult


class WorkspaceSandbox:
    """Path-restricted filesystem tools. No shell or network access in v0.1."""

    def __init__(self, root: Path, max_read_bytes: int = 100_000, allow_write: bool = False):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_read_bytes = max_read_bytes
        self.allow_write = allow_write

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escapes the configured workspace") from exc
        return candidate

    def list_files(self, relative_path: str = ".") -> ToolResult:
        try:
            directory = self.resolve(relative_path)
            if not directory.is_dir():
                return ToolResult(False, error="Not a directory")
            entries = []
            for path in sorted(directory.iterdir(), key=lambda item: item.name.lower())[:200]:
                entries.append({"path": str(path.relative_to(self.root)), "directory": path.is_dir()})
            return ToolResult(True, output=json.dumps(entries, ensure_ascii=False), metadata={"count": len(entries)})
        except (OSError, ValueError) as exc:
            return ToolResult(False, error=str(exc))

    def read_file(self, relative_path: str) -> ToolResult:
        try:
            path = self.resolve(relative_path)
            if not path.is_file():
                return ToolResult(False, error="Not a file")
            data = path.read_bytes()
            truncated = len(data) > self.max_read_bytes
            text = data[: self.max_read_bytes].decode("utf-8", errors="replace")
            return ToolResult(True, output=text, metadata={"bytes": len(data), "truncated": truncated})
        except (OSError, ValueError) as exc:
            return ToolResult(False, error=str(exc))

    def write_file(self, relative_path: str, content: str) -> ToolResult:
        if not self.allow_write:
            return ToolResult(False, error="write_file requires explicit approval (allow_write=false)")
        try:
            path = self.resolve(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(True, output=f"wrote {path.relative_to(self.root)}", metadata={"bytes": len(content.encode())})
        except (OSError, ValueError) as exc:
            return ToolResult(False, error=str(exc))
