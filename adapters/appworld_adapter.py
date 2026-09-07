"""Fixed-S3 AppWorld controller with strict contracts and auditable checkpoints.

The module intentionally depends on a small world/model protocol so all causal
semantics can be tested without exposing AppWorld ground truth to an agent.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel

from .appworld_budget import AppWorldBudgetLedger, BudgetExhausted, BudgetLimits
from .appworld_code_executor import (
    CODE_EXECUTOR_NAME,
    BatchCodeRejected,
    code_executor_schema,
    extract_batch_calls,
    instrument_batch_code,
    validate_batch_code,
)
from .appworld_contracts import (
    ExecutorArtifact,
    PlannerArtifact,
    SCHEMA_VERSION,
    ToolSelectionArtifact,
    VerifierArtifact,
    artifact_hash,
    canonical_json,
    typed_null,
    validate_artifact,
)
from .appworld_dag import DAGExecutor, DAGNode, DAGSpec, Intervention


READ_METHODS = {"GET"}
LOGIN_API = "login"
MAX_TOOL_OUTPUT_CHARS = 20_000
# Tool schemas are repeated on every function-calling turn.  A smaller fixed
# shortlist keeps the executor's context from crowding out its handoff
# artifact while still leaving enough room for cross-app tasks.
MAX_SELECTED_TOOLS = 20


class ProviderRequestTimeout(TimeoutError):
    """Hard wall-clock timeout for one isolated provider request."""


def _provider_request_worker(
    connection: Any,
    provider: str,
    model_name: str,
    base_url: str | None,
    api_key_env: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    generation_options: dict[str, Any],
) -> None:
    """Spawn-safe worker that creates its own SDK/transport after process start."""

    try:  # pragma: no cover - exercised in spawned subprocess
        from llm.client import build_client

        bundle = build_client(provider, model_name, base_url, api_key_env)
        payload: tuple[Any, ...] = (
            "ok",
            bundle.adapter.complete_configured(
                model_name=model_name,
                messages=messages,
                tools=tools,
                generation_options=generation_options,
            ),
        )
    except BaseException as exc:
        payload = ("error", type(exc).__name__, str(exc))
    try:
        connection.send(payload)
    finally:
        connection.close()


def isolated_provider_request(
    *,
    provider: str,
    model_name: str,
    base_url: str | None,
    api_key_env: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    generation_options: dict[str, Any],
    seconds: float | None,
) -> Any:
    """Run one provider request in a spawn child with a true wall-clock cap.

    macOS forbids using the certificate bridge after ``fork()``. ``spawn``
    creates a fresh interpreter and SDK transport, so the parent can safely
    terminate an unresponsive DeepSeek request without affecting AppWorld state.
    """

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_provider_request_worker,
        args=(child, provider, model_name, base_url, api_key_env, messages, tools, generation_options),
    )
    process.start()
    child.close()
    try:
        if seconds is not None and seconds > 0 and not parent.poll(float(seconds)):
            process.terminate()
            process.join()
            raise ProviderRequestTimeout(f"provider request exceeded {seconds:.3f}s hard timeout")
        try:
            payload = parent.recv()
        except EOFError as exc:
            raise RuntimeError("provider child exited without a response") from exc
    finally:
        parent.close()
        process.join()
    if payload[0] == "ok":
        return payload[1]
    raise RuntimeError(f"provider child failed: {payload[1]}: {payload[2]}")


class PhaseModel(Protocol):
    model_name: str

    def complete(
        self,
        *,
        phase: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_output_tokens: int,
    ) -> Any: ...


class ProviderPhaseModel:
    """Bridge Metamorph's normalized provider adapter into the experiment core."""

    def __init__(
        self,
        client_bundle: Any,
        *,
        temperature: float = 0.0,
        seed: int | None = None,
        request_timeout_seconds: float | None = None,
    ) -> None:
        self.model_name = client_bundle.model_name
        self.provider = client_bundle.provider
        self.base_url = client_bundle.base_url
        self.api_key_env: str | None = None
        self.temperature = temperature
        self.seed = seed
        self.request_timeout_seconds = request_timeout_seconds

    def configure(self, *, temperature: float, seed: int, request_timeout_seconds: float | None = None) -> None:
        self.temperature = temperature
        self.seed = seed
        self.request_timeout_seconds = request_timeout_seconds

    def complete(
        self,
        *,
        phase: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_output_tokens: int,
    ) -> Any:
        del phase
        generation_options = {
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": max_output_tokens,
            "timeout": self.request_timeout_seconds,
        }
        return isolated_provider_request(
            provider=self.provider,
            model_name=self.model_name,
            base_url=self.base_url,
            api_key_env=self.api_key_env,
            messages=messages,
            tools=tools,
            generation_options=generation_options,
            seconds=self.request_timeout_seconds,
        )

    def complete_finalization(
        self,
        *,
        phase: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_output_tokens: int,
    ) -> Any:
        """Request a terminal artifact, never another tool interaction.

        JSON mode is deliberately confined to this request: the preceding
        phase can use native function calling, while this request can only
        commit the typed handoff from the already-observed evidence.
        """

        del phase
        generation_options = {
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": max_output_tokens,
            "timeout": self.request_timeout_seconds,
            "response_format": {"type": "json_object"},
        }
        return isolated_provider_request(
            provider=self.provider,
            model_name=self.model_name,
            base_url=self.base_url,
            api_key_env=self.api_key_env,
            messages=messages,
            tools=tools,
            generation_options=generation_options,
            seconds=self.request_timeout_seconds,
        )


