"""File access tools: write, list, and path safety for the workspace.

与 ``read_document`` 对称的另一半：``write_file`` 负责写入，``list_files``
负责枚举目录结构。所有路径都限定在工作区内（防越界），写入类工具通过
``mutates=True`` 受执行策略（``allow_write``）守门——只读策略下
``base.dispatch`` 会直接拒绝执行。
"""

from __future__ import annotations

import fnmatch
from itertools import islice
from pathlib import Path

from pydantic import BaseModel, Field

from .base import register

_MAX_LIST_ENTRIES = 500   # 返回给模型的条目上限（控制 tool 结果体积）
_MAX_SCAN_ENTRIES = 2000  # 递归扫描上限（防止 node_modules 等巨型目录拖垮循环）


def _resolve_within_workspace(path: str, workspace_root: Path) -> tuple[Path | None, str]:
    """把相对路径解析到工作区内；越界/非法路径返回 (None, 错误说明)。

    重点：``resolve()`` 消解掉 ``..``、符号链接等间接路径后，再用
    ``relative_to`` 判断是否仍在工作区内部，任何逃逸都直接拒绝。
    """
    if not path.strip():
        return None, "路径不能为空。"
    full = (Path(workspace_root) / path).resolve()
    try:
        full.relative_to(Path(workspace_root).resolve())
    except ValueError:
        return None, "不允许访问工作区之外的路径。"
    return full, ""


def _human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


class WriteFileInput(BaseModel):
    path: str = Field(..., description="工作区内的目标文件相对路径（不存在时会自动创建父目录）")
    content: str = Field(..., description="要写入的完整文本内容（UTF-8，覆盖写入）")


def write_file(path: str, content: str, workspace_root: Path) -> str:
    """Write (create or overwrite) a UTF-8 text file inside the workspace.

    Parent directories are created automatically. Requires the write-enabled
    execution policy; otherwise dispatch rejects the call before reaching here.
    """
    full, err = _resolve_within_workspace(path, workspace_root)
    if full is None:
        return err

    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"写入文件失败：{exc}"
    return f"已写入 {path}（{len(content)} 字符）"


class ListFilesInput(BaseModel):
    path: str = Field("", description="工作区内的相对目录路径，留空表示工作区根目录")
    pattern: str = Field("", description="可选通配符过滤文件名，如 *.py 或 report*.md")
    recursive: bool = Field(False, description="是否递归列出全部子目录（条目过多时会截断）")


def list_files(path: str = "", pattern: str = "", recursive: bool = False, workspace_root: Path | None = None) -> str:
    """List directory contents of the workspace so the model can discover
    uploaded folders before reading specific files with read_document."""
    root = Path(workspace_root or ".")
    full, err = _resolve_within_workspace(path or ".", root)
    if full is None:
        return err
    if not full.exists():
        return f"目录不存在：{path or '.'}"
    if not full.is_dir():
        return f"不是目录：{path}"

    base = root.resolve()

    def rel_posix(p: Path) -> str:
        return p.relative_to(base).as_posix()

    lines: list[str] = []
    truncated = False
    if recursive:
        candidates = sorted(islice(full.rglob("*"), _MAX_SCAN_ENTRIES), key=lambda p: rel_posix(p).lower())
        if len(candidates) >= _MAX_SCAN_ENTRIES:
            truncated = True
    else:
        try:
            candidates = sorted(full.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError) as exc:
            return f"读取目录失败：{exc}"

    for child in candidates:
        if len(lines) >= _MAX_LIST_ENTRIES:
            truncated = True
            break
        try:
            if child.is_dir():
                lines.append(f"[目录] {rel_posix(child)}/")
            elif child.is_file():
                if pattern and not fnmatch.fnmatch(child.name.lower(), pattern.lower()):
                    continue
                try:
                    size = _human_size(child.stat().st_size)
                except OSError:
                    size = "?"
                lines.append(f"[文件] {rel_posix(child)}（{size}）")
        except (PermissionError, OSError):
            continue

    if not lines:
        return "目录为空或没有匹配的文件。"
    if truncated:
        lines.append(f"…（结果已截断，仅显示前 {len(lines)} 项；可用更具体的 path/pattern 缩小范围）")
    return "\n".join(lines)


register(
    "write_file",
    WriteFileInput,
    write_file,
    pass_ctx=True,
    ctx_keys=("workspace_root",),
    mutates=True,
)
register(
    "list_files",
    ListFilesInput,
    list_files,
    pass_ctx=True,
    ctx_keys=("workspace_root",),
)
