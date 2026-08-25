"""Document tool: read a document from the workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .base import register


class ReadDocumentInput(BaseModel):
    path: str = Field(..., description="工作区内的文档相对路径")


def read_document(path: str, workspace_root: Path, max_read_bytes: int = 100_000) -> str:
    """Read a document from the workspace. Supports txt/md and best-effort
    pdf/docx via optional dependencies."""
    full = (Path(workspace_root) / path).resolve()
    try:
        full.relative_to(Path(workspace_root).resolve())
    except ValueError:
        return "不允许访问工作区之外的路径。"

    if not full.exists():
        return f"文件不存在：{path}"

    suffix = full.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".text", ".json", ".csv", ".log"}:
            data = full.read_text(encoding="utf-8", errors="ignore")
            return data[:max_read_bytes]
        if suffix == ".pdf":
            return _read_pdf(full)[:max_read_bytes]
        if suffix in {".docx", ".doc"}:
            return _read_docx(full)[:max_read_bytes]
    except Exception as exc:  # noqa: BLE001
        return f"读取文档失败：{exc}"
    return "不支持的文档类型。"


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "需要安装依赖：pip install pypdf"
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        return f"PDF 解析失败：{exc}"


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return "需要安装依赖：pip install python-docx"
    try:
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as exc:  # noqa: BLE001
        return f"DOCX 解析失败：{exc}"


register("read_document", ReadDocumentInput, read_document, pass_ctx=True)
