# FILE POSITIVE CONTROL REPORT

Run status: **NOT EXECUTED — configuration/entry mismatch detected before any provider request.**

This report concerns only the independent authorization received as the user message
“继续运行” on 2026-09-21. It is an engineering positive control, not a primary-analysis
result: `study_kind=engineering_positive_control` and
`included_in_primary_analysis=false`.

## Authorization and preflight

- Frozen pending configuration: `experiments/experience_value/file_positive_control.pending.json`
- Frozen pending SHA-256: `66a5a53c57050d600aa6e8463e34a80628a95a582e01238d2a7aa76a490e7665`
- Authorization record: `experiments/experience_value/file_positive_control.authorized_20260921T111831Z.json`
- Authorization source: user message “继续运行”; recorded at `2026-09-21T11:18:31Z`.
- Requested provider configuration: DeepSeek `deepseek-v4-pro`, thinking enabled,
  `reasoning_effort=low`, 30-second timeout, zero application and SDK retries,
  5,120 input-token and 512 output-token reservation ceilings.
- Requested boundaries: three serial episodes; at most six actual provider requests
  and six tools per episode; at most 18 actual provider requests; only `list_dir`,
  `read_file`, `write_file`, and read-only SQLite SQL; no agent code execution.
- Budget reservation arithmetic in the frozen configuration is internally sufficient:
  USD 0.00878592/request × 18 = USD 0.15814656, below USD 0.20. This did not
  authorize using a mismatched entry point.

Preflight stopped before client construction or network activity because the repository
has no positive-control execution entry. The only available live entry,
`experiments/experience_value/live_smoke_run.py`, is explicitly an old `engineering_smoke`
runner. It requires a different `authorization` and `budget` schema, a status of
`AUTHORIZED_FOR_EXACT_THREE_EPISODES`, and fixed old task IDs/prompts (`U1` and the
prior local-fixture probe). It cannot load this positive-control configuration, does not
select the three frozen PC episode IDs, and would therefore violate the instruction not
to guess parameters or silently change tasks/configuration.

The previously present `artifacts/experience_value/e0-*` directories and their prior
requests are outside this authorization and were not read as, charged to, or reused by
this run.

## Episode records

| Episode | Condition | Status | Provider requests | Tool proposal/dispatch/success/failure | Result |
|---|---|---|---:|---|---|
| 1 | PC-SOURCE | NOT_RUN | 0 | list/read/write/SQL: 0/0/0/0 | No workspace, source artifact, snapshot, transcript, tool event, evaluation, or answer exists under this authorization. Stop: missing matching entry. |
| 2 | PC-MEMORY | NOT_RUN | 0 | list/read/write/SQL: 0/0/0/0 | No frozen source clone was created; no file discovery/read or probe answer occurred. Stop: episode 1 was not executable. |
| 3 | PC-EMPTY | NOT_RUN | 0 | list/read/write/SQL: 0/0/0/0 | No empty workspace probe, evaluation, or answer occurred. Stop: entry preflight failed. |

For every episode, “write success,” “read success,” and “evidence of use” are all
`NOT_OBSERVED`, rather than inferred. No final answer was accepted; no evaluator ran;
task correctness is `NOT_EVALUATED`. There is no source snapshot to test for immutability.

## Evidence and accounting

- Provider transcripts: none created; no provider request was sent.
- Tool events: none created; no tool was proposed, dispatched, succeeded, or failed.
- Source artifact / frozen snapshot / probe results: none created.
- Cost ledger: zero reservations, zero estimated/settled cost, zero unknown billing,
  and no provider invoice or other real billing record.
- Additional episodes: zero. No retry, final-answer call, microtest, 78-episode batch,
  public environment, code sandbox, commit, push, or background task was started.

This is a stopping report, not evidence of learning, performance improvement, or a
causal effect.
