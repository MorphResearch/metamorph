"""GET /v1/fs/list — local directory browser for workspace selection.

本地部署（前后端同机）场景下，前端通过该接口逐级浏览磁盘目录，
选中的绝对路径将作为 agent 的 workspace 提交。仅返回目录、不返回
文件内容；服务绑定非 localhost 时已有强制 token 保护。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs

from api.middleware import json_response
from api.workers import TaskWorker


def _drives() -> list[dict[str, str]]:
    """列出 Windows 下所有存在的盘符根目录。"""
    drives: list[dict[str, str]] = []
    for code in range(ord("A"), ord("Z") + 1):
        root = f"{chr(code)}:\\"
        if os.path.exists(root):
            drives.append({"name": root, "path": root, "type": "dir"})
    return drives


def list_directories(handler: object, worker: TaskWorker, query: str) -> None:
    """返回指定路径下的子目录列表；path 为空时返回盘符根列表。"""
    raw = (parse_qs(query or "").get("path") or [""])[0].strip()
    if not raw:
        json_response(handler, 200, {"path": "", "parent": "", "entries": _drives()})
        return

    target = Path(raw).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        json_response(handler, 404, {"error": f"directory not found: {raw}"})
        return

    entries: list[dict[str, str]] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except (PermissionError, OSError):
        children = []
    for child in children:
        try:
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child), "type": "dir"})
        except (PermissionError, OSError):
            continue

    parent = str(target.parent) if target.parent != target else ""
    json_response(handler, 200, {"path": str(target), "parent": parent, "entries": entries})
