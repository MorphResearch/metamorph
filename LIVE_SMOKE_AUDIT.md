# Live smoke offline evidence audit

Scope: this audit reads only the three-episode run rooted at
`artifacts/experience_value/e0-0a386c98a62f46c1b005aa660a91bd57` and the
frozen signed configuration hash
`ff3cadeb389e213d97e65c242a3530710ed843a1e46696c20fdaaa809278e25e`.
It made **zero** provider requests. The original report and JSONL are not
rewritten.

## Evidence limits

The JSONL has request IDs, message hashes, character counts, schema hashes,
usage, adapter stop reasons, model-decision events, tool-completed events, and
SQLite status events. It does **not** retain raw provider response objects,
complete request messages, request `tool_choice`, a server continuation ID,
or the original `tool_call_id`. Therefore, all tool/request pairings below are
the unambiguous sequential pairing from `provider.request_finished` →
`model.decision` → tool event(s) → next `provider.request_started`; the missing
fields are marked `NOT_RECORDED`, not reconstructed.

`e98bbbe1…` is the hash of the three allowed schemas; `4f53cda1…` is the hash
of `[]`. The latter appears only on each probe's final request after six
counted tool calls.

## All 17 counted tool calls

Every counted event was model-proposed as evidenced by the preceding adapter
stop reason `tool_calls` and `model.decision.action=tool_call`. JSON parsing is
not independently logged in this historical run, but a decoded argument object
reached the dispatcher; it is therefore `INFERRED_PASS`, not a raw-response
claim. `parameter validation=PASS` means no `参数校验失败` result was observed.
`feedback→next` means the normal loop appended the result and the next actual
request began; the exact next message body was not retained.

| # | Episode / originating request | Tool and arguments | Parse / parameters / permission | Dispatch result and count | Feedback→next |
|---:|---|---|---|---|---|
| 1 | E1 R1 `6f39c635…` | `query_sql`: `SELECT name FROM sqlite_master WHERE type='table';` | inferred pass / pass / allowlisted | dispatched; read-only SQL policy rejected semicolon before DB query; tool counter +1, SQL rejected +1 | R2 |
| 2 | E1 R2 `d02b63ae…` | `query_sql`: table names from `sqlite_master` | inferred pass / pass / allowlisted | dispatched; SQLite success; tool +1, SQL success +1 | R3 |
| 3 | E1 R3 `e3635fde…` | `query_sql`: `SELECT * FROM regions` | inferred pass / pass / allowlisted | dispatched; SQLite success; tool +1, SQL success +1 | R4 |
| 4 | E1 R4 `e4135624…` | `query_sql`: `SELECT * FROM observations` | inferred pass / pass / allowlisted | dispatched; SQLite success; tool +1, SQL success +1 | R5 |
| 5 | E1 R5 `e55a634d…` | `query_sql`: regions table DDL | inferred pass / pass / allowlisted | dispatched; SQLite success; tool +1, SQL success +1 | R6 |
| 6 | E2 R1 `d25c4582…` | `read_file /memory/task.md` | inferred pass / pass / allowlisted | dispatched; path absent; tool +1, file read success +0 | R2 |
| 7 | E2 R1 `d25c4582…` | `read_file /work/task.md` | inferred pass / pass / allowlisted | dispatched; path absent; tool +1, file read success +0 | R2 |
| 8 | E2 R2 `1659194a…` | `query_sql`: `information_schema.tables` with schema filter | inferred pass / pass / allowlisted | dispatched; SQLite attempted and failed (`no such table`); tool +1, SQL failed +1 | R3 |
| 9 | E2 R2 `1659194a…` | `query_sql`: `information_schema.tables` | inferred pass / pass / allowlisted | dispatched; SQLite attempted and failed (`no such table`); tool +1, SQL failed +1 | R3 |
| 10 | E2 R3 `6d385fac…` | `query_sql`: schema from `sqlite_master` | inferred pass / pass / allowlisted | dispatched; SQLite success; tool +1, SQL success +1 | R4 |
| 11 | E2 R4 `c3071297…` | `query_sql`: `SELECT * FROM regions` | inferred pass / pass / allowlisted | dispatched; SQLite success; tool +1, SQL success +1 | R5 |
| 12 | E3 R1 `eb7d35ba…` | `read_file /memory` | inferred pass / pass / allowlisted | dispatched; directory/not regular file; tool +1, file read success +0 | R2 |
| 13 | E3 R2 `3a8b5432…` | `read_file /memory/README.txt` | inferred pass / pass / allowlisted | dispatched; path absent; tool +1, file read success +0 | R3 |
| 14 | E3 R2 `3a8b5432…` | `read_file /work/README.txt` | inferred pass / pass / allowlisted | dispatched; path absent; tool +1, file read success +0 | R3 |
| 15 | E3 R3 `ff5dbcef…` | `read_file /memory/notes.txt` | inferred pass / pass / allowlisted | dispatched; path absent; tool +1, file read success +0 | R4 |
| 16 | E3 R3 `ff5dbcef…` | `read_file /work/notes.txt` | inferred pass / pass / allowlisted | dispatched; path absent; tool +1, file read success +0 | R4 |
| 17 | E3 R4 `3276d38b…` | `query_sql`: table names from `sqlite_master` | inferred pass / pass / allowlisted | dispatched; SQLite success; tool +1, SQL success +1 | R5 |

