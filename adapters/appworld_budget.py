"""One per-task budget ledger shared by all AppWorld scaffold phases."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from threading import RLock, get_ident
from typing import Any


class BudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetLimits:
    max_steps: int
    max_errors: int
    max_total_tokens: int
    max_tool_calls: int
    max_latency_seconds: float
    allow_write: bool
    enforce: bool = True
    emergency_multiplier: float = 2.0


class AppWorldBudgetLedger:
    """Enforce aggregate limits before every paid call or environment action."""

    def __init__(self, limits: BudgetLimits, initial_usage: dict[str, Any] | None = None) -> None:
        self.limits = limits
        # AppWorld freezes time.time/perf_counter/monotonic via freezegun to
        # simulate the task date. clock_gettime remains a real OS wall clock.
        self.started = time.clock_gettime(time.CLOCK_MONOTONIC)
        initial_usage = initial_usage or {}
        self.initial_latency_seconds = float(initial_usage.get("latency_seconds", 0.0) or 0.0)
        self.steps = int(initial_usage.get("steps", 0) or 0)
        self.errors = int(initial_usage.get("errors", 0) or 0)
        self.input_tokens = int(initial_usage.get("input_tokens", 0) or 0)
        self.output_tokens = int(initial_usage.get("output_tokens", 0) or 0)
        self.tool_calls = int(initial_usage.get("tool_calls", 0) or 0)
        self.write_actions = int(initial_usage.get("write_actions", 0) or 0)
        self.safety_incidents = int(initial_usage.get("safety_incidents", 0) or 0)
        self.tool_errors = int(initial_usage.get("tool_errors", 0) or 0)
        self.json_contract_violations = int(initial_usage.get("json_contract_violations", 0) or 0)
        self.missing_token_usage_calls = int(initial_usage.get("missing_token_usage_calls", 0) or 0)
        self.violations: list[str] = []
        self.termination_reason: str | None = None
        # G2 may issue independent read-only model requests concurrently.
        # All budget mutation remains one shared, atomic ledger.
        self._lock = RLock()
        self._model_reservations: dict[int, int] = {}

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def elapsed(self) -> float:
        return self.initial_latency_seconds + time.clock_gettime(time.CLOCK_MONOTONIC) - self.started

    def _limits(self) -> list[tuple[str, float, float]]:
        return [
            ("max_steps", self.steps, self.limits.max_steps),
            ("max_errors", self.errors, self.limits.max_errors),
            ("max_total_tokens", self.total_tokens, self.limits.max_total_tokens),
            ("max_tool_calls", self.tool_calls, self.limits.max_tool_calls),
            ("max_latency_seconds", self.elapsed, self.limits.max_latency_seconds),
        ]

    def _check(self, name: str, proposed: float, limit: float) -> None:
        effective = limit if self.limits.enforce else limit * self.limits.emergency_multiplier
        if proposed <= effective:
            if not self.limits.enforce and proposed > limit and name not in self.violations:
                self.violations.append(name)
            return
        self.termination_reason = f"budget exhausted: {name}"
        raise BudgetExhausted(self.termination_reason)

    def before_model_call(
        self,
        estimated_input_tokens: int,
        max_output_tokens: int,
        *,
        reserved_downstream_tokens: int = 0,
    ) -> None:
        with self._lock:
            thread_id = get_ident()
            if thread_id in self._model_reservations:
                raise RuntimeError("model token reservation already exists for this thread")
            reservation = max(0, estimated_input_tokens) + max(1, max_output_tokens)
            downstream = max(0, reserved_downstream_tokens)
            self._check("max_steps", self.steps + 1, self.limits.max_steps)
            self._check(
                "max_total_tokens",
                self.total_tokens + sum(self._model_reservations.values()) + reservation + downstream,
                self.limits.max_total_tokens,
            )
            self._check("max_latency_seconds", self.elapsed, self.limits.max_latency_seconds)
            self.steps += 1
            self._model_reservations[thread_id] = reservation

    def record_model_call(self, usage: dict[str, Any]) -> None:
        with self._lock:
            self._model_reservations.pop(get_ident(), None)
            prompt = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            completion = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
            total = int(usage.get("total_tokens", 0) or 0)
            if total and not prompt and not completion:
                prompt = total
            self.input_tokens += max(0, prompt)
            self.output_tokens += max(0, completion)
            # Provider token accounting is authoritative and can be slightly larger
            # than the pre-call estimate. Stop immediately instead of allowing an
            # over-budget response to be recorded as a completed phase.
            self._check(
                "max_total_tokens", self.total_tokens + sum(self._model_reservations.values()), self.limits.max_total_tokens
            )
            self._check("max_latency_seconds", self.elapsed, self.limits.max_latency_seconds)

    def cancel_model_call(self) -> None:
        """Release a pre-call reservation when the provider raises before usage exists."""

        with self._lock:
            self._model_reservations.pop(get_ident(), None)

    def before_tool_call(self, *, is_write: bool) -> None:
        with self._lock:
            self._check("max_tool_calls", self.tool_calls + 1, self.limits.max_tool_calls)
            self._check("max_latency_seconds", self.elapsed, self.limits.max_latency_seconds)
            if is_write and not self.limits.allow_write:
                self.safety_incidents += 1
                raise PermissionError("write action rejected by allow_write=false")
            self.tool_calls += 1
            if is_write:
                self.write_actions += 1

    def remaining_tool_calls(self) -> int:
        """Return the still-admissible API calls, including a soft-gate buffer."""

        with self._lock:
            effective = self.limits.max_tool_calls
            if not self.limits.enforce:
                effective = int(self.limits.max_tool_calls * self.limits.emergency_multiplier)
            return max(0, effective - self.tool_calls)

    def ensure_tool_capacity(self, count: int) -> None:
        """Check capacity without recording a call (used before a code batch)."""

        with self._lock:
            self._check("max_tool_calls", self.tool_calls + max(0, count), self.limits.max_tool_calls)

    def after_tool_call(self) -> None:
        """Catch latency exhaustion caused by the tool call itself."""

        with self._lock:
            self._check("max_latency_seconds", self.elapsed, self.limits.max_latency_seconds)

    def record_error(self, *, tool: bool = False, contract: bool = False) -> None:
        with self._lock:
            self._check("max_errors", self.errors + 1, self.limits.max_errors)
            self.errors += 1
            if tool:
                self.tool_errors += 1
            if contract:
                self.json_contract_violations += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            exhausted = self.termination_reason is not None
            return {
                "limits": asdict(self.limits),
                "steps": self.steps,
                "errors": self.errors,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "tool_calls": self.tool_calls,
                "write_actions": self.write_actions,
                "safety_incidents": self.safety_incidents,
                "tool_errors": self.tool_errors,
                "json_contract_violations": self.json_contract_violations,
                "missing_token_usage_calls": self.missing_token_usage_calls,
                "latency_seconds": round(self.elapsed, 6),
                "budget_exhausted": exhausted,
                "termination_reason": self.termination_reason,
                "violations": list(dict.fromkeys(self.violations)),
            }
