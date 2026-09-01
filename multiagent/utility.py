"""Budget accounting and a replaceable net-utility interface."""

from __future__ import annotations

import threading
from typing import Any

from .models import AgentResult, ArchitecturePlan, BudgetPolicy, UtilityBreakdown


class BudgetLedger:
    """Thread-safe token reservations made before a DAG node is scheduled."""

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.spent = 0
        self.reserved = 0
        self._reservations: dict[str, int] = {}
        self._lock = threading.Lock()

    def reserve(self, reservation_id: str, estimated_tokens: int) -> bool:
        estimate = max(1, int(estimated_tokens))
        with self._lock:
            if self.limit is not None and self.spent + self.reserved + estimate > self.limit:
                return False
            self._reservations[reservation_id] = estimate
            self.reserved += estimate
            return True

    def settle(self, reservation_id: str, actual_tokens: int) -> None:
        with self._lock:
            reserved = self._reservations.pop(reservation_id, 0)
            self.reserved -= reserved
            self.spent += max(0, int(actual_tokens))

    def snapshot(self) -> dict[str, int | None]:
        with self._lock:
            return {"limit": self.limit, "spent": self.spent, "reserved": self.reserved, "remaining": None if self.limit is None else max(0, self.limit - self.spent - self.reserved)}


def aggregate_metrics(
    plan: ArchitecturePlan,
    results: list[AgentResult],
    fallback_latency: float = 0.0,
) -> dict[str, Any]:
    """Measure resource use; latency is the DAG critical path, not summed work."""

    by_id = {item.agent_id: item for item in results}
    role_by_id = {role.agent_id: role for role in plan.roles}
    critical: dict[str, float] = {}

    def path_latency(agent_id: str, visiting: set[str] | None = None) -> float:
        if agent_id in critical:
            return critical[agent_id]
        visiting = visiting or set()
        if agent_id in visiting:
            # Invalid cycles are rejected by the compiler; keep this helper
            # total so diagnostics can still be produced for an uncompiled plan.
            return 0.0
        visiting.add(agent_id)
        role = role_by_id.get(agent_id)
        result = by_id.get(agent_id)
        duration = float((result.metrics if result else {}).get("latency_seconds", 0.0) or 0.0)
        dependency_time = max(
            (path_latency(dep, visiting.copy()) for dep in (role.dependencies if role else [])),
            default=0.0,
        )
        critical[agent_id] = dependency_time + duration
        return critical[agent_id]

    for role in plan.roles:
        path_latency(role.agent_id)
    path_latency = max(critical.values(), default=0.0)
    if path_latency <= 0.0:
        path_latency = max(0.0, fallback_latency)
    return {
        "token_cost": sum(int((item.metrics or {}).get("total_tokens", 0) or 0) for item in results),
        "critical_path_latency": round(path_latency, 6),
        "tool_calls": sum(int((item.metrics or {}).get("tool_calls", 0) or 0) for item in results),
        "safety_incidents": sum(int((item.metrics or {}).get("safety_incidents", 0) or 0) for item in results),
        "regression_risk": sum(float((item.metrics or {}).get("regression_risk", 0.0) or 0.0) for item in results),
    }


def score_utility(quality: float, metrics: dict[str, Any], policy: BudgetPolicy) -> UtilityBreakdown:
    """Compute an inspectable utility; weights are intentionally configurable."""

    token_cost = int(metrics.get("token_cost", 0) or 0)
    latency = float(metrics.get("critical_path_latency", 0.0) or 0.0)
    tool_calls = int(metrics.get("tool_calls", 0) or 0)
    safety = int(metrics.get("safety_incidents", 0) or 0)
    regression = float(metrics.get("regression_risk", 0.0) or 0.0)
    value = (
        float(quality)
        - policy.token_weight * token_cost
        - policy.latency_weight * latency
        - policy.tool_weight * tool_calls
        - policy.safety_weight * safety
        - policy.regression_weight * regression
    )
    return UtilityBreakdown(
        quality=round(float(quality), 6),
        token_cost=token_cost,
        critical_path_latency=round(latency, 6),
        tool_calls=tool_calls,
        safety_incidents=safety,
        regression_risk=round(regression, 6),
        value=round(value, 6),
    )


def budget_allows(metrics: dict[str, Any], policy: BudgetPolicy) -> tuple[bool, list[str]]:
    """Hard budget gate used before paying for another intervention."""

    reasons: list[str] = []
    if policy.max_total_tokens is not None and int(metrics.get("token_cost", 0) or 0) >= policy.max_total_tokens:
        reasons.append("token budget exhausted")
    if policy.max_latency_seconds is not None and float(metrics.get("critical_path_latency", 0.0) or 0.0) >= policy.max_latency_seconds:
        reasons.append("latency budget exhausted")
    if policy.max_tool_calls is not None and int(metrics.get("tool_calls", 0) or 0) >= policy.max_tool_calls:
        reasons.append("tool-call budget exhausted")
    return not reasons, reasons