Thus E1 is 5 tools = 4 successful SQL + 1 policy-rejected SQL. E2 is 6 tools
= 2 failed file reads + 2 failed SQL + 2 successful SQL. E3 is 6 tools = 5
failed file reads + 1 successful SQL. The original report's `file_reads=0`
counts successful runtime reads (`agent.file_read`), not dispatched read-file
attempts.

There is one additional **uncounted** E2 R4 proposal: the log records
`requested=2, permitted=1`, so the runner suppressed one call for the tool
cap. Its ID/name/arguments are `NOT_RECORDED` in the historical response log;
it was not dispatched, not an SQL attempt, and not part of the 17.

## Probe termination paths

### E2 (memory requested as `M_U`, actual parent was an empty source snapshot)

R4 began with the all-tools schema, 3,482 serialized message characters, and
1,132 provider-reported prompt tokens. The provider stop reason was
`tool_calls`; it proposed two calls, then the runner emitted the cap event and
only dispatched the `regions` query. R5 began after that feedback with 4,025
characters but the empty schema hash, and returned `stop` with 603 prompt
tokens and DSML-looking text in `answer.delta`.

No forced finalization, message rebuild, or history-cropping branch exists in
the E0 loop. The message character count grew. The token reduction alone is
therefore only an unexplained provider-usage observation; raw messages and
provider response objects were not persisted, so it cannot establish context
loss or prove complete message retention. The final DSML text flowed through
the normal non-streaming path: SDK `message.content` → `AdapterResponse.content`
→ `run_loop` `assistant_content` → returned `answer`; the raw provider object
was not retained, so a distinction before the adapter is `NOT_RECORDED`.

### E3 (empty memory)

R4 similarly had all schemas, 2,503 characters, and 901 prompt tokens; it
successfully queried table names, reaching tool count six. R5 had 2,956
characters and the empty schema hash, returned `stop` with 526 prompt tokens,
and its `answer.delta` contains unexecuted DSML query text. The same
non-attribution caveat applies.

The frozen configuration specifies thinking enabled, `reasoning_effort=low`,
no temperature, and no explicit `tool_choice`. The code sends the thinking
flag and replays nonempty `reasoning_content` on tool continuations. The event
log shows reasoning-token fields and some reasoning events, but not the raw
outgoing assistant messages; actual retention of each vendor-required field is
therefore `NOT_RECORDED`, not independently proved by this run.

