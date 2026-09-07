# Gate-1 G3 repair-branch audit

Date: 2026-09-07  
Frozen orchestration commit: `c88d6af`  
Formal run root: `experiments/appworld/runs/dag_p1_formal_orchestrated_v2_20260906`  
Registry: `experiments/appworld/formal_run_registry.csv`

## Fixed scope

This audit did not modify the provider configuration, prompt, pricing, lambda values,
DAG implementation, or the frozen P1 task selection.  All rows below used seed 300
and the v2 formal orchestration.  They are engineering-smoke evidence only and are
excluded from primary analysis.

## Existing Gate-1 evidence

`6bdbc26_1` passed G0, G1, and G2 with `protocol_valid=true`.  The G2 trace already
contains independent `inspect_a` / `inspect_b` artifacts and a subsequent join.

`6bdbc26_1 × G3` completed with `protocol_valid=true`, complete accounting, and a
successful initial check.  Its `repair` and `final_check` nodes were therefore
`skipped_condition`.  This is valid evidence for the conditional-skip path, not for
the repair branch.

## Targeted G3 attempts

| task | result | repair-chain finding |
| --- | --- | --- |
| `4fab96f_1` | completed, protocol-invalid | Interrupted run had already finished; act and check had null artifacts / invalid contracts. No repair trigger or repair trace. |
| `3ab5b8b_1` | completed, protocol-invalid | Targeted smoke run; inspect, act, and check had invalid contracts. No `NOT_VERIFIED`, repair, or final-check trace. |
| `530b157_3` | completed, protocol-invalid | Targeted smoke run; inspect completed and act attempted execution, but act/check ended invalid-contract. No `NOT_VERIFIED`, repair, or final-check trace. |

All three have finished `run_state`, retained result/trace artifacts, token totals and
monotonic latency.  No infrastructure exception, state race, duplicate arm, or missing
run-state was observed.  Protocol-invalid model outputs remain failures and are not
silently counted as successful or zero-cost outcomes.

## Gate decision

**GATE-1 NOT COMPLETE.** G0--G2 are passed and G3 conditional skip is passed, but no
valid run demonstrates `check -> NOT_VERIFIED -> repair -> final_check`.  Per the
predeclared limit, no task is retried and no further G3 smoke arm is started.  P1 must
remain unstarted until this missing mechanism evidence is resolved under an explicitly
approved protocol decision; the frozen P1 manifest/config and profile-freeze boundary
remain unchanged.
