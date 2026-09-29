"""Offline-only live-entry acceptance; no public task data is loaded."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from llm.adapters import AdapterResponse, ProviderAdapter

from experiments.experience_value import formal_receiver_run as v1
from experiments.experience_value import formal_receiver_run_v2 as v2
from experiments.experience_value.records import AuthorizationError

ROOT = Path(__file__).resolve().parents[3]


class FakeTask:
    def __init__(self, task_id, _records): self.task_id, self.completed, self.successful_queries, self.failed_queries = task_id, False, 0, 0
    def reset(self): return type("View", (), {"task_id": str(self.task_id), "prompt": "synthetic V2 task"})()
    def query_sql(self, sql): self.successful_queries += 1; return "[]"
    def submit_answer(self, answer): self.completed = True; return "done"
    def evaluate_native(self): return type("Result", (), {"score": 1.0, "metrics": {"correct": True, "score": 1.0}})()


class FakeAdapter(ProviderAdapter):
    def __init__(self): self.requests=[]
    def stream(self, **_): raise TypeError()
    def complete_configured(self, **kwargs):
        self.requests.append(kwargs)
        return AdapterResponse(content="synthetic-answer", usage={"prompt_tokens": 1, "completion_tokens": 1}, stop_reason="stop")


def offpeak_ok(*_args, **_kwargs): return {"ok": True, "request_allowed": True, "new_episode_allowed": True}


class ReceiverV2Tests(unittest.TestCase):
    def setUp(self):
        self.bindings=v1.verify_frozen_bindings(); self.temp=tempfile.TemporaryDirectory(dir=ROOT/"artifacts/experience_value"); self.root=Path(self.temp.name)
        self.pending, self.pending_auth=v2.write_pending_files(self.bindings, self.root)
    def tearDown(self): self.temp.cleanup()
    def auth(self):
        p=json.loads(self.pending.read_text())
        a={"status": v2.AUTHORIZED_STATUS, "live_requests_authorized": True, "authorization_consumed": False, "real_model_requests_sent_under_this_authorization": 0, "pending_sha256": hashlib.sha256(self.pending.read_bytes()).hexdigest(), "entry_code": p["entry_code"], "block_id": p["block_id"], "allowed_tokens": p["allowed_tokens"], "hard_cap_usd": "8.00"}
        path=self.root/"authorized.json"; path.write_text(json.dumps(a)); return path
    def test_live_fake_block_consumes_once_and_stops_after_five(self):
        auth=self.auth(); fake=FakeAdapter()
        report=json.loads(v2.execute(pending_path=self.pending, authorization_path=auth, output_root=self.root/"run", mode="live", adapter=fake, task_factory=FakeTask, preflight=lambda:{"ok":True}, offpeak=offpeak_ok).read_text())
        self.assertEqual(report["status"], "COMPLETED"); self.assertEqual(len(report["episodes"]),5); self.assertEqual([x["frozen_token"] for x in report["episodes"]], ["t15-EMPTY","t15-M_F","t15-M_U","t15-RAW_F","t15-RAW_U"])
        self.assertEqual(len(fake.requests),5); self.assertEqual(report["next_block"],"NOT_STARTED"); self.assertTrue(json.loads(auth.read_text())["authorization_consumed"])
        self.assertTrue(all(x["native_answer_submitted"] and not x["consolidation"] and x["post_evaluation_model_calls"]==0 for x in report["episodes"]))
    def test_rejections_and_preflight_do_not_consume(self):
        auth=self.auth(); fake=FakeAdapter()
        for mutation in (lambda a:a.update(live_requests_authorized=False), lambda a:a.update(pending_sha256="0"*64), lambda a:a.update(allowed_tokens=[])):
            a=json.loads(auth.read_text()); mutation(a); auth.write_text(json.dumps(a))
            with self.assertRaises(AuthorizationError): v2.execute(pending_path=self.pending, authorization_path=auth, output_root=self.root/"bad", mode="live", adapter=fake, task_factory=FakeTask, preflight=lambda:{"ok":True}, offpeak=offpeak_ok)
            self.assertEqual(len(fake.requests),0)
            auth=self.auth()
        result=json.loads(v2.execute(pending_path=self.pending, authorization_path=auth, output_root=self.root/"preflight", mode="live", adapter=fake, task_factory=FakeTask, preflight=lambda:{"ok":False,"reason":"synthetic"}, offpeak=offpeak_ok).read_text())
        self.assertEqual(result["status"],"INVALID_INFRA_PRECHECK"); self.assertFalse(json.loads(auth.read_text())["authorization_consumed"])
    def test_consumed_reuse_and_plan_only(self):
        auth=self.auth(); v2.execute(pending_path=self.pending, authorization_path=auth, output_root=self.root/"run", mode="live", adapter=FakeAdapter(), task_factory=FakeTask, preflight=lambda:{"ok":True}, offpeak=offpeak_ok)
        with self.assertRaises(AuthorizationError): v2.execute(pending_path=self.pending, authorization_path=auth, output_root=self.root/"reuse", mode="live", adapter=FakeAdapter(), task_factory=FakeTask, preflight=lambda:{"ok":True}, offpeak=offpeak_ok)
        plan=json.loads(v2.execute(pending_path=self.pending, authorization_path=None, output_root=self.root/"plan", mode="plan-only").read_text())
        self.assertEqual(plan["provider_requests"],0); self.assertEqual(len(plan["episodes"]),5)


if __name__ == '__main__': unittest.main()
