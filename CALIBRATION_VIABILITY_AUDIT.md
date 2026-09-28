# Calibration viability audit

**Scope.** This is a read-only audit of final v3 development run
`e0-f4bbd72f46544ba3b7f07bdd43cc753b`.  It did not send a provider request,
run an evaluator, alter the historical run, or create an experiment batch.
The raw evidence is retained under
`artifacts/experience_value/public_calibration/e0-f4bbd72f46544ba3b7f07bdd43cc753b/research_records/`.

## Direct result

All six episodes had `native_score=null`, because none reached the runner's
native `ANSWER` action.  There were 46 completed provider decisions (and 46
provider attempts), no transport retry, no provider failure, and no evaluator
feedback supplied to the model.  Their derived v3 analysis outcomes are all
`RESOURCE_LIMITED_FAILURE` with `analysis_score=0`; those are not native zero
scores and must not be rewritten as such.

The immediate causes are heterogeneous:

| Episode | Condition | Last resource stop | Native ANSWER reached? |
| --- | --- | --- | --- |
| dev-1-f0 | F0 | `query_sql_budget_reached` | no |
| dev-1-u0 | U0 | `output_token_limit_reached` | no |
| dev-2-u0 | U0 | `input_token_budget_reached` | no |
| dev-2-f0 | F0 | `input_token_budget_reached` | no |
| dev-3-f0 | F0 | `query_sql_budget_reached` | no |
| dev-3-u0 | U0 | `query_sql_budget_reached` | no |

Thus the run provides **zero of six native-scored observations**, rather than
six observations of task failure.

## Last two completed decisions per episode

`finish_reason` below is the provider response field recorded as
`response.stop_reason` in the transcript.  `P→D` means model-proposed tool
calls that the runner dispatched and completed successfully.  SQL counts are
reconstructed from the paired `tool.proposed` and `tool.completed` records.

| Episode | Decision | finish_reason | Visible content | Reasoning tokens | P→D | SQL before→after | Was a next request allowed by the actual runner? | Final resource stop |
| --- | ---: | --- | --- | ---: | --- | --- | --- | --- |
| dev-1-f0 | 6 | `tool_calls` | empty | 658 | `query_sql` x2 → x2 | 11→13 | yes | `query_sql_budget_reached` |
|  | 7 | `tool_calls` | empty | 944 | `query_sql` x2 → x2 | 13→15 | no: runner closed after feedback |  |
| dev-1-u0 | 7 | `tool_calls` | empty | 1,476 | `query_sql` x2 → x2 | 9→11 | yes | `output_token_limit_reached` |
|  | 8 | `length` | empty | 8,192 | none | 11→11 | no: output limit was reached |  |
| dev-2-u0 | 7 | `tool_calls` | empty | 328 | `query_sql` x2 → x2 | 9→11 | yes | `input_token_budget_reached` |
|  | 8 | `tool_calls` | non-empty (409 chars) | 1,842 | `query_sql` x1 → x1 | 11→12 | no: the following request was pre-send blocked |  |
| dev-2-f0 | 8 | `tool_calls` | empty | 44 | `query_sql` x1 → x1 | 10→11 | yes | `input_token_budget_reached` |
|  | 9 | `tool_calls` | empty | 5,193 | `query_sql` x1 → x1 | 11→12 | no: the following request was pre-send blocked |  |
| dev-3-f0 | 6 | `tool_calls` | empty | 1,219 | `query_sql` x2 → x2 | 12→14 | yes | `query_sql_budget_reached` |
|  | 7 | `tool_calls` | empty | 2,867 | `query_sql` x1 → x1 | 14→15 | no: runner closed after feedback |  |
| dev-3-u0 | 6 | `tool_calls` | empty | 285 | `query_sql` x2 → x2 | 12→14 | yes | `query_sql_budget_reached` |
|  | 7 | `tool_calls` | empty | 875 | `query_sql` x1 → x1 | 14→15 | no: runner closed after feedback |  |

### The three 15-query paths

All three are **A**, not B or C.  In each case the fifteenth `query_sql` was
dispatched, completed, and appended as feedback (`Query result (15/15 queries
used, 0 remaining)`).  The only subsequent event types were
`tool.feedback_appended` and `tool_only_episode.completed`; there was no later
`provider.request_started`, no later completed model decision, and no attempted
sixteenth query.  The existing loop therefore closed immediately after the
fifteenth-query feedback.  It did not offer a terminal text-only decision that
could have produced `ANSWER`.

That is a runner/interface semantic, separate from the model's observed choice
to use the final permitted decision for a query.  A text-only terminal decision
would still have been below the 24-decision cap, but the current implementation
does not reserve or expose such a decision after the native SQL cap.

## Input-budget stops

The input budget is an estimator-side pre-send gate, not an observed provider
context limit.  Consequently neither blocked request has `prompt_tokens` from
the provider.

| Episode | Blocked request serialized chars / UTF-8 bytes / request bytes | Estimated tokens | Immediately preceding completed request: estimate → actual prompt tokens (error) |
| --- | --- | ---: | --- |
| dev-2-u0 | 52,125 / 52,146 / 53,141 | 27,531 | 23,509 → 7,307 (-16,202) |
| dev-2-f0 | 55,439 / 55,479 / 56,474 | 29,229 | 18,402 → 8,075 (-10,327) |

The completed-request trajectories establish only the following facts.  For
dev-2-u0, actual prompts grew from 927 to 7,307 over eight requests while the
estimate grew from 1,930 to 23,509.  For dev-2-f0, actual prompts grew from 946
to 8,075 over nine requests while the estimate grew from 1,972 to 18,402.
They do **not** establish the actual token count of either unsent request.

