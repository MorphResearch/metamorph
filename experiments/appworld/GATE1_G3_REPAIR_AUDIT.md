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

## V3 artifact-finalization follow-up

The later, explicitly approved protocol-adapter repair in commit `fd7354d` separates
tool interaction from a tools-disabled JSON artifact-finalization request.  It neither
parses nor executes DSML-like content.  A fresh formal preflight and one fresh smoke
arm, `530b157_3 × G3 × seed 300`, were run under the isolated root
`dag_p1_formal_orchestrated_v3_20260907`; no v2 artifact was overwritten or reused.

The v3 selector finalized successfully in JSON mode.  The act node also finalized
successfully after its one permitted JSON-only correction retry.  The check node
performed its read-only interaction but stopped before its first finalization request
because the shared frozen token limit was exhausted (`145,986 / 150,000` tokens;
16 model calls, 21 tool calls).  All accounting and traces are present; there was no
provider exception, state race, or duplicate arm.  This is an auditable valid budget
stop, not repair evidence.  In particular, it still did not produce a
`VerifierArtifact(status=NOT_VERIFIED)`, repair artifact, or final-check artifact.

Therefore the Gate decision remains **NOT COMPLETE**.  The v3 smoke is excluded from
primary analysis and cannot be compared numerically with v2 because its protocol adds
terminal artifact-finalization calls.
