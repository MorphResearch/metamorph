"""Tool registry overview: display metadata for every registered tool.

Mirrors scilink-agent's ``main_graph.py:ALL_TOOLS`` / ``TOOL_META`` pattern.
This is the single source of truth for tool display names and categories; the
actual implementations are registered separately in each tool module.
"""

from __future__ import annotations

# Ordered list of all registered tool names (mirrors the registration order).
ALL_TOOLS: list[str] = [
    "web_search",
    "web_fetch",
    "list_files",
    "read_document",
    "write_file",
    "update_user_memory",
]

# Display metadata per tool (used by the frontend / skills page).
TOOL_META: dict[str, dict[str, str]] = {
    "web_search": {
        "display_name": "网页搜索",
        "example_prompt": "搜索最新的 Python 3.13 特性",
        "category": "web",
    },
    "web_fetch": {
        "display_name": "网页抓取",
        "example_prompt": "抓取 https://example.com 的正文",
        "category": "web",
    },
    "read_document": {
        "display_name": "读取文档",
        "example_prompt": "读取工作区中的报告.pdf",
        "category": "document",
    },
    "list_files": {
        "display_name": "列出文件",
        "example_prompt": "检查当前工作区并总结文件结构",
        "category": "document",
    },
    "write_file": {
        "display_name": "写入文件",
        "example_prompt": "把整理好的要点写入 工作区/summary.md",
        "category": "document",
    },
    "update_user_memory": {
        "display_name": "更新记忆",
        "example_prompt": "记住用户偏好用简体中文",
        "category": "memory",
    },
}