Across all 46 completed requests, using the recorded
`calibrated_utf8_half_bytes_plus_chat_tool_overhead_v1` values:

| Measure | Min | P25 | Median | P75 | Max | Mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Actual provider prompt tokens | 927 | 1,620.25 | 3,637.5 | 6,037.25 | 8,075 | 3,875.52 |
| Estimated tokens | 1,930 | 3,549.25 | 8,456 | 14,718.5 | 23,509 | 9,436.87 |
| Actual − estimate | -16,202 | -8,108.25 | -4,893.5 | -1,929 | -1,003 | -5,561.35 |
| Actual / estimate | 0.284 | 0.425 | 0.437 | 0.465 | 0.480 | 0.432 |

Every completed sample overestimated actual prompt tokens.  This is a
consistent safety bias rather than evidence that the provider would have
accepted the two blocked requests.  However, as currently calibrated it is
**not suitable as a 24,000-token formal research cutoff**: it censors episodes
when the only observed nearby prompts are 7,307 and 8,075 actual tokens.
The 24,000 value must remain explicitly an estimator budget until a
model-aligned estimator or a separately validated conservative calibration is
frozen.  Characters remain diagnostic data only.

## Output-limit path: dev-1-u0

The eighth response had `finish_reason=length`, `completion_tokens=8,192`,
`reasoning_tokens=8,192`, visible content length 0, and no tool calls.  The
recorded provider accounting therefore supports the classification **reasoning
occupied the reported generation budget**; it does not support a claim that a
visible answer was generated and truncated.  No automatic follow-up was sent,
as required by the frozen rule.  This is one resource-limited path, not a
native-scored wrong answer.

## Experience production and isolation

All six episodes had zero proposed and zero dispatched `write_file`, `list_dir`,
and `read_file` operations.  Every recorded output snapshot had an empty file
list.  Four completed snapshots have the empty-directory SHA-256
`e3b0c442...b855`; the two input-pre-send stops record no final snapshot hash,
but also have an empty `snapshot_files` list and zero file events.

The common prompt explicitly says the agent may use `/memory`, may save reusable
text/code/tests there, and that an immutable snapshot may be independently
cloned into a later new session when permitted.  The calibration task manifest
also says that saving inert notes under `/memory` is voluntary.  Thus the agent
was told about the mechanism, but this calibration's six episodes intentionally
start empty and pass no snapshot to another episode.  There is no non-empty
experience artifact here, and no F1/U1 experience-transfer measurement can be
made from this run.

## Viability decision

### What explains the six non-scored episodes?

It is a combination, not evidence for a single source of model weakness:

- **Model behavior:** all final completed decisions either requested more SQL
  or, once, exhausted generation in reasoning.  No model response supplied a
  terminal answer.
- **Runner semantics:** in three episodes the runner closed immediately upon
  completing the 15th native query.  This removed any terminal `ANSWER`
  opportunity after the final legal SQL feedback.
- **Estimator artifact:** two episodes were stopped by a conservative estimate
  whose observed actual/estimate ratio was 0.284–0.480 across all completed
  requests.  These are estimator stops, not demonstrated provider-context
  stops.
- **Output allocation:** one episode exhausted all 8,192 reported completion
  tokens as reasoning with no visible content.

There is no evidence here of infrastructure failure, evaluator failure, a
reference leak, or a native evaluator returning a zero score.

### Is the current protocol measurable?

**No.** With 0/6 native `ANSWER`s and 0/6 non-empty experience snapshots, the
current public-task protocol cannot estimate task performance or a F0/U0/F1/U1
experience effect.  Treating the six derived zeroes as performance observations
would confound model behavior with a missing terminal interface and estimator
censoring.

### Minimal necessary changes before formal F0/U0/F1/U1

**Interface-correctness fixes**

1. Preserve the native 15-SQL limit, but provide exactly one terminal
   text-only decision after the fifteenth query's feedback (with SQL disabled
   for that decision).  Map only its ordinary text to native `ANSWER`; do not
   execute a sixteenth query or add a post-evaluation call.
2. Define the equivalent terminal behavior for all resource-stop paths before
   the formal run, so a runner stop cannot silently replace an otherwise
   possible native submission.

**Measurement-design fixes**

1. Recalibrate or replace the input-token estimator against actual provider
   usage, then pre-register a shared cutoff that does not use characters as
   tokens and is validated for full legal SQL histories.  This is a compute
   measurement correction, not an increase to the task's SQL allowance.
2. Separately validate the shared response-budget/terminal-answer policy under
   provider reasoning accounting.  The v3 observation shows that 8,192 reported
   completion tokens can yield no visible output; any changed common policy
   must be frozen before the formal matrix and applied identically to F and U.
3. Establish, prospectively and outside the formal sample, that source episodes
   can reach a terminal answer and that the public-task file interface can
   produce a non-empty voluntary artifact when one is chosen.  F1/U1 should
   receive only the predeclared immutable source snapshot; calibration artifacts
   must not become formal experience.

**Do not treat these as performance tuning**

- Do not add task-specific table/column hints, SQL, answer text, or evaluator
  feedback to either condition.
- Do not raise the 15-query cap, add model decisions after evaluation, change
  F/U prompts differentially, force experience writing, choose the best run, or
  rerun failed formal episodes selectively.
- Do not use the Atomic marker artifact as a public-task experience sample.

## Decision

**NO_GO for the formal F0/U0/F1/U1 matrix now.**  A future run can be considered
only after the interface and measurement corrections above have been frozen and
an independently authorized, prospective calibration demonstrates both
native-scoring reachability and an interpretable experience-production path.
This audit makes no claim about learning, generalization, or relative F/U
performance.
