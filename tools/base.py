"""Tool base layer: registry, pydantic→OpenAI schema conversion, dispatch."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel


TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def register(
    name: str,
    schema: type[BaseModel],
    fn: Callable,
    pass_ctx: bool = False,
    ctx_keys: tuple[str, ...] = (),
) -> None:
    """Register a tool and the exact runtime context keys it may receive."""
    TOOL_REGISTRY[name] = {
        "schema": schema,
        "fn": fn,
        "pass_ctx": pass_ctx,
        "ctx_keys": ctx_keys,
    }


def get_registered_tools() -> list[str]:
    return list(TOOL_REGISTRY.keys())


def openai_tool_schema(name: str, pydantic_schema: type[BaseModel]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for field_name, field in pydantic_schema.model_fields.items():
        annotation = field.annotation
        if annotation is bool:
            ttype = "boolean"
        elif annotation is int:
            ttype = "integer"
        elif annotation is float:
            ttype = "number"
        else:
            ttype = "string"
        props[field_name] = {"type": ttype, "description": field.description or ""}
        if field.is_required():
            required.append(field_name)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (pydantic_schema.__doc__ or "").strip(),
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def tool_schemas() -> list[dict[str, Any]]:
    return [openai_tool_schema(name, meta["schema"]) for name, meta in TOOL_REGISTRY.items()]


def dispatch(name: str, arguments: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Validate arguments and execute the named tool, returning its string output."""
    meta = TOOL_REGISTRY.get(name)
    if meta is None:
        return f"工具不存在：{name}"
    try:
        validated = meta["schema"](**arguments)
    except Exception as exc:  # noqa: BLE001
        return f"参数校验失败：{exc}"
    kwargs = validated.model_dump()
    try:
        if meta["pass_ctx"]:
            scoped_ctx = {key: ctx[key] for key in meta["ctx_keys"] if key in ctx}
            return str(meta["fn"](**kwargs, **scoped_ctx))
        return str(meta["fn"](**kwargs))
    except Exception as exc:  # noqa: BLE001 - tool failures become observations
        return f"工具执行失败：{exc}"
