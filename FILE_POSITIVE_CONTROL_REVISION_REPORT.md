# File positive-control local revision report

Scope: implementation and offline validation only. No real provider request was
made in this revision, and the completed 17-request authorization was neither
read as spendable nor reused. Existing run artifacts and reports remain unchanged.

## PC-MEMORY terminal-decision audit

Evidence: the completed run's PC-MEMORY attempt
`310eb890125c4ae1abdd3afaad89c5cd` in
`artifacts/experience_value/e0-d85add05283a4dc0936314c450c5b5a7/research_records/`.

- Six provider requests, six dispatched tools, USD 0.00920832 conservative
  estimated cost, and 12.53224 seconds were all within its per-episode limits
  (6 requests, 6 tools, USD 0.20 batch cap, 30-second per-request timeout).
- Every one of the six dispatched tool calls has a matching
  `tool.feedback_appended` record. At step 5 both remaining SQL calls were
  dispatched and fed back before request 6.
- Request 6 used the empty tool schema because the tool cap had been reached.
  It returned a natural-language answer containing `6`; it did not contain
  unexecuted DSML tool text, and no tool was dispatched beyond the cap.
- The original report remains authoritative for its old strict field:
  `task_score.correct=true` and `final_answer_validity.answer_accepted_as_task_answer=false`.
  The latter was caused solely by `runner_stop_reason=tool_budget_exhausted`.

The new `evaluate_terminal_result_v2` reports separately: raw answer correctness,
format/feedback protocol validity, tool-limit reached, actual authorization-range
exceeded, normal/resource-limited termination, and a joint result. For this historical
PC-MEMORY observation those values are respectively `true`, `true`, `true`, `false`,
resource-limited, and `true`. This is a versioned interpretation only; it does not
modify the original evidence or claim an extra request/tool opportunity.

## Atomic file-I/O control

New entry support is in
`experiments/experience_value/file_positive_control_run.py`:

- `PC-WRITE` has only `query_sql` and `write_file`, and receives exactly
  `SELECT payload FROM io_probe`. A fresh run-local SQLite fixture creates one
  random non-sensitive marker. The marker is absent from the initial prompt and
  workspace; success requires an actual SQL response containing it and a
  model-originated file whose exact content matches it.
- `PC-READ` starts only after that source success, from an independent source
  clone and fresh conversation. It has only `list_dir` and `read_file`, no SQL
  tool, source filename, marker, or source dialogue. Success requires directory
  discovery, file read, exact marker return, and unchanged source hash.
- A failed source yields `BLOCKED_SOURCE_ARTIFACT`; no empty receiver, repair,
  replacement file, or retry is started.

Run commands:

```bash
./.venv/bin/python -m experiments.experience_value.file_positive_control_run --atomic-plan-only
./.venv/bin/python -m experiments.experience_value.file_positive_control_run --atomic-live
```

The second command is intentionally blocked before transport/client use by the new
pending authorization record. It can run only after a separately signed record has
status `AUTHORIZED_FOR_EXACT_TWO_ATOMIC_FILE_IO_EPISODES` and explicitly enables live
requests.

## Offline validation

- `python -m unittest experiments.experience_value.tests.test_file_positive_control_run -v`:
  7 passed. It covers a final valid answer after the last permitted tool, DSML text,
  over-limit-tool rejection, missing tool feedback, successful atomic SQL→write→freeze→fresh
  list/read flow, blocked source behavior, and pending-live authorization rejection.
- `python -m unittest discover -s tests -q`: 77 passed.
- `python -m unittest discover -s experiments/experience_value/tests -q`: 28 passed.
- `--atomic-plan-only` parsed the real independent configuration and produced zero
  provider requests in `/private/tmp/metamorph-atomic-plan-only`; fake artifacts were
  created only in test temporary directories and were not copied into any real run.

## Pending independent authorization

The candidate configuration is
`experiments/experience_value/atomic_file_io_control.pending.json` (SHA-256
`acc2de068fbbc6270c44bf837a71a4963b28381b9f537b1b03a31785bd269869`), with its
independent pending authorization record
`experiments/experience_value/atomic_file_io_control.authorization.pending.json`
(SHA-256 `068e68bb75e8b276c135767e5f70980d01547abd95abcabac2d93449c94fa82a`).

It freezes at most two episodes, six requests and six tools per episode, twelve
requests total, DeepSeek `deepseek-v4-pro`, thinking low, 30-second timeout, and zero
application/SDK retries. Reservation is USD 0.00878592/request and USD 0.10543104 for
twelve requests, below the proposed USD 0.20 cap. This is a candidate only:
`live_requests_authorized=false`, real requests recorded as zero. Both the original
and new controls are excluded from primary analysis and future F/U research samples.
