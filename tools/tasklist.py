"""Task list tool: lets the model plan multi-step tasks and track progress.

模型在处理多步任务时可调用该工具创建/更新任务清单；清单随 tool.completed
事件落盘，前端渲染为可跟踪的任务列表卡片（对齐主流 Agent 的 Todo 能力）。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .base import register

_VALID_STATUS = {"pending", "in_progress", "completed"}


class UpdateTaskListInput(BaseModel):
    tasks_json: str = Field(
        ...,
        description=(
            "任务清单 JSON 数组字符串（每次传完整清单做全量替换），"
            '每项形如 {"content": "任务描述", "status": "pending|in_progress|completed"}'
        ),
    )


def update_task_list(tasks_json: str) -> str:
    """Update the visible task list for the current run. Pass the FULL list
    every time as a JSON array string; items carry content and status
    (pending / in_progress / completed)."""
    try:
        tasks: Any = json.loads(tasks_json)
    except json.JSONDecodeError as exc:
        return f"参数校验失败：tasks_json 不是合法 JSON：{exc}"
    if not isinstance(tasks, list) or not tasks:
        return "参数校验失败：任务清单不能为空"
    for item in tasks:
        if (
            not isinstance(item, dict)
            or not str(item.get("content", "")).strip()
            or item.get("status") not in _VALID_STATUS
        ):
            return "参数校验失败：每项需要非空 content 和 status(pending/in_progress/completed)"
    done = sum(1 for t in tasks if t["status"] == "completed")
    in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
    return f"任务清单已更新：共 {len(tasks)} 项，{done} 项完成，{in_progress} 项进行中"


register("update_task_list", UpdateTaskListInput, update_task_list)