@dataclass
class PhaseTrace:
    phase: str
    status: str
    answer: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    code_batches: list[dict[str, Any]] = field(default_factory=list)
    contract_errors: list[str] = field(default_factory=list)
    provider_protocol_mismatches: list[str] = field(default_factory=list)
    finalization_attempts: list[dict[str, Any]] = field(default_factory=list)
    artifact: dict[str, Any] | None = None
    started_at: float = 0.0
    latency_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _response_parts(response: Any) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if isinstance(response, dict):
        return (
            str(response.get("content", response.get("answer", "")) or ""),
            list(response.get("tool_calls") or []),
            dict(response.get("usage") or response.get("metrics") or {}),
        )
    return (
        str(getattr(response, "content", "") or ""),
        list(getattr(response, "tool_calls", None) or []),
        dict(getattr(response, "usage", None) or {}),
    )


def _contains_unstructured_tool_markup(content: str) -> bool:
    """Detect, but never execute, provider-private tool-call markup."""

    lowered = content.lower()
    return "dsml" in lowered and "tool_call" in lowered


def _estimate_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    # UTF-8 bytes / 3 is conservative for the English-heavy AppWorld schemas.
    payload = json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False)
    return max(1, (len(payload.encode("utf-8")) + 2) // 3)


def _hash_directory(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return digest.hexdigest()
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(file_path.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_tool_code(function_name: str, arguments: dict[str, Any]) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*__[a-zA-Z_][a-zA-Z0-9_]*", function_name):
        raise ValueError(f"invalid AppWorld function name: {function_name}")
    return f"print({function_name}(**{arguments!r}))"


def _artifact_action_name(app: str, api: str) -> str:
    """Accept contract actions written as either ``app``/``api`` or API name.

    AppWorld's function-calling schemas expose names such as
    ``file_system__show_file``.  Models therefore naturally put the complete
    callable in the ``api`` field; concatenating its app namespace a second
    time turns an otherwise observed action into a false hallucination.
    """

    return api if "__" in api else f"{app}__{api}"


def _contract_instructions(contract: type[BaseModel]) -> str:
    return (
        "Return exactly one JSON object, with no markdown or surrounding prose. "
        "It must validate against this JSON Schema:\n"
        + json.dumps(contract.model_json_schema(), ensure_ascii=False, sort_keys=True)
    )


class AppWorldController:
    """Execute one S0 or fixed-S3 condition inside one AppWorld instance."""

    def __init__(
        self,
        *,
        world: Any,
        model: PhaseModel,
        limits: BudgetLimits,
        trace_dir: Path,
        json_contract: bool = True,
        enable_verifier: bool = True,
        enable_repair: bool = True,
        max_output_tokens: int = 4096,
        initial_usage: dict[str, Any] | None = None,
        require_token_usage: bool = False,
        request_timeout_seconds: float | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.world = world
        self.model = model
        self.ledger = AppWorldBudgetLedger(limits, initial_usage=initial_usage)
        self.trace_dir = trace_dir
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.json_contract = json_contract
        self.enable_verifier = enable_verifier
        self.enable_repair = enable_repair
        self.max_output_tokens = max_output_tokens
        self.require_token_usage = require_token_usage
        self.request_timeout_seconds = request_timeout_seconds
        self.event_callback = event_callback
        self.traces: dict[str, PhaseTrace] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self._function_docs = list(world.task.api_docs.function_calling())
        self._standard_docs = {
            f"{app_name}__{api_name}": doc
            for app_name, api_docs in world.task.api_docs.items()
            for api_name, doc in api_docs.items()
        }
        self._function_by_name = {
            item["function"]["name"]: item for item in self._function_docs
        }
        # AppWorld direct function calls are separate execution contexts.  If
        # a direct login succeeds, a later direct API call cannot inherit its
        # session and is stopped rather than being recorded as a false task
        # failure. The model can retry with one constrained code batch.
        self._direct_login_apps: set[str] = set()
        self.selected_tool_names: list[str] = []

    def _emit_event(self, event: str, **details: Any) -> None:
        """Best-effort arm observability; controller semantics never depend on it."""

        if self.event_callback is not None:
            self.event_callback(event, details)

    def _write_trace(self, trace: PhaseTrace) -> None:
        self.traces[trace.phase] = trace
        path = self.trace_dir / f"{trace.phase}.json"
        path.write_text(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_write(self, tool_name: str) -> bool:
        doc = self._standard_docs.get(tool_name, {})
        # Login creates an authentication session but is allowed in read-only
        # phases and is not counted as a task-state write action.
        return str(doc.get("method", "POST")).upper() not in READ_METHODS and doc.get("api_name") != LOGIN_API

    def _requires_session_safe_batch(self, tool_name: str) -> bool:
        app, separator, api = tool_name.partition("__")
        return bool(separator and api != LOGIN_API and app in self._direct_login_apps)

    def _tools(self, names: list[str], *, read_only: bool) -> list[dict[str, Any]]:
        output = []
        for name in names:
            if name not in self._function_by_name:
                continue
            if read_only and self._is_write(name):
                continue
            output.append(self._function_by_name[name])
        # This synthetic tool retains function-calling compatibility while
        # allowing the paper's code-style agents to loop over direct APIs in a
        # single AppWorld interaction. Its AST validator only admits ``output``.
        output.append(
            code_executor_schema(
                allowed_names=[item["function"]["name"] for item in output],
                read_only=read_only,
            )
        )
        return output

    def _execute_batch_code(
        self,
        *,
        code: str,
        allowed_names: set[str],
        phase: str,
        trace: PhaseTrace,
    ) -> tuple[str, list[dict[str, Any]], bool]:
        """Execute one validated code batch and account for actual API calls.

        The AppWorld requester enforces the remaining aggregate API allowance
        during the cell itself.  Instrumentation then gives us an exact
        per-call audit record for artifact reconciliation and cost reporting.
        """

        validation = validate_batch_code(code, allowed_api_names=allowed_names)
        writes = [name for name in validation.api_names if self._is_write(name)]
        if writes and not self.ledger.limits.allow_write:
            self.ledger.safety_incidents += 1
            raise PermissionError("write action rejected by allow_write=false")
        remaining = self.ledger.remaining_tool_calls()
        if validation.api_names and remaining < 1:
            self.ledger.ensure_tool_capacity(1)
        tracker = getattr(getattr(self.world, "requester", None), "request_tracker", None)
        if tracker is None or not hasattr(tracker, "max_num_requests"):
            raise RuntimeError("AppWorld code executor requires a request-tracked world")
        old_cap = tracker.max_num_requests
        tracker.max_num_requests = max(1, remaining)
        try:
            raw_output = str(self.world.execute(instrument_batch_code(validation)))
        finally:
            tracker.max_num_requests = old_cap
        visible_output, calls = extract_batch_calls(raw_output)
        records: list[dict[str, Any]] = []
        for call in calls:
            if call.name not in allowed_names:
                self.ledger.safety_incidents += 1
                raise PermissionError(f"batch called a tool not allowed in {phase}: {call.name}")
            is_write = self._is_write(call.name)
            self.ledger.before_tool_call(is_write=is_write)
            record = {
                "name": call.name,
                "arguments": call.arguments,
                "output": "[executed in constrained code batch]",
                "success": call.success,
                "batch": True,
            }
            if call.error:
                record["error"] = call.error
            records.append(record)
            if not call.success:
                self.ledger.record_error(tool=True)
        if calls:
            self.ledger.after_tool_call()
        batch_record = {
            "code": validation.code,
            "api_names_static": list(validation.api_names),
            "api_calls_observed": len(calls),
            "write_calls_observed": sum(1 for call in calls if self._is_write(call.name)),
            "success": not raw_output.startswith("Execution failed") and all(call.success for call in calls),
        }
        trace.code_batches.append(batch_record)
        summary = visible_output or f"Code batch executed {len(calls)} API call(s)."
        return summary, records, bool(batch_record["success"])

    def _call_model(
        self,
        *,
        phase: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        finalization: bool = False,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Make one accounted provider call, optionally in terminal JSON mode."""

        self.ledger.before_model_call(_estimate_tokens(messages, tools), self.max_output_tokens)
        call_number = self.ledger.snapshot()["steps"] + 1
        provider_started = time.clock_gettime(time.CLOCK_MONOTONIC)
        self._emit_event("PROVIDER_START", phase=phase, call=call_number, finalization=finalization)
        try:
            if finalization and callable(getattr(self.model, "complete_finalization", None)):
                response = self.model.complete_finalization(
                    phase=phase,
                    messages=messages,
                    tools=tools,
                    max_output_tokens=self.max_output_tokens,
                )
            else:
                response = self.model.complete(
                    phase=phase,
                    messages=messages,
                    tools=tools,
                    max_output_tokens=self.max_output_tokens,
                )
        except Exception as exc:
            self._emit_event(
                "PROVIDER_END", phase=phase, call=call_number, finalization=finalization,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self._emit_event(
            "PROVIDER_END", phase=phase, call=call_number, finalization=finalization,
            latency_seconds=round(time.clock_gettime(time.CLOCK_MONOTONIC) - provider_started, 6),
        )
        content, tool_calls, usage = _response_parts(response)
        has_token_usage = any(
            key in usage
            for key in ("prompt_tokens", "input_tokens", "completion_tokens", "output_tokens", "total_tokens")
        )
        if not has_token_usage:
            self.ledger.missing_token_usage_calls += 1
            if self.require_token_usage:
                raise RuntimeError("provider response is missing token usage in formal mode")
        self.ledger.record_model_call(usage)
        return content, tool_calls

    @staticmethod
    def _finalization_prompt(contract: type[BaseModel]) -> str:
        evidence_rule = (
            "If the available evidence is insufficient to verify success, return NOT_VERIFIED with concrete "
            "non-empty repair_instructions."
            if contract is VerifierArtifact
            else "Use only the evidence already present in the conversation."
        )
        return (
            "Tool interaction is now complete. Do not call tools, request additional information, or continue "
            "reasoning through tool use. Commit the final typed artifact using only the evidence already present. "
            + evidence_rule
            + "\n\n"
            + _contract_instructions(contract)
        )

    def _finalize_artifact(
        self,
        *,
        phase: str,
        messages: list[dict[str, Any]],
        contract: type[BaseModel],
        trace: PhaseTrace,
        allow_contract_retry: bool,
    ) -> BaseModel | None:
        """Commit one typed artifact after the tool loop has terminated."""

        finalization_messages = [*messages, {"role": "user", "content": self._finalization_prompt(contract)}]
        attempts = 2 if allow_contract_retry else 1
        for attempt in range(1, attempts + 1):
            self._emit_event("ARTIFACT_FINALIZATION_START", phase=phase, attempt=attempt)
            content, tool_calls = self._call_model(
                phase=phase,
                messages=finalization_messages,
                tools=[],
                finalization=True,
            )
            record = {
                "attempt": attempt,
                "tools_enabled": False,
                "json_mode_requested": True,
                "content_chars": len(content),
                "structured_tool_calls_returned": len(tool_calls),
            }
            trace.finalization_attempts.append(record)
            trace.answer = content
            errors: list[str] = []
            if tool_calls:
                message = "provider_protocol_mismatch: structured tool call returned during tools-disabled artifact finalization"
                trace.provider_protocol_mismatches.append(message)
                errors.append(message)
            if _contains_unstructured_tool_markup(content):
                message = "provider_protocol_mismatch: unstructured DSML-like tool markup returned during artifact finalization"
                trace.provider_protocol_mismatches.append(message)
                errors.append(message)
            artifact, validation_errors = validate_artifact(content, contract)
            errors.extend(validation_errors)
            if artifact is not None and not tool_calls:
                trace.status = "completed"
                trace.artifact = artifact.model_dump(mode="json")
                self._emit_event("ARTIFACT_FINALIZATION_END", phase=phase, attempt=attempt, status="completed")
                return artifact

            trace.contract_errors.extend(errors)
            self.ledger.record_error(contract=True)
            self._emit_event("ARTIFACT_FINALIZATION_END", phase=phase, attempt=attempt, status="invalid_contract")
            if attempt == attempts:
                trace.status = "invalid_contract"
                return None
            finalization_messages.extend([
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": "Your previous artifact was invalid: " + " | ".join(errors)
                    + "\nDo not call tools. Return only one corrected JSON object.\n\n"
                    + self._finalization_prompt(contract),
                },
            ])
        raise AssertionError("unreachable finalization state")

    def _tool_catalog(self) -> dict[str, str]:
        return {
            name: str(doc.get("description", ""))
            for name, doc in self._standard_docs.items()
            if name in self._function_by_name
        }

    def select_tools(self) -> list[str]:
        catalog = self._tool_catalog()
        mandatory = {
            name
            for name in catalog
            if name.startswith("supervisor__") or name.endswith("__login")
        }
        prompt = (
            "Select the AppWorld APIs that may be needed to solve the task. Use only the task and "
            "API names/descriptions; do not infer from hidden outcomes. Include APIs for retrieval, "
            f"mutation, verification, and task completion. Select at most {MAX_SELECTED_TOOLS}.\n\n"
            f"TASK:\n{self.world.task.instruction}\n\n"
            f"API CATALOG:\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
            + _contract_instructions(ToolSelectionArtifact)
        )
        trace, artifact = self._run_phase(
            "tool_selector", prompt, [], contract=ToolSelectionArtifact, allow_contract_retry=True
        )
        selected = list(artifact.tools) if isinstance(artifact, ToolSelectionArtifact) else []
        selected = [name for name in selected if name in self._function_by_name]
        if len(mandatory) > MAX_SELECTED_TOOLS:
            raise ValueError(f"mandatory AppWorld tools exceed selector limit: {len(mandatory)}")
        optional = sorted(set(selected) - mandatory)
        selected = sorted(mandatory) + optional[: MAX_SELECTED_TOOLS - len(mandatory)]
        if not selected:
            # Deterministic, outcome-independent fallback. This is deliberately
            # broad enough to keep the run diagnosable rather than silently fail.
            selected = sorted(mandatory) + sorted(set(catalog) - mandatory)[: MAX_SELECTED_TOOLS - len(mandatory)]
        self.selected_tool_names = selected
        trace.artifact = {"selected_tools": selected, "count": len(selected)}
        self._write_trace(trace)
        return selected

    def _run_phase(
        self,
        phase: str,
        prompt: str,
        tools: list[dict[str, Any]],
        *,
        contract: type[BaseModel] | None = None,
        allow_contract_retry: bool = True,
    ) -> tuple[PhaseTrace, BaseModel | str | None]:
        started = time.clock_gettime(time.CLOCK_MONOTONIC)
        trace = PhaseTrace(
            phase=phase,
            status="running",
            started_at=time.clock_gettime(time.CLOCK_REALTIME),
        )
        self._emit_event("STAGE_START", phase=phase)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a bounded AppWorld experiment agent. Never use hidden ground truth."},
            {"role": "user", "content": prompt},
        ]
        try:
            # Tool-free stages are artifact commitments from the outset.  They
            # skip a redundant reasoning call while retaining the same strict
            # terminal JSON protocol as tool-using stages.
            if contract is not None and not tools:
                artifact = self._finalize_artifact(
                    phase=phase,
                    messages=messages,
                    contract=contract,
                    trace=trace,
                    allow_contract_retry=allow_contract_retry,
                )
                trace.latency_seconds = round(time.clock_gettime(time.CLOCK_MONOTONIC) - started, 6)
                self._write_trace(trace)
                self._emit_event("STAGE_END", phase=phase, status=trace.status)
                return trace, artifact
            while True:
                content, tool_calls = self._call_model(phase=phase, messages=messages, tools=tools)
                if tool_calls:
                    messages.append({
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [
                            {
                                "id": item.get("id") or f"{phase}-{len(trace.tool_calls)}-{index}",
                                "type": "function",
                                "function": {"name": item.get("name", ""), "arguments": item.get("arguments", "{}")},
                            }
                            for index, item in enumerate(tool_calls)
                        ],
                    })
                    allowed_names = {item["function"]["name"] for item in tools}
                    for index, call in enumerate(tool_calls):
                        name = str(call.get("name", ""))
                        call_id = str(call.get("id") or f"{phase}-{len(trace.tool_calls)}-{index}")
                        arguments_raw = call.get("arguments", "{}")
                        arguments: dict[str, Any] = {}
                        try:
                            arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else dict(arguments_raw)
                            if not isinstance(arguments, dict):
                                raise ValueError("arguments must be an object")
                            if name == CODE_EXECUTOR_NAME:
                                code = arguments.get("code")
                                if not isinstance(code, str):
                                    raise BatchCodeRejected("code executor requires a string 'code' argument")
                                output, records, ok = self._execute_batch_code(
                                    code=code,
                                    allowed_names=allowed_names - {CODE_EXECUTOR_NAME},
                                    phase=phase,
                                    trace=trace,
                                )
                                trace.tool_calls.extend(records)
                                self._emit_event("TOOL_CALL", phase=phase, name=CODE_EXECUTOR_NAME, count=len(records))
                                messages.append({"role": "tool", "tool_call_id": call_id, "content": output[:MAX_TOOL_OUTPUT_CHARS]})
                                continue
                            if name not in allowed_names:
                                self.ledger.safety_incidents += 1
                                raise PermissionError(f"tool is not allowed in {phase}: {name}")
                            if self._requires_session_safe_batch(name):
                                raise RuntimeError(
                                    f"SessionBatchRequired: {name} must be called with its login and dependent "
                                    "authenticated APIs in one metamorph__execute_code batch"
                                )
                            is_write = self._is_write(name)
                            self.ledger.before_tool_call(is_write=is_write)
                            output = str(self.world.execute(_safe_tool_code(name, arguments)))
                            self.ledger.after_tool_call()
                            ok = not output.startswith("Execution failed")
                            app, separator, api = name.partition("__")
                            if ok and separator and api == LOGIN_API:
                                self._direct_login_apps.add(app)
                            if not ok:
                                self.ledger.record_error(tool=True)
                        except (BudgetExhausted, PermissionError):
                            raise
                        except Exception as exc:  # keep tool failures visible to the model
                            output = f"Tool execution failed: {exc}"
                            ok = False
                            self.ledger.record_error(tool=True)
                        record = {"name": name, "arguments": arguments, "output": output, "success": ok}
                        trace.tool_calls.append(record)
                        self._emit_event("TOOL_CALL", phase=phase, name=name, success=ok)
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": output[:MAX_TOOL_OUTPUT_CHARS]})
                    continue

                if contract is None:
                    trace.answer = content
                    trace.status = "completed" if content.strip() else "failed_empty_output"
                    trace.latency_seconds = round(time.clock_gettime(time.CLOCK_MONOTONIC) - started, 6)
                    self._write_trace(trace)
                    self._emit_event("STAGE_END", phase=phase, status=trace.status)
                    return trace, content

                # A provider-private tool-call encoding in content is never
                # interpreted or executed.  It is retained as evidence for
                # finalization and made explicit in the immutable trace.
                if _contains_unstructured_tool_markup(content):
                    trace.provider_protocol_mismatches.append(
                        "provider_protocol_mismatch: unstructured DSML-like tool markup ended the tool phase"
                    )
                if content:
                    messages.append({"role": "assistant", "content": content})
                artifact = self._finalize_artifact(
                    phase=phase,
                    messages=messages,
                    contract=contract,
                    trace=trace,
                    allow_contract_retry=allow_contract_retry,
                )
                trace.latency_seconds = round(time.clock_gettime(time.CLOCK_MONOTONIC) - started, 6)
                self._write_trace(trace)
                self._emit_event("STAGE_END", phase=phase, status=trace.status)
                return trace, artifact
        except (BudgetExhausted, PermissionError) as exc:
            self.ledger.cancel_model_call()
            trace.status = "budget_stopped" if isinstance(exc, BudgetExhausted) else "permission_stopped"
            trace.contract_errors.append(str(exc))
            trace.latency_seconds = round(time.clock_gettime(time.CLOCK_MONOTONIC) - started, 6)
            self._write_trace(trace)
            self._emit_event("STAGE_END", phase=phase, status=trace.status)
            return trace, None
        except Exception as exc:
            self.ledger.cancel_model_call()
            trace.status = "failed"
            trace.contract_errors.append(f"{type(exc).__name__}: {exc}")
            trace.latency_seconds = round(time.clock_gettime(time.CLOCK_MONOTONIC) - started, 6)
            self._write_trace(trace)
            self._emit_event("STAGE_END", phase=phase, status=trace.status)
            raise

    def checkpoint(self, name: str) -> dict[str, Any]:
        state_id = self.world.save_state(name)
        checkpoint_root = Path(self.world.output_checkpoints_directory) / str(state_id or name)
        record = {
            "state_id": str(state_id or name),
            "state_hash": _hash_directory(checkpoint_root),
            "path": str(checkpoint_root),
            "budget": self.ledger.snapshot(),
        }
        self.checkpoints[name] = record
        return record

    def _planner(self, *, phase: str = "planner") -> PlannerArtifact | str | None:
        schema = _contract_instructions(PlannerArtifact) if self.json_contract else "Return a useful plain-text plan."
        prompt = (
            "You are the strategy planner in a fixed planner→executor→verifier scaffold. Do not call tools: "
            "the executor resolves task-specific entities and values from the environment. Do not perform "
            "requested mutations. Produce at most six high-level actions; describe repeated work as one loop or "
            "category, never as a per-item list. Use an unqualified API path in `api` (for example `login`) and "
            "its namespace in `app` (for example `file_system`). This artifact is a handoff, not an interaction log.\n\n"
            f"TASK:\n{self.world.task.instruction}\n\n{schema}"
        )
        trace, artifact = self._run_phase(
            phase,
            prompt,
            [],
            contract=PlannerArtifact if self.json_contract else None,
        )
        if isinstance(artifact, PlannerArtifact):
            # A planner handoff is intentionally strategic: it may say
            # "list directory" or describe a loop without committing to the
            # exact function name/arguments.  The executor resolves concrete
            # API calls and the controller audits them.  Rejecting such a
            # plan turns a useful causal handoff into a brittle API validator.
            # Exact API/argument allowlisting remains enforced at execution.
            pass
        return artifact

    def _dag_join(self, inputs: dict[str, Any], *, phase: str) -> PlannerArtifact | None:
        """Merge independent read-only inspections into one typed handoff."""

        serialized_inputs = {
            name: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
            for name, value in inputs.items()
        }

        prompt = (
            "You are a read-only DAG join node. Merge the two upstream inspection artifacts into one concise "
            "execution plan. Do not call tools, invent API results, or mutate state.\n\n"
            f"TASK:\n{self.world.task.instruction}\n\n"
            f"UPSTREAM INSPECTIONS:\n{canonical_json(serialized_inputs)}\n\n"
            + _contract_instructions(PlannerArtifact)
        )
        _, artifact = self._run_phase(phase, prompt, [], contract=PlannerArtifact)
        return artifact if isinstance(artifact, PlannerArtifact) else None

    def run_dag(
        self,
        spec: DAGSpec,
        *,
        intervention: Intervention | None = None,
        initial_artifacts: dict[str, Any] | None = None,
        selected_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a task-internal DAG while keeping the controller plane fixed.

        The DAG runtime writes a checkpoint after each completed node.  Its
        callback is the only bridge to model/tool execution, which lets the
        same compiler and intervention semantics be exercised in no-model P0
        tests and in AppWorld runs.
        """

        self.checkpoint("initial")
        if selected_tools is None:
            self.select_tools()
        else:
            # Replay reuses the baseline's frozen tool surface.  Selecting
            # again would add a new model call and invalidate a downstream-only
            # intervention.
            self.selected_tool_names = list(selected_tools)

        def run_node(node: DAGNode, inputs: dict[str, Any]) -> Any:
            phase = f"dag_{node.id}"
            if node.operator == "inspect":
                return self._planner(phase=phase)
            if node.operator == "join":
                return self._dag_join(inputs, phase=phase)
            if node.operator == "act":
                return self._executor(inputs.get("plan"), phase=phase)
            if node.operator == "check":
                return self._verifier(inputs.get("execution"), phase=phase)
            if node.operator == "repair":
                return self._executor(inputs.get("verification"), phase=phase)
            raise ValueError(f"unsupported DAG operator: {node.operator}")

        execution = DAGExecutor(runner=run_node, checkpoint=self.checkpoint).execute(
            spec, intervention, initial_artifacts=initial_artifacts
        )
        self.checkpoint("final")

        phase_statuses = {name: trace.status for name, trace in self.traces.items()}
        invalid_phases = sorted(name for name, status in phase_statuses.items() if status != "completed")
        # A replay correctly has no new tool-selector phase; ordinary runs
        # must have a completed selector trace as part of the fixed controller
        # plane.
        if selected_tools is None and "tool_selector" not in phase_statuses:
            invalid_phases.append("tool_selector:missing")
        protocol_valid = bool(execution["protocol_valid"]) and not invalid_phases
        protocol_reasons = [*execution["protocol_invalid_reasons"], *[f"phase {name} not completed" for name in invalid_phases]]

        def json_value(value: Any) -> Any:
            if isinstance(value, BaseModel):
                return value.model_dump(mode="json")
            if isinstance(value, dict):
                return {name: json_value(item) for name, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [json_value(item) for item in value]
            return value

        final_answer = ""
        for node_id in ("repair", "act"):
            value = execution["artifacts"].get(node_id)
            if isinstance(value, ExecutorArtifact) and value.final_answer is not None:
                final_answer = str(value.final_answer)
                break
        return {
            "answer": final_answer,
            "dag_execution": json_value(execution),
            "artifacts": {
                node_id: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
                for node_id, value in execution["artifacts"].items()
            },
            "artifact_hashes": execution["artifact_hashes"],
            "protocol_valid": protocol_valid,
            "protocol_invalid_reasons": protocol_reasons,
            "phase_statuses": phase_statuses,
        }

    def _executor(self, plan: PlannerArtifact | str | dict[str, Any] | None, *, phase: str = "executor") -> ExecutorArtifact | None:
        plan_text = canonical_json(plan) if isinstance(plan, BaseModel) else str(plan or "")
        prompt = (
            f"You are the {phase} in a fixed AppWorld scaffold. Execute the task using only allowed APIs. "
            "Follow the validated upstream plan when available; do not claim an action that was not observed. "
            "If this is a repair, apply only the minimum corrections. Complete the active task through the "
            "supervisor API when appropriate. For repeated or bulk API work, use the constrained code-batch "
            "tool with a loop; the controller records every individual API invocation in the immutable trace. "
            "If you mention the synthetic metamorph__execute_code tool in executed_actions, do so only when "
            "you actually invoked it; its expanded API calls remain the authoritative action audit. "
            "For any app exposing a login API, you must call login and every dependent authenticated API in the "
            "same metamorph__execute_code batch; direct function calls for such apps are rejected because they lose "
            "their session context. Never invent, reuse, or transform credentials. "
            "In the final JSON artifact, summarize only the material actions and state changes needed for the "
            "downstream verifier; do not try to duplicate the complete audit log.\n\n"
            f"TASK:\n{self.world.task.instruction}\n\nUPSTREAM ARTIFACT:\n{plan_text}\n\n"
            + _contract_instructions(ExecutorArtifact)
        )
        trace, artifact = self._run_phase(
            phase,
            prompt,
            self._tools(self.selected_tool_names, read_only=False),
            contract=ExecutorArtifact,
        )
        if isinstance(artifact, ExecutorArtifact):
            observed_names = {item["name"] for item in trace.tool_calls if item["success"]}
            # A constrained code batch is a real model tool call, but its trace
            # deliberately expands into individual AppWorld APIs.  Treat the
            # synthetic wrapper as observed only when a recorded batch exists.
            if trace.code_batches:
                observed_names.add(CODE_EXECUTOR_NAME)
            claimed_names = {
                _artifact_action_name(item.app, item.api)
                for item in artifact.executed_actions
                if item.success
            }
            unsupported_claims = sorted(claimed_names - observed_names)
            if unsupported_claims:
                trace.status = "invalid_contract"
                trace.contract_errors.append(f"artifact claims unobserved API names: {unsupported_claims}")
                self.ledger.record_error(contract=True)
                self._write_trace(trace)
                return None
        return artifact if isinstance(artifact, ExecutorArtifact) else None

    def _verifier(self, executor: Any, *, phase: str = "verifier") -> VerifierArtifact | None:
        executor_text = canonical_json(executor) if isinstance(executor, BaseModel) else str(executor or "")
        prompt = (
            "You are the read-only verifier in a fixed AppWorld scaffold. Inspect actual state with read APIs. "
            "Verify the original task directly; do not mutate or complete it. If any criterion is not met, "
            "return concrete minimal repair instructions. For repeated inspection, use the constrained code-batch "
            "tool with only read APIs.\n\n"
            f"TASK:\n{self.world.task.instruction}\n\nEXECUTOR ARTIFACT:\n{executor_text}\n\n"
            + _contract_instructions(VerifierArtifact)
        )
        _, artifact = self._run_phase(
            phase,
            prompt,
            self._tools(self.selected_tool_names, read_only=True),
            contract=VerifierArtifact,
        )
        return artifact if isinstance(artifact, VerifierArtifact) else None

    def run_fixed_s3(self, *, exclude_planner: bool = False) -> dict[str, Any]:
        self.checkpoint("initial")
        self.select_tools()
        planner: PlannerArtifact | str | dict[str, Any] | None
        if exclude_planner:
            planner = typed_null("planner", "executor", "PlannerArtifact").model_dump(mode="json")
        else:
            planner = self._planner()
        self.checkpoint("pre_executor")
        executor = self._executor(planner)
        self.checkpoint("post_executor")
        verifier: VerifierArtifact | None = None
        repair: ExecutorArtifact | None = None
        final_verifier: VerifierArtifact | None = None
        if self.enable_verifier:
            verifier = self._verifier(executor)
            if verifier is not None and verifier.status == "NOT_VERIFIED" and self.enable_repair:
                repair = self._executor(verifier, phase="repair")
                final_verifier = self._verifier(repair, phase="verifier_after_repair")
        self.checkpoint("final")
        final_answer = ""
        for artifact in (repair, executor):
            if artifact is not None and artifact.final_answer is not None:
                final_answer = str(artifact.final_answer)
                break
        return {
            "answer": final_answer,
            "artifacts": {
                "planner": planner.model_dump(mode="json") if isinstance(planner, BaseModel) else planner,
                "executor": executor.model_dump(mode="json") if executor else None,
                "verifier": verifier.model_dump(mode="json") if verifier else None,
                "repair": repair.model_dump(mode="json") if repair else None,
                "verifier_after_repair": final_verifier.model_dump(mode="json") if final_verifier else None,
            },
            "artifact_hashes": {
                name: artifact_hash(value) for name, value in {
                    "planner": planner.model_dump(mode="json") if isinstance(planner, BaseModel) else str(planner),
                    "executor": executor.model_dump(mode="json") if executor else "",
                    "verifier": verifier.model_dump(mode="json") if verifier else "",
                }.items()
            },
        }

    def replay_masked_edge(
        self,
        *,
        edge: tuple[str, str],
        baseline_artifacts: dict[str, Any],
        selected_tools: list[str],
        artifact_policy: str = "typed_null",
    ) -> dict[str, Any]:
        """Replay exactly the downstream stages after the caller restores a checkpoint."""

        self.selected_tool_names = list(selected_tools)
        planner_value = baseline_artifacts.get("planner")
        executor_value = baseline_artifacts.get("executor")
        if artifact_policy not in {"typed_null", "passthrough"}:
            raise ValueError(f"unsupported artifact policy: {artifact_policy}")
        if edge == ("planner", "executor"):
            input_artifact = (
                typed_null("planner", "executor", "PlannerArtifact").model_dump(mode="json")
                if artifact_policy == "typed_null"
                else planner_value
            )
            executor = self._executor(input_artifact, phase="replay_executor")
            self.checkpoint("post_replay_executor")
            verifier = self._verifier(executor, phase="replay_verifier") if self.enable_verifier else None
            repair = None
            if verifier is not None and verifier.status == "NOT_VERIFIED" and self.enable_repair:
                repair = self._executor(verifier, phase="replay_repair")
                self._verifier(repair, phase="replay_verifier_after_repair")
            artifacts = {"planner": input_artifact, "executor": executor.model_dump(mode="json") if executor else None, "verifier": verifier.model_dump(mode="json") if verifier else None}
        elif edge == ("executor", "verifier"):
            input_artifact = (
                typed_null("executor", "verifier", "ExecutorArtifact").model_dump(mode="json")
                if artifact_policy == "typed_null"
                else executor_value
            )
            verifier = self._verifier(input_artifact, phase="replay_verifier") if self.enable_verifier else None
            repair = None
            if verifier is not None and verifier.status == "NOT_VERIFIED" and self.enable_repair:
                repair = self._executor(verifier, phase="replay_repair")
                self._verifier(repair, phase="replay_verifier_after_repair")
            artifacts = {"planner": planner_value, "executor": input_artifact, "verifier": verifier.model_dump(mode="json") if verifier else None}
        else:
            raise ValueError(f"unsupported pre-registered edge: {edge}")
        self.checkpoint("final")
        return {
            "masked_edge": list(edge),
            "artifact_policy": artifact_policy,
            "typed_null_used": artifact_policy == "typed_null",
            "artifacts": artifacts,
            "artifact_hashes": {name: artifact_hash(value or "") for name, value in artifacts.items()},
        }

    def audit_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "model": self.model.model_name,
            "budget": self.ledger.snapshot(),
            "selected_tools": list(self.selected_tool_names),
            "selected_tool_schema_hash": artifact_hash([
                *[
                    self._function_by_name[name]
                    for name in self.selected_tool_names
                    if name in self._function_by_name
                ],
                code_executor_schema(
                    allowed_names=[
                        name for name in self.selected_tool_names if name in self._function_by_name
                    ],
                    read_only=False,
                ),
            ]),
            "phases": {name: trace.to_dict() for name, trace in self.traces.items()},
            "checkpoints": dict(self.checkpoints),
        }


def official_metrics(world: Any) -> dict[str, Any]:
    tracker = world.evaluate(suppress_errors=True)
    details = tracker.to_dict(stats_only=False)
    num_tests = int(details.get("num_tests", 0) or 0)
    pass_count = len(details.get("passes", []))
    return {
        "strict_success": bool(details.get("success", False)),
        "official_reward": 1.0 if details.get("success", False) else 0.0,
        "requirement_pass_fraction": round(pass_count / num_tests, 6) if num_tests else 0.0,
        "individual_evaluation": details,
    }
