# Public viability revision

`study_kind=development_public_viability_gate`  
`included_in_primary_analysis=false`

## Scope

This is a measurement-interface revision following [CALIBRATION_VIABILITY_AUDIT.md](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/CALIBRATION_VIABILITY_AUDIT.md). No historical run, task prompt, task answer, reference SQL, native evaluator, F/U workflow difference, or native 15-query limit was changed. No live provider or paid-evaluator request was sent.

The old protocol was unmeasurable: three episodes closed immediately after the fifteenth SQL feedback, two were censored by the old high estimate, one hit the output limit, none reached native `ANSWER`, and none created an artifact.

## Terminal ANSWER interface

The loop now has an explicit `terminal_only_after_tool_limit_names` mode. Under the new protocol, after the fifteenth legal `query_sql` feedback:

- It schedules exactly one further decision only if fewer than 24 main decisions were used.
- The decision has an empty tool schema. Any proposed tool call is logged/rejected and never dispatched; no sixteenth SQL or follow-up is possible.
- Ordinary text is submitted once to native `ANSWER`; the native evaluator runs afterward on the researcher side. Evaluator/reference feedback never returns to the model, workspace, or transcript.
- If the fifteenth query occurs at decision 24, `terminal_answer_unavailable_model_decision_budget_reached` is recorded without a twenty-fifth request. Input, output, decision, file-operation, and episode-timeout limits remain direct main resource stops. Only the SQL-cap path gets the terminal-only opportunity.

The terminal decision counts within the existing 24 main decisions and has no finalization retry.

## Formal token cutoff

The existing `calibrated_utf8_half_bytes_plus_chat_tool_overhead_v1` remains intact as a diagnostic log. It records estimate, serialized characters/bytes, response-side actual `prompt_tokens`, and error. It no longer alone governs the formal 24,000-token cutoff.

No exact offline tokenizer maps `deepseek-v4-pro` in the reviewed Python 3.13 environment: `tiktoken.encoding_for_model` raises its model-mapping `KeyError`. The frozen formal estimator is therefore `deepseek_prompt_usage_calibrated_v1`:

```text
formal_estimate = ceil(diagnostic_estimated_tokens * 0.50) + 256
stop when formal_estimate >= 24,000
```

It was calibrated from all 46 v3 provider-reported prompt-token observations only. The actual/old-estimate ratio was 0.284–0.480 (maximum 0.480392); task scores, answers, SQL, and condition outcomes were excluded. Both estimates and their post-response errors are persisted. Characters are never a token cutoff.

## Common optional consolidation and provenance

Every source condition uses this same pre-evaluator step after native `ANSWER` submission, or after a main resource termination:

> 你现在可以选择把任何你认为可能对未来任务有帮助的可复用信息保存到 /memory。内容和格式由你决定，也可以选择不保存。未来独立 session 在允许的条件下可能接收该 /memory snapshot。

It has one separate decision and two file operations (`list_dir`, `read_file`, `write_file`); SQL is absent. It can see only the task, agent-visible SQL feedback/trajectory, and `/memory`/`/work`, never a score, answer key, reference SQL, evaluator feedback, or researcher logs. Choosing not to write is valid. The step is common across F0/U0/F1/U1 and does not alter main-task scoring.

Every successful write produces runner-only `artifact.provenance`: path, content SHA-256, write tool-call ID, source attempt/episode/condition, snapshot ID/hash, and categories of evidence visible before writing. The agent cannot read these research records. Formal policy is frozen: F0/U0 snapshots are archived but not inherited; F1/U1 may mount only the immutable permitted `/memory` consolidation snapshot. Gate/calibration artifacts never enter formal samples.

## Independent viability gate

New pending artifacts:

- [public_viability_gate.pending.json](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_viability_gate.pending.json), SHA-256 `09629be1a8302661da8eb13eaba827850659d52903f946e1a7bc4d84e463eb01`.
- [public_viability_gate.authorization.pending.json](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_viability_gate.authorization.pending.json), pending only; `live_requests_authorized=false`.
- [public_viability_gate_run.py](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_viability_gate_run.py), SHA-256 `34d9f0e249394898c079ff30536da98fe43a212e50bec4c6b27f8014434cbc76`.

The gate has only two development-contacted sources: `viability-1-f0` (task 1) and `viability-2-u0` (task 2). It is not an F-vs-U result. It must stop after these two, including when neither writes an artifact.

GO requires all four conditions:

1. At least one submitted native `ANSWER` with an actually run native evaluator and recorded score.
2. At least one non-empty source `/memory` artifact from the common optional consolidation step.
3. No reference/evaluator leakage.
4. Complete terminal, native-score, snapshot/provenance, diagnostic-estimator, and formal-cutoff logs.

If no artifact exists after these frozen episodes, the outcome is **NO_GO**, not an expansion of the sample. Passing is only a measurement check, not learning evidence.

## Offline acceptance

Executed with the established Python 3.13 environment:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_viability_gate_run --plan-only \
  --output-root /private/tmp/public-viability-plan

benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m unittest experiments.experience_value.tests.test_public_viability_gate_run \
  experiments.experience_value.tests.test_public_calibration_run -v
```

The fake transport executes actual public task loading, 15 legal queries, empty-schema terminal decision, native `ANSWER`, native evaluator, consolidation, and frozen snapshot/provenance. Tests cover no sixteenth SQL; no 25th decision at a 24-decision cap; evaluator/reference non-leakage; optional no-write; F1/U1 snapshot mount semantics; and unauthorised live rejection before a provider request. A large legal SQL history makes the old diagnostic estimate exceed 24,000 while the formal estimate remains below it and reaches the fifteenth query. **19 tests passed.** Existing upstream SQLite resource warnings appeared in regression output; no test failed.

## Candidate envelope

Each episode has at most 24 main decisions (including terminal-only) plus one consolidation decision. With one allowed pre-response transport retry, two episodes permit at most 100 provider attempts.

```text
per attempt = (24,000 × 0.66 + 8,192 × 1.98) / 1,000,000 = USD 0.03206016
100 attempts = USD 3.20601600
```

The pending hard-cap proposal is USD 4.00: an upper-bound reservation, not authorization or expected spend. After a separate authorization only, the future live command would be:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_viability_gate_run --live
```

No live gate, formal 48+30 matrix, commit, push, or background work was started.