For both probes, `tool_budget_exhausted` becomes determined immediately before
R5: after R4 dispatch increments the counter to six, R5 is constructed with
zero schemas. The original raw metrics stored `model_finished` because the old
loop treated any non-tool text as a normal finish. The original field remains
unchanged; the corrected result-layer interpretation is `tool_budget_exhausted`.

## Result-field meanings and correction

`metrics.success` is `bool(answer)` in `run_loop`; it means only that the
function returned nonempty text. It is neither model-task success, a valid task
answer, evaluator execution, nor correctness. `task_score.scored=true` is
truthful here: the deterministic local-fixture evaluator was actually called
on the observed returned string. It can therefore accompany an invalid answer
and `correct=false`.

| Episode | Runner returned text | Corrected stop | Valid task answer | Evaluator executed | Correct |
|---|---:|---|---:|---:|---:|
| E1 | yes | `model_finished` | yes | yes | yes |
| E2 | yes (DSML text) | `tool_budget_exhausted` | no | yes | no |
| E3 | yes (DSML text) | `tool_budget_exhausted` | no | yes | no |

The local result layer now emits these separate fields for future runs:
`runner_returned_nonempty_text`, `answer_accepted_as_task_answer`,
`evaluator_executed`, `task_correct`, and `unexecuted_tool_text_detected`.
It does not rewrite the historical `metrics.success` or the original report.

## Zero-artifact observation

E1 received the three-tool schema on every request, including a usable
`write_file` operation, and the source prompt referred to `/memory` and
optional reusable saving. No actual write attempt occurred, so the live trace
does not demonstrate a successful real-model file write; fake transport tests
do demonstrate the implementation path. The frozen snapshot is empty and
unchanged. `requested_memory_condition=M_U` for E2 is retained as the requested
condition; its actual parent hash is the empty snapshot hash. Neither probe
read a source artifact.

The historical source prompt made saving optional but did not explicitly say a
future *new* session could receive a clone. The shared source prompt is now
clarified—optionally and for every F/U condition—that an immutable `/memory`
snapshot may be cloned into a later new session when permitted. This is a
documentation/prompt correction, not a new retention requirement, and this
run was not repeated.

## Offline fixes and verification

- Future logs now record `tool.proposed`, `tool_call_id`, raw arguments,
  budget-truncated IDs, dispatch/policy/parse fields, and
  `tool.feedback_appended`. Historical absent fields remain absent.
- The loop marks a response received with no schemas after the tool cap as
  `tool_budget_exhausted`, rather than ordinary model completion.
- The result classifier rejects unexecuted DSML-looking text as a valid task
  answer while retaining the fact that the evaluator executed.

Verified offline with the project interpreter:

```text
./.venv/bin/python -m unittest experiments.experience_value.tests.test_e0_acceptance -v  # exit 0, 18 passed
./.venv/bin/python -m unittest discover -s tests -q                                      # exit 0, 77 passed
```

The new regressions cover tool proposal/dispatch/feedback logging, budget
exhaustion not masquerading as normal completion, and separation of runner
return, evaluation, and task success. The pre-existing snapshot-isolation
tests still pass.

## Next-microtest budget decision

No automatic budget change is warranted and no remaining authorization is
available. The evidence does show a tool-cap pressure point: E2 had one
additional proposal suppressed at R4, and both R5 responses contained query
markup after schemas were removed. A future, separately authorized configuration
may review the six-tool limit and clearer discovery guidance, but this single
trace does not establish an exact replacement limit or justify increasing money,
request, or tool budgets now.

## Source references

- [Original event log](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/artifacts/experience_value/e0-0a386c98a62f46c1b005aa660a91bd57/research_records/events.jsonl:32)
- [Frozen run manifest](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/artifacts/experience_value/e0-0a386c98a62f46c1b005aa660a91bd57/research_records/live_smoke_run_manifest.json)
- [Original live report](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/LIVE_SMOKE_REPORT.md)
