"""Append-only records and pre-reservation accounting for E0."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthorizationError(RuntimeError):
    pass


class BudgetError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveAuthorization:
    authorized: bool
    provider: str | None = None
    exact_model_id: str | None = None
    currency: str | None = None
    hard_cap: Decimal | None = None
    max_requests: int | None = None
    price_basis: str | None = None

    def validate(self) -> None:
        if not self.authorized:
            raise AuthorizationError("live smoke is not authorized")
        if not all((self.provider, self.exact_model_id, self.currency, self.price_basis)):
            raise AuthorizationError("provider, model, currency, and price basis must be confirmed")
        if self.hard_cap is None or self.hard_cap <= 0 or self.max_requests is None or self.max_requests < 1:
            raise AuthorizationError("a positive hard cap and request limit are required")
        if self.max_requests > 3:
            raise AuthorizationError("Day-1 live smoke permits at most three complete task episodes")


class CostLedger:
    """Reserves worst-case spend before a call and retains unknown charges."""

    def __init__(self, authorization: LiveAuthorization):
        self.authorization = authorization
        self.entries: list[dict[str, Any]] = []
        self.reserved = Decimal("0")
        self.settled = Decimal("0")
        self.billing_unknown = False

    def reserve(self, estimated_worst_case: Decimal) -> str:
        self.authorization.validate()
        if self.billing_unknown:
            raise BudgetError("billing is unknown; later live calls are paused")
        if len(self.entries) >= (self.authorization.max_requests or 0):
            raise BudgetError("request limit reached")
        if estimated_worst_case < 0 or self.reserved + estimated_worst_case > self.authorization.hard_cap:  # type: ignore[operator]
            raise BudgetError("hard cap would be exceeded")
        entry_id = uuid.uuid4().hex
        self.reserved += estimated_worst_case
        self.entries.append({"id": entry_id, "status": "reserved", "reserved": str(estimated_worst_case)})
        return entry_id

    def settle(self, entry_id: str, actual: Decimal | None, usage: dict[str, Any] | None) -> None:
        entry = next(item for item in self.entries if item["id"] == entry_id)
        entry["usage"] = usage
        if actual is None:
            entry.update({"status": "billing_unknown", "actual": None})
            self.billing_unknown = True
            return
        entry.update({"status": "settled", "actual": str(actual)})
        self.settled += actual


class RunRecords:
    """Runner-only JSONL event log. It never becomes an agent mount."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.jsonl"

    def emit(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {"timestamp": utc_now(), "type": event_type, **payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def write_json(self, name: str, payload: Any) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path


def record_attempt(
    *,
    attempt_id: str,
    condition: str,
    task_id: str,
    error_kind: str | None = None,
    task_correct: bool | None = None,
) -> dict[str, Any]:
    """Keep task, protocol, and infrastructure status distinct."""
    categories = {None, "empty_artifact", "task_error", "protocol_error", "infrastructure_error", "timeout"}
    if error_kind not in categories:
        raise ValueError(f"unknown error kind: {error_kind}")
    return {
        "attempt_id": attempt_id,
        "condition": condition,
        "task_id": task_id,
        "task_correct": task_correct,
        "artifact_status": "empty" if error_kind == "empty_artifact" else "unknown",
        "protocol_status": "failed" if error_kind == "protocol_error" else "unknown",
        "infra_status": "failed" if error_kind in {"infrastructure_error", "timeout"} else "unknown",
        "error_kind": error_kind,
    }
