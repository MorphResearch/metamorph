# Formal Source Block 6 authorization

**AUTHORIZED — not dispatched.** `scientific diff = NONE`; Codex provider requests: **0**.

| Position | Token | Task / condition | Initial memory |
|---:|---|---|---|
| 21 | `t12-U0` | 12 / U0 | empty |
| 22 | `t12-F1` | 12 / F1 | only task-11 F1 final cumulative snapshot |
| 23 | `t12-U1` | 12 / U1 | only task-11 U1 final cumulative snapshot |
| 24 | `t12-F0` | 12 / F0 | empty |

Position 25+ is not authorized. F1 uses `formal-t11-f1` snapshot `snapshot-d4f4b05def374d6aa9bc0cdf81eb401f`; U1 uses `formal-t11-u1` snapshot `snapshot-665b386530fe49d18e1753aa1cf0c5b8`, both from Block 5 run `e0-dc6e03395e4a4aa7b86c52430d97bda2`. V2 verified same-condition immediate predecessor, formal lineage, snapshot/provenance hashes, cumulative immutable memory, and contamination exclusions. F0/U0 were verified empty.

Bindings: protocol `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450`; manifest `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e`; blocks `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a`; V2 `c3625f2ebf148de45e42facd2aa36f5bd537d6f505360ae93eb9f9a097a7efa9`; pending `2883af5bd294cf9c0d9da78dc5e5c0e4262e78b2c083325d2a5a971cae5c7ddc`; authorization `27f07fe9ab449cb0cb2cf1ebc2afb35edd3fe663b0901bf3057115947cd9d3b0`.

Hard cap: USD 7.00. Frozen worst-case reservation: USD 6.41203200. The live entry performs the frozen off-peak, preflight, no-shim, hash, and authorization checks.

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v2 \
  --pending experiments/experience_value/formal_source_block_06.pending.json \
  --authorization experiments/experience_value/formal_source_block_06.authorization.authorized_20260928T221145+0800.json \
  --live
```
