"""Constrained, auditable code batches for AppWorld direct APIs.

AppWorld's code agents can call several direct APIs from one environment
interaction.  This module deliberately supports that useful subset (variables,
conditionals and ``for`` loops) without exposing imports, dynamic dispatch,
filesystem access, or arbitrary Python execution to the model.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


CODE_EXECUTOR_NAME = "metamorph__execute_code"
CODE_EXECUTOR_MARKER = "__METAMORPH_BATCH_CALLS__"
MAX_BATCH_CODE_CHARS = 20_000
MAX_BATCH_AST_NODES = 1_500


class BatchCodeRejected(ValueError):
    """Raised before execution when model-supplied code is outside the subset."""


@dataclass(frozen=True)
class BatchValidation:
    code: str
    api_names: tuple[str, ...]


@dataclass(frozen=True)
class BatchApiCall:
    name: str
    arguments: dict[str, Any]
    success: bool
    error: str | None = None


_ALLOWED_BUILTINS = {
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "len",
    "list",
    "max",
    "min",
    "print",
    "range",
    "reversed",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
}
_ALLOWED_METHODS = {
    "add",
    "append",
    "copy",
    "count",
    "endswith",
    "extend",
    "get",
    "index",
    "items",
    "join",
    "keys",
    "lower",
    "pop",
    "remove",
    "replace",
    "reverse",
    "sort",
    "split",
    "startswith",
    "strip",
    "update",
    "upper",
    "values",
}
_ALLOWED_STATEMENTS = (
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Break,
    ast.Continue,
    ast.Expr,
    ast.For,
    ast.If,
    ast.Pass,
)
_DISALLOWED_NODES = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.FunctionDef,
    ast.Global,
    ast.Import,
    ast.ImportFrom,
    ast.Lambda,
    ast.Match,
    ast.Nonlocal,
    ast.Raise,
    ast.Try,
    ast.While,
    ast.With,
    ast.Yield,
    ast.YieldFrom,
)


def code_executor_schema(*, allowed_names: list[str], read_only: bool) -> dict[str, Any]:
    """Return the synthetic function schema presented to the phase model."""

    access = "read-only APIs" if read_only else "the allowed APIs"
    return {
        "type": "function",
        "function": {
            "name": CODE_EXECUTOR_NAME,
            "description": (
                "Execute a constrained Python batch inside AppWorld. Use it for loops or bulk work; "
                f"it may call only {access}. No imports, files, network, eval/exec, definitions, "
                "or dynamic dispatch are allowed. Use keyword arguments for API calls and print a "
                "small summary. Every API invocation is recorded individually. Allowed direct APIs: "
                + ", ".join(sorted(allowed_names))
            ),
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Constrained Python code."}},
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    }


class _SubsetValidator(ast.NodeVisitor):
    def __init__(self, allowed_api_names: set[str]) -> None:
        self.allowed_api_names = allowed_api_names
        self.api_names: list[str] = []
        self._call_function_names: set[int] = set()

    def reject(self, node: ast.AST, message: str) -> None:
        raise BatchCodeRejected(f"line {getattr(node, 'lineno', '?')}: {message}")

    def visit_Module(self, node: ast.Module) -> Any:
        for statement in node.body:
            if not isinstance(statement, _ALLOWED_STATEMENTS):
                self.reject(statement, f"statement {type(statement).__name__} is not allowed")
        self.generic_visit(node)

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, _DISALLOWED_NODES):
            self.reject(node, f"syntax {type(node).__name__} is not allowed")
        return super().visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id.startswith("__") or node.id.startswith("_metamorph_"):
            self.reject(node, "dunder and reserved names are not allowed")
        if node.id in self.allowed_api_names and id(node) not in self._call_function_names:
            self.reject(node, f"API {node.id} may only be used as a direct call")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if node.attr.startswith("_"):
            self.reject(node, "private or dunder attributes are not allowed")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        if any(keyword.arg is None for keyword in node.keywords):
            self.reject(node, "**kwargs expansion is not allowed")
        if isinstance(node.func, ast.Name):
            name = node.func.id
            self._call_function_names.add(id(node.func))
            if name in self.allowed_api_names:
                if node.args:
                    self.reject(node, "API calls must use keyword arguments")
                self.api_names.append(name)
            elif name not in _ALLOWED_BUILTINS:
                self.reject(node, f"call to {name} is not allowed")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr not in _ALLOWED_METHODS:
                self.reject(node, f"method {node.func.attr} is not allowed")
        else:
            self.reject(node, "dynamic calls are not allowed")
        self.generic_visit(node)


def validate_batch_code(code: str, *, allowed_api_names: set[str]) -> BatchValidation:
    if not isinstance(code, str) or not code.strip():
        raise BatchCodeRejected("code must be a non-empty string")
    if len(code) > MAX_BATCH_CODE_CHARS:
        raise BatchCodeRejected(f"code exceeds {MAX_BATCH_CODE_CHARS} characters")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise BatchCodeRejected(f"syntax error: {exc.msg}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_BATCH_AST_NODES:
        raise BatchCodeRejected(f"code exceeds {MAX_BATCH_AST_NODES} AST nodes")
    validator = _SubsetValidator(allowed_api_names)
    validator.visit(tree)
    return BatchValidation(code=code, api_names=tuple(validator.api_names))


class _ApiCallInstrumenter(ast.NodeTransformer):
    def __init__(self, api_names: set[str]) -> None:
        self.api_names = api_names

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in self.api_names:
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="_metamorph_api_call", ctx=ast.Load()),
                    args=[ast.Constant(node.func.id), ast.Name(id=node.func.id, ctx=ast.Load())],
                    keywords=node.keywords,
                ),
                node,
            )
        return node


def instrument_batch_code(validation: BatchValidation) -> str:
    """Wrap every admitted API call and emit a parseable audit marker in ``finally``."""

    tree = ast.parse(validation.code, mode="exec")
    transformed = _ApiCallInstrumenter(set(validation.api_names)).visit(tree)
    ast.fix_missing_locations(transformed)
    body = transformed.body
    prelude = ast.parse(
        "_metamorph_calls = []\n"
        "def _metamorph_api_call(name, function, **kwargs):\n"
        "    try:\n"
        "        result = function(**kwargs)\n"
        "    except Exception as error:\n"
        "        _metamorph_calls.append((name, kwargs, False, type(error).__name__))\n"
        "        raise\n"
        "    _metamorph_calls.append((name, kwargs, True, None))\n"
        "    return result\n"
    ).body
    finalizer = ast.parse(f"print({CODE_EXECUTOR_MARKER!r} + repr(_metamorph_calls))").body
    wrapped = ast.Module(body=[*prelude, ast.Try(body=body, handlers=[], orelse=[], finalbody=finalizer)], type_ignores=[])
    ast.fix_missing_locations(wrapped)
    return ast.unparse(wrapped)


def extract_batch_calls(output: str) -> tuple[str, list[BatchApiCall]]:
    """Separate the instrumentation marker from user-visible environment output."""

    index = output.rfind(CODE_EXECUTOR_MARKER)
    if index < 0:
        raise BatchCodeRejected("batch execution did not produce its audit marker")
    before = output[:index]
    marker_and_after = output[index + len(CODE_EXECUTOR_MARKER) :]
    raw, separator, after = marker_and_after.partition("\n")
    visible = (before + (separator + after if separator else "")).rstrip()
    raw = raw.strip()
    try:
        entries = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise BatchCodeRejected("batch execution emitted an invalid audit marker") from exc
    if not isinstance(entries, list):
        raise BatchCodeRejected("batch execution audit marker is not a list")
    calls: list[BatchApiCall] = []
    for entry in entries:
        if not isinstance(entry, tuple) or len(entry) != 4:
            raise BatchCodeRejected("batch execution audit entry is malformed")
        name, arguments, success, error = entry
        if not isinstance(name, str) or not isinstance(arguments, dict) or not isinstance(success, bool):
            raise BatchCodeRejected("batch execution audit entry has invalid types")
        calls.append(BatchApiCall(name=name, arguments=arguments, success=success, error=error if isinstance(error, str) else None))
    return visible, calls
