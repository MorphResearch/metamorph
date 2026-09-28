"""Isolated /memory and /work handling for the E0 experiment.

The paths exposed to an agent are logical paths.  Research records, frozen
snapshots, evaluator material, and database files are intentionally outside
the logical workspace root.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path


class WorkspaceAccessError(PermissionError):
    """Raised when a logical agent path is outside /memory or /work."""


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    path: Path
    content_hash: str
    parent_snapshot_id: str | None
    source_attempt_id: str | None
    files: tuple[str, ...]


@dataclass(frozen=True)
class AgentSession:
    attempt_id: str
    condition: str
    replicate: str
    task_id: str
    conversation_id: str
    agent_root: Path
    memory_root: Path
    work_root: Path
    parent_snapshot_id: str | None
    # Files inherited from a frozen source snapshot are agent-readable but
    # cannot be overwritten by a later source episode.  Each later episode
    # may add a new, episode-unique experience file of its own.
    immutable_memory_files: tuple[str, ...] = ()


def _safe_relative(path: str) -> tuple[str, Path]:
    raw = Path(path)
    if raw.is_absolute() or ".." in raw.parts:
        raise WorkspaceAccessError("agent path must be beneath /memory or /work")
    return raw.as_posix(), raw


def _walk_regular_files(root: Path) -> list[Path]:
    """Return a stable, safe tree; reject links and non-regular inputs."""
    if not root.exists():
        return []
    result: list[Path] = []
    for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if candidate.is_symlink():
            raise WorkspaceAccessError(f"symbolic links are not permitted: {candidate}")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise WorkspaceAccessError(f"non-regular file is not permitted: {candidate}")
        result.append(candidate)
    return result


def hash_tree(root: Path) -> tuple[str, tuple[str, ...]]:
    """Hash normalized names, executable bits, and bytes, never mtimes."""
    digest = hashlib.sha256()
    files: list[str] = []
    for item in _walk_regular_files(root):
        relative = item.relative_to(root).as_posix()
        executable = bool(item.stat().st_mode & stat.S_IXUSR)
        contents = item.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0file\0")
        digest.update(b"x" if executable else b"-")
        digest.update(b"\0")
        digest.update(hashlib.sha256(contents).digest())
        files.append(relative)
    return digest.hexdigest(), tuple(files)


def _copy_tree(source: Path, destination: Path) -> None:
    """Copy regular files only; never create shared hardlinks or follow links."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in _walk_regular_files(source):
        target = destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target, follow_symlinks=False)
        os.chmod(target, stat.S_IMODE(item.stat().st_mode))


