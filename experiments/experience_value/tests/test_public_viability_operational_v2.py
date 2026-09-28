"""Operational-wrapper tests: every transport here is fake and sends no network request."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import httpx

from experiments.experience_value.public_viability_gate_run import _code_hashes, execute
from experiments.experience_value.tests.test_public_viability_gate_run import GateFakeAdapter, NoWriteGateAdapter
from llm.adapters import ProviderAdapter


ROOT = Path(__file__).resolve().parents[3]
PENDING = ROOT / "experiments/experience_value/public_viability_gate.operational_v2.pending.json"
AUTH = ROOT / "experiments/experience_value/public_viability_gate.operational_v2.authorization.pending.json"


def _bind(pending: Path, authorization: Path) -> None:
    payload = json.loads(authorization.read_text())
    payload["frozen_pending_config"]["sha256"] = hashlib.sha256(pending.read_bytes()).hexdigest()
    payload["entry_code"]["sha256"] = hashlib.sha256((ROOT / "experiments/experience_value/public_viability_gate_run.py").read_bytes()).hexdigest()
    payload["code_dependencies"] = _code_hashes()
    payload["status"] = "AUTHORIZED_PUBLIC_VIABILITY_GATE_OPERATIONAL_V2"
    payload["live_requests_authorized"] = True
    payload["real_model_requests_sent_under_this_authorization"] = 0
    authorization.write_text(json.dumps(payload))


def _window(*_args, **_kwargs):
    return {"request_allowed": True, "new_episode_allowed": True, "reason": "test_window", "local_time": "2026-09-26T20:00:00+08:00", "utc_offset": "+0800"}


class AlwaysTimeout(ProviderAdapter):
    def stream(self, **_kwargs):
        raise TypeError()

    def complete_configured(self, **_kwargs):
        raise httpx.ReadTimeout("offline test")


class FlakyThenGate(GateFakeAdapter):
    def __init__(self):
        super().__init__()
        self.failed = False

    def complete_configured(self, **kwargs):
        if not self.failed:
            self.failed = True
            raise httpx.ReadTimeout("first fake transport failure")
        return super().complete_configured(**kwargs)


class OperationalV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pending, self.auth = self.root / "pending.json", self.root / "auth.json"
        shutil.copyfile(PENDING, self.pending)
        shutil.copyfile(AUTH, self.auth)
        _bind(self.pending, self.auth)

    def tearDown(self):
        self.tmp.cleanup()

    def test_predispatch_window_preflight_and_shim_rejections_do_not_consume(self):
        outside = lambda *_a, **_k: {"request_allowed": False, "new_episode_allowed": False, "reason": "outside", "local_time": "x", "utc_offset": "+0800"}
        for label, kwargs, expected in (
            ("outside", {"offpeak_check": outside}, "WAITING_OFFPEAK"),
            ("preflight", {"offpeak_check": _window, "preflight_check": lambda: {"ok": False, "exception_chain": []}}, "PRECHECK_FAILED"),
            ("shim", {"offpeak_check": _window, "preflight_check": lambda: {"ok": True}, "shim_check": lambda: (_ for _ in ()).throw(RuntimeError("shim"))}, "INVALID_SYSTEM"),
        ):
            path = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / label, mode="live", report_path=self.root / f"{label}.md", **kwargs)
            self.assertIn(expected, path.read_text())
            self.assertEqual(json.loads(self.auth.read_text())["real_model_requests_sent_under_this_authorization"], 0)

    def test_all_attempts_and_consolidation_recheck_window_and_go_is_unchanged(self):
        checks = []
        def checked(*args, **kwargs):
            checks.append((args, kwargs))
            return _window()
        result = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "go", mode="live", adapter=GateFakeAdapter(), offpeak_check=checked, preflight_check=lambda: {"ok": True}, shim_check=lambda: "real", report_path=self.root / "go.md")
        report = json.loads(result.read_text())
        self.assertEqual(report["status"], "COMPLETED_GO")
        self.assertEqual(report["gate_outcome"], "GO")
        self.assertGreater(len(checks), report["provider_attempts"])  # startup/new-episode checks plus every request including consolidation
        self.assertEqual(json.loads(self.auth.read_text())["real_model_requests_sent_under_this_authorization"], 1)

    def test_second_transport_failure_stops_batch_and_marks_remaining_not_run(self):
        result = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "infra", mode="live", adapter=AlwaysTimeout(), offpeak_check=_window, preflight_check=lambda: {"ok": True}, shim_check=lambda: "real", report_path=self.root / "infra.md")
        report = json.loads(result.read_text())
        self.assertEqual(report["status"], "INVALID_INFRA")
        self.assertEqual(report["episodes"][0]["analysis_status"], "INVALID_INFRA")
        self.assertFalse(report["episodes"][1]["started"])
        self.assertEqual(report["episodes"][1]["not_run_reason"], "INVALID_INFRA")
        self.assertEqual(report["provider_attempts"], 2)

    def test_retry_rechecks_time_and_completed_no_go_has_the_same_report_shape(self):
        checks = []
        def checked(*args, **kwargs):
            checks.append(1)
            return _window()
        retry = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "retry", mode="live", adapter=FlakyThenGate(), offpeak_check=checked, preflight_check=lambda: {"ok": True}, shim_check=lambda: "real", report_path=self.root / "retry.md")
        retried = json.loads(retry.read_text())
        self.assertTrue(any(row["transport_retries"] == 1 for row in retried["episodes"]))
        self.assertGreater(len(checks), retried["provider_attempts"])
        # Fresh unsigned-equivalent test authorization: optional non-write is a
        # legal path and must yield a complete NO_GO report, not a crash.
        _bind(self.pending, self.auth)
        no_go = execute(pending_path=self.pending, authorization_path=self.auth, output_root=self.root / "no-go", mode="live", adapter=NoWriteGateAdapter(), offpeak_check=_window, preflight_check=lambda: {"ok": True}, shim_check=lambda: "real", report_path=self.root / "no-go.md")
        no_go_report = json.loads(no_go.read_text())
        self.assertEqual(no_go_report["status"], "COMPLETED_NO_GO")
        self.assertEqual(no_go_report["gate_outcome"], "NO_GO_FOR_EXPERIENCE_TRANSFER")
