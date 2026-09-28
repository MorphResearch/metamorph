# Public viability gate — operational wrapper revision

`study_kind=development_public_viability_gate`  
`included_in_primary_analysis=false`

## Scope

The previous viability entry correctly bound the two frozen development tasks,
but it could construct a provider client and begin an episode without the
already validated public-calibration operational guards.  In particular, it
had no timezone-aware non-peak check before client construction, no
credential-free DNS/TLS/HEAD preflight, no explicit real-LiteLLM/no-shim
rejection, and no uniform report for pre-dispatch exits or partially run
batches.  Those omissions made a live launch unsafe; they do not change a
scientific condition.

This revision changes only the operational wrapper in
[`public_viability_gate_run.py`](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_viability_gate_run.py).

## Frozen scientific configuration

The new pending file is
[`public_viability_gate.operational_v2.pending.json`](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_viability_gate.operational_v2.pending.json)
(`c995c0bea8baae087e4deb94e8919deecd889cfb0033283b13a3fe5577d3307e`).

Its scientific fields are unchanged from the prior viability candidate:

- Episodes and order: `viability-1-f0` / task 1 / F0, then `viability-2-u0` / task 2 / U0.
- Model, endpoint, thinking, low reasoning effort, 120-second request timeout,
  24,000 formal input cutoff, 8,192 output cap, 24 main decisions, 15 SQL,
  8 file operations, and one strict pre-response transport retry.
- Terminal-only ANSWER, native evaluator, provenance, optional consolidation
  (one decision, two file operations, no SQL), and the preregistered GO/NO-GO
  criteria.

The only new fields are operational: `offpeak_window`, credential-free
preflight, no-shim verification, dispatch-time authorization consumption, and
partial-run reporting.  The frozen task manifest is
[`public_viability_gate.tasks.md`](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_viability_gate.tasks.md)
(`63a759c611c4ea7a267d633572d2ba71b4074340c594fa90de4f7911366d1a8c`);
it contains no answer material.

## Operational behavior

- Asia/Shanghai is evaluated before client construction, before every provider
  attempt (including consolidation and the allowed transport retry), and before
  each new episode.  The signed window is 18:05–08:55.  Outside it, the entry
  writes `WAITING_OFFPEAK`, constructs no client, sends no completion, and does
  not consume authorization.
- Before client construction it performs credential-free DNS, verified TLS,
  and unauthenticated `HEAD https://api.deepseek.com/`.  Failure yields
  `PRECHECK_FAILED` / `INVALID_INFRA_PRECHECK`, with zero completions.
- It calls `DatabaseExplorationAdapter.assert_real_litellm_available()` before
  constructing the client.  A no-model shim yields `INVALID_SYSTEM`, with zero
  completions.
- A successful first `provider.request_started` persists consumption in the
  authorization record.  Pre-dispatch exits do not.  A second strict
  pre-response transport failure produces `INVALID_INFRA`, stops the batch,
  and explicitly records subsequent frozen episodes as `NOT_RUN`.
- Every live terminal state writes
  `PUBLIC_VIABILITY_GATE_RUN_REPORT.md`, including identity hashes, time and
  preflight evidence, both episode rows (including non-started rows), usage,
  cost/unknown-billing, evaluator and leakage fields, then the frozen gate
  outcome only.

## Offline verification

Executed with the isolated public-environment interpreter:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m unittest \
  experiments.experience_value.tests.test_public_viability_gate_run \
  experiments.experience_value.tests.test_public_viability_operational_v2 -v
```

Result: **11 tests passed**.  The tests use fake transports only.  They cover
the actual public task/SQL/native-evaluator/terminal/consolidation path, no
artifact as a legal choice, frozen GO and NO-GO logic, pre-dispatch window,
preflight and shim rejections with no authorization consumption, per-attempt
time checks including consolidation and retry, a complete `COMPLETED_NO_GO`
report, and a two-attempt `ReadTimeout` ending in
`INVALID_INFRA` with the remaining episode `NOT_RUN`.

The same entry also passed zero-request plan-only validation:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_viability_gate_run --plan-only \
  --output-root /private/tmp/public-viability-operational-plan
```

## Authorization and reservation

The new, deliberately unsigned record is
[`public_viability_gate.operational_v2.authorization.pending.json`](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_viability_gate.operational_v2.authorization.pending.json)
(`1217419bca52de764cbb1ef4a846ce3135f60980b8268d11e46cb84d497d552f`).
It binds the pending, task manifest, entry, live bridge, public adapter,
transport/provider client, loop, workspace, runner, and ledger hashes.  The
combined code hash is `b283906f4b05937f7c9461584f7199f4586d693f3a4807c800594e59dbe3b585`.

The official [DeepSeek price basis](https://api-docs.deepseek.com/quick_start/pricing/)
was rechecked on 2026-09-26 (off-peak cache-miss input USD 0.66/M and output USD
1.98/M), each 24,000-input / 8,192-output reservation is USD 0.03206016.
The 100-attempt transport-inclusive maximum is USD 3.206016, below the
candidate USD 4.00 hard cap.  This is a reservation proposal, not permission
to spend.

## Future live command

After a new explicit authorization record is created and hash-bound, the only
live command is:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_viability_gate_run --live
```

This revision sent **0 real provider requests**, started no viability gate,
and did not modify the prior pending, authorization, historical run, or formal
matrix.