class WorkspaceManager:
    """Creates fresh sessions and runner-only immutable snapshots."""

    def __init__(self, run_root: Path):
        self.run_root = Path(run_root).resolve()
        self.sessions_root = self.run_root / "agent_sessions"
        self.snapshots_root = self.run_root / "frozen_snapshots"
        self.research_root = self.run_root / "research_records"
        for path in (self.sessions_root, self.snapshots_root, self.research_root):
            path.mkdir(parents=True, exist_ok=True)

    def start_task(
        self,
        *,
        condition: str,
        replicate: str,
        task_id: str,
        parent: Snapshot | None = None,
        attempt_id: str | None = None,
    ) -> AgentSession:
        attempt_id = attempt_id or uuid.uuid4().hex
        root = self.sessions_root / attempt_id / "agent"
        memory = root / "memory"
        work = root / "work"
        memory.mkdir(parents=True, exist_ok=False)
        work.mkdir(parents=True, exist_ok=False)
        if parent is not None:
            _copy_tree(parent.path, memory)
            # A frozen source is read-only; its per-task clone must remain an
            # ordinary agent-writable workspace without changing the source.
            for item in _walk_regular_files(memory):
                item.chmod(stat.S_IMODE(item.stat().st_mode) | stat.S_IWUSR)
        return AgentSession(
            attempt_id=attempt_id,
            condition=condition,
            replicate=replicate,
            task_id=task_id,
            conversation_id=uuid.uuid4().hex,
            agent_root=root,
            memory_root=memory,
            work_root=work,
            parent_snapshot_id=parent.snapshot_id if parent else None,
            immutable_memory_files=parent.files if parent else (),
        )

    def resolve_agent_path(self, session: AgentSession, logical_path: str) -> Path:
        prefix, separator, remainder = logical_path.partition("/")
        if logical_path.startswith("/"):
            prefix, separator, remainder = logical_path[1:].partition("/")
        if prefix not in {"memory", "work"}:
            raise WorkspaceAccessError("only /memory and /work are visible to the agent")
        _, relative = _safe_relative(remainder or ".")
        root = session.memory_root if prefix == "memory" else session.work_root
        raw_target = root / relative
        # Reject every symlink component before resolution.  It prevents a
        # directory listing from becoming a way to traverse a link inside an
        # otherwise valid logical root.
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceAccessError("symbolic links are not permitted in agent paths")
        target = raw_target.resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise WorkspaceAccessError("agent path escapes logical workspace") from exc
        return target

    def list_agent_directory(self, session: AgentSession, logical_path: str, max_entries: int = 64) -> dict[str, object]:
        """List one logical directory without reading any file contents."""
        if max_entries < 1:
            raise ValueError("directory listing limit must be positive")
        target = self.resolve_agent_path(session, logical_path)
        if not target.exists():
            raise WorkspaceAccessError("agent directory does not exist")
        if not target.is_dir():
            raise WorkspaceAccessError("agent path is not a directory")
        entries = []
        for item in sorted(target.iterdir(), key=lambda candidate: candidate.name):
            if item.is_symlink():
                # Do not dereference or reveal the target of a link.
                entries.append({"name": item.name, "type": "symlink_blocked"})
            elif item.is_dir():
                entries.append({"name": item.name, "type": "directory"})
            elif item.is_file():
                entries.append({"name": item.name, "type": "file"})
            else:
                entries.append({"name": item.name, "type": "other_blocked"})
        returned = entries[:max_entries]
        return {
            "path": logical_path,
            "entries": returned,
            "returned": len(returned),
            "truncated": len(entries) > len(returned),
            "limit": max_entries,
        }

    def read_agent_file(self, session: AgentSession, logical_path: str) -> bytes:
        target = self.resolve_agent_path(session, logical_path)
        if target.is_symlink() or not target.is_file():
            raise WorkspaceAccessError("agent file does not exist or is not a regular file")
        return target.read_bytes()

    def write_agent_file(self, session: AgentSession, logical_path: str, data: bytes) -> None:
        target = self.resolve_agent_path(session, logical_path)
        normalized = logical_path.lstrip("/")
        if normalized.startswith("memory/"):
            relative = normalized.removeprefix("memory/")
            if relative in session.immutable_memory_files:
                raise WorkspaceAccessError("inherited frozen memory artifacts are immutable")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Check every existing parent after resolution.  This also rejects a
        # link introduced by an external process during a test.
        current = target.parent
        while current != session.agent_root:
            if current.is_symlink():
                raise WorkspaceAccessError("symbolic-link parent is not permitted")
            current = current.parent
        target.write_bytes(data)

    def freeze_memory(self, session: AgentSession, parent: Snapshot | None = None) -> Snapshot:
        content_hash, files = hash_tree(session.memory_root)
        snapshot_id = f"snapshot-{uuid.uuid4().hex}"
        target = self.snapshots_root / snapshot_id
        _copy_tree(session.memory_root, target)
        # Read-only permissions are defense-in-depth; probes receive copies.
        for item in _walk_regular_files(target):
            item.chmod(stat.S_IRUSR | (stat.S_IXUSR if item.stat().st_mode & stat.S_IXUSR else 0))
        return Snapshot(
            snapshot_id=snapshot_id,
            path=target,
            content_hash=content_hash,
            parent_snapshot_id=parent.snapshot_id if parent else None,
            source_attempt_id=session.attempt_id,
            files=files,
        )

    def empty_snapshot(self) -> Snapshot:
        snapshot_id = f"snapshot-empty-{uuid.uuid4().hex}"
        target = self.snapshots_root / snapshot_id
        target.mkdir()
        content_hash, files = hash_tree(target)
        return Snapshot(snapshot_id, target, content_hash, None, None, files)
