"""Agent tools: generic web retrieval, document reading, and cross-session
memory. Stripped of any vertical-domain logic.

Mirrors the scilink-agent ``tools/`` layering: a registry of tools with
pydantic schemas, a base layer for schema conversion / dispatch, and
individual modules per tool family.
"""

from .base import TOOL_REGISTRY, dispatch, get_registered_tools, tool_schemas
from .document import read_document
from .memory import update_user_memory, read_user_memories
from .tasklist import update_task_list
from .utils import process_tool_result
from .web import web_fetch, web_search

__all__ = [
    "TOOL_REGISTRY",
    "dispatch",
    "get_registered_tools",
    "process_tool_result",
    "read_document",
    "read_user_memories",
    "tool_schemas",
    "update_task_list",
    "update_user_memory",
    "web_fetch",
    "web_search",
]
