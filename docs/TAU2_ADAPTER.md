# τ²-Bench Adapter

`adapters/tau2_adapter.py` connects the metamorph routing arms and legacy S0--S4 conditions to the
official τ²-Bench v0.2.0 `Environment`, `Orchestrator`, and evaluator.

## Conditions

| Condition | Adapter behavior |
| --- | --- |
| S0 | Always use one agent with the complete assistant tool set. |
| Complex-only | Always use the selected complex controller (default S3). |
| Adaptive | Hidden planner/router selects S0 or the selected complex controller. |
| Oracle | A human-authored task label selects S0 or the selected complex controller. |
| S1--S4 | Legacy complex-controller ablations. |

The executor accepts only validated write tools plus the explicit
`transfer_to_human_agents` fallback allowlist. A planner cannot call a write
tool, and a verifier cannot call a write or fallback tool.

## Smoke test

Run one τ² mock task through the four routing conditions:

```bash
benchmarks/tau2-bench/.venv/bin/python scripts/run_tau2_adapter_smoke.py \
  --domain mock \
  --task-id create_task_1
```

The default conditions are `S0 Complex-only Adaptive Oracle`; use
`--conditions S0 S1 S2 S3 S4` for the legacy ablation matrix.

The result is written to
`benchmarks/tau2-bench/data/simulations/metamorph_adapter_smoke.json`.

The smoke runner records official τ² reward, termination reason, token usage,
assistant tool calls, phase events, and replay hash agreement. It does not use a
second scoring implementation.

## Scope limitation

S3/S4 currently implement an isolated replay of the selected action and check
that its copied-environment DB hash agrees with the official execution. This is
safe for a smoke test, but it is not yet the final planner-edge masking
ablation. The full experiment should add a frozen-context, masked-handoff
replay while keeping the official task state isolated.
