# E0 phase status — tool-only preparation update

| Phase | Status | Evidence / blocker |
|---|---|---|
| Offline isolation and memory acceptance | PASS | Original T01–T14 remain passing; extended suite is now 17/17. |
| Local-fixture real file + read-only SQL smoke | COMPLETED (engineering only) | Three signed DeepSeek episodes sent 16 requests under the USD 0.20 cap. The source wrote no artifact; both probes reached the tool cap, so there is no learning claim. See `LIVE_SMOKE_REPORT.md`. |
| Atomic file I/O control | COMPLETED (engineering only) | Under restricted file tools, one real-model run produced a model-written file and a fresh-session directory discovery/read. The historical whole-response field `returned_exact_marker=false` is retained; exact-marker containment and whole-response equality are reported separately. The run, transcripts, artifacts, config, and authorization are retained and backed up; no Atomic artifact is mounted for F/U work. |
| Public environment integration | DEVELOPMENT ACCEPTANCE PASS (zero-model) | Official `continual-learning-bench` remains at fixed commit `5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26`. A separate Python 3.13 environment downloaded only the two official Database Exploration SQLite snapshots; the thin adapter executed one legal query and the unchanged upstream evaluator distinguished a researcher-side wrong answer (score 0.0) from a correct development answer (score 0.9333). No provider or paid-evaluator request was sent; instance 1 is permanently development-contacted. See `PUBLIC_ENVIRONMENT_INTEGRATION_REPORT.md`. |
| Arbitrary Agent code execution sandbox | BLOCKED | No verified sandbox; no Python/bash/eval/import/code tool is exposed. Code files are static byte artifacts in this temporary smoke scope. |
| 78-episode E1+E2 development batch | NOT AUTHORIZED / NOT STARTED | Existing plan-only record remains zero-request; this update adds no batch runner or authorization. |

The temporary tool-only boundary does not freeze the study's eventual open
artifact formats. It only prevents unsafe execution while the code sandbox is
unverified.

Verified commands for this update:

```text
./.venv/bin/python -m json.tool experiments/experience_value/live_smoke_config.pending.json   # exit 0
./.venv/bin/python -m compileall -q experiments/experience_value graphs llm                   # exit 0
./.venv/bin/python -m unittest experiments.experience_value.tests.test_e0_acceptance -v       # exit 0, 17 passed
./.venv/bin/python -m unittest discover -s tests -q                                             # exit 0, 77 passed
```
