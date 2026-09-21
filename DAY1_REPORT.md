# Metamorph E0 — Day-1 acceptance report

```text
Repository preflight: PARTIAL
Protocol draft: PARTIAL
Offline tests: passed=14, failed=0, blocked=0
Scripted memory plumbing: PASS
Real model smoke: NOT_RUN
Public benchmark integration: BLOCKED
Memory generated / read / executed: ScriptedAgent 1 / 1 / 0; real model NOT_MEASURED
Agent-model requests / spend: 0 / NOT_RUN
Paid batch launched: NO
Scientific improvement claim: NOT_EVALUATED
Ready for authorized development batch: NO — public environment, explicit live authorization, and code-sandbox decision remain open
```

## What changed

The new [E0 harness](experiments/experience_value/README.md) has independent
logical `/memory` and `/work` roots, fresh conversation IDs, frozen SHA-256
snapshots, safe clone-only probes, runner-only logs, condition/replicate path
isolation, a ScriptedAgent-only smoke, and a fixed-receiver probe entry for
`EMPTY`, `M_F`, `M_U`, `RAW_F`, and `RAW_U`. It also adds pre-reservation cost
records, blocks live calls without all authorization fields, caps Day-1 live
work at three episodes, and includes a metered, read-only synthetic SQLite
fixture. `artifacts/experience_value/` is ignored only to avoid committing
local run data and secrets-adjacent evidence; it remains on disk.

Supporting design and reproducibility material is in
`experiments/experience_value/{protocol_v0.1.yaml,task_manifest.dev.json,research_question.md,DESIGN_DECISIONS.md,AI_ASSISTANCE_LOG.md}`.
The protocol uses `fixed_workflow_implementation=prompt_prescribed_v0`, which
is a development choice, not a frozen or program-enforced F protocol.

## Actual verification

| Command | Exit | Result |
|---|---:|---|
| `./.venv/bin/python -m unittest experiments.experience_value.tests.test_e0_acceptance -v` | 0 | T01–T14: 14 passed. |
| `./.venv/bin/python -m experiments.experience_value.smoke` | 0 | Durable ScriptedAgent-only source → frozen snapshot → new memory probe and EMPTY probe evidence. |
| `./.venv/bin/python -m experiments.experience_value.runner --output-root artifacts/experience_value --plan-only` | 0 | 78 planned episodes (E1 48 + E2 30), zero requests. |
| `./.venv/bin/python -m compileall -q experiments/experience_value` | 0 | New package compiled. |
| `./.venv/bin/python -m unittest discover -s tests -v` | 0 | Existing project suite: 77 passed. |
| `python -m unittest discover -s tests -v` | 1 | Not an E0 code failure: system Python lacks `pydantic` (two import errors). |
| `pytest -q` | 127 | `pytest` command unavailable in the active shell. |

The fixed development evidence is [scripted smoke summary](artifacts/experience_value/e0-7675322b3f7947e687035da6ebcc3b9f/research_records/scripted_smoke_summary.json): it records a source artifact produced by `ScriptedAgent` after one real SQLite query, an independent new session that read it, an EMPTY session that could not retrieve it, unchanged source hash, 0 model requests, and `NOT_RUN` spend. The corresponding [event log](artifacts/experience_value/e0-7675322b3f7947e687035da6ebcc3b9f/research_records/events.jsonl) records separate conversation/attempt IDs plus prompt, request-configuration, tool-schema, receiver, and snapshot hashes. This establishes plumbing only; it is not evidence that a model created or used experience.

The [plan-only record](artifacts/experience_value/e0-7bc4ad6d396b4259b26497343383feab/research_records/plan_only.json) contains 78 `planned_only` rows and `requests_sent=0`; it did not launch the 48+30 batch.

## Boundaries, versions, and status

- Git HEAD at preflight: `31e568a1f9f04582ea1db67806c2cc739187ce3f`; the worktree already had unrelated modifications, all preserved.
- E0 source-tree SHA-256: `9535a0af53d13d82a00f95346baffb6d9cdea63b8a116a707e4ba6fb1ca8b177`.
- The public CL-Bench environment was not found or connected. The local fixture is explicitly `engineering_smoke`, `included_in_primary_analysis=false`, and must not be called a CL-Bench score.
- No real model request was made. The report does not claim a real agent wrote, read, or executed an experience artifact. `code_execution_isolation=BLOCKED`, so zero real code-execution evidence exists.
- The existing provider configuration has candidate defaults, and local credential variables may exist, but no secret values were read and neither constitutes authorization. Retry, usage, unknown billing, and stop handling are offline-tested only.

## Minimum confirmation required before live smoke

1. Exact provider and API model ID; all request parameters, output/token limits, per-episode request/tool limits, timeout, and finite retry rule.
2. Currency, current price basis, and a hard monetary cap for no more than three complete engineering-smoke episodes.
3. The preselected practice/probe manifest and whether the current absence of a verified code sandbox restricts the smoke to file and SQLite-tool artifacts.
4. A verified public-environment checkout/version, task IDs, and evaluator interface before claiming readiness for the authorized development batch.

No commit, push, background process, paid batch, formal matrix, or real-model microtest was started.
