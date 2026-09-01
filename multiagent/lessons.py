"""Versioned, causally evidenced lesson storage.

The store is append-only so every admission and state transition remains
auditable. It deliberately does not turn ordinary task summaries into durable
lessons: long-term memory is reserved for controlled causal evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LessonStore:
    """Append-only JSONL ledger for Candidate, Active, and Disabled lessons."""

    def __init__(self, data_dir: Path, min_validations: int = 2) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "multiagent_lessons.jsonl"
        self.min_validations = max(1, min_validations)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _fingerprint(condition: dict[str, Any], dag_edit: dict[str, Any]) -> str:
        payload = json.dumps({"condition": condition, "dag_edit": dag_edit}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    def _append_snapshot(self, lesson: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(lesson, ensure_ascii=False, sort_keys=True) + "\n")

    def all(self) -> list[dict[str, Any]]:
        """Return the latest snapshot of every current lesson, oldest first."""

        if not self.path.exists():
            return []
        latest: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            lesson_id = str(record.get("lesson_id") or "")
            if not lesson_id:
                # Ignore pre-causal v0 lesson summaries rather than promoting
                # them without evidence.
                continue
            if lesson_id not in latest:
                order.append(lesson_id)
            latest[lesson_id] = record
        return [latest[lesson_id] for lesson_id in order]

    def recent(self, limit: int = 8) -> list[dict[str, Any]]:
        return self.all()[-limit:]

    def select_active(self, context: dict[str, Any], limit: int = 3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return compatible Active lessons and explicit drift rejections."""

        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for lesson in self.all():
            if lesson.get("status") != "Active":
                continue
            condition = lesson.get("condition") or {}
            mismatches = [
                key for key in ("task_kind", "strategy", "tool_intensity")
                if condition.get(key) and context.get(key) and condition[key] != context[key]
            ]
            if mismatches:
                rejected.append({"lesson_id": lesson["lesson_id"], "reason": "distribution drift", "mismatches": mismatches})
                continue
            selected.append(lesson)
        selected.sort(key=lambda item: (float(item.get("strength", 0.0)), int(item.get("validation_count", 0))), reverse=True)
        return selected[:limit], rejected

    def admit_causal_evidence(
        self,
        *,
        condition: dict[str, Any],
        dag_edit: dict[str, Any],
        evidence: dict[str, Any],
        source_run: str | None,
        artifact_contracts: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or strengthen a lesson after a fixed-context intervention.

        A lesson becomes Active only after independent source runs agree on a
        positive lower-bound effect. Negative evidence disables it immediately.
        """

        fingerprint = self._fingerprint(condition, dag_edit)
        existing = next((item for item in self.all() if item.get("fingerprint") == fingerprint), None)
        effect = float(evidence.get("utility_delta", 0.0) or 0.0)
        lower_bound = float(evidence.get("utility_lower_bound", 0.0) or 0.0)
        drift = bool(evidence.get("drift_detected", False))
        if existing is None:
            lesson_id = f"lesson-{fingerprint}"
            existing = {
                "lesson_id": lesson_id,
                "fingerprint": fingerprint,
                "created_at": self._now(),
                "condition": condition,
                "dag_edit": dag_edit,
                "artifact_contracts": artifact_contracts,
                "status": "Candidate",
                "strength": 0.0,
                "validation_count": 0,
                "evidence": [],
                "negative_transfer_count": 0,
            }

        lesson = dict(existing)
        observations = list(lesson.get("evidence") or [])
        if source_run and any(item.get("source_run") == source_run for item in observations):
            return lesson
        observations.append({
            "source_run": source_run,
            "recorded_at": self._now(),
            "utility_delta": round(effect, 6),
            "utility_lower_bound": round(lower_bound, 6),
            "drift_detected": drift,
            "baseline": evidence.get("baseline"),
            "intervention": evidence.get("intervention"),
        })
        lesson["evidence"] = observations
        lesson["validation_count"] = len(observations)
        if drift or lower_bound <= 0.0:
            lesson["negative_transfer_count"] = int(lesson.get("negative_transfer_count", 0)) + 1
            lesson["strength"] = round(max(0.0, float(lesson.get("strength", 0.0)) * 0.5), 6)
            if drift or lesson["negative_transfer_count"] >= 2:
                lesson["status"] = "Disabled"
        else:
            mean_effect = sum(float(item.get("utility_delta", 0.0)) for item in observations) / len(observations)
            min_lcb = min(float(item.get("utility_lower_bound", 0.0)) for item in observations)
            lesson["strength"] = round(min(1.0, 0.25 * len(observations) + 0.5 * max(0.0, mean_effect)), 6)
            if len(observations) >= self.min_validations and min_lcb > 0.0:
                lesson["status"] = "Active"
        lesson["updated_at"] = self._now()
        self._append_snapshot(lesson)
        return lesson

    def disable(self, lesson_id: str, reason: str) -> dict[str, Any] | None:
        """Explicitly revoke a lesson that becomes unsafe or stale."""

        lesson = next((item for item in self.all() if item.get("lesson_id") == lesson_id), None)
        if lesson is None:
            return None
        lesson = dict(lesson)
        lesson["status"] = "Disabled"
        lesson["disabled_reason"] = reason
        lesson["updated_at"] = self._now()
        self._append_snapshot(lesson)
        return lesson
