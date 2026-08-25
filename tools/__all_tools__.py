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
    "read_document",
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
    "update_user_memory": {
        "display_name": "更新记忆",
        "example_prompt": "记住用户偏好用简体中文",
        "category": "memory",
    },
}
