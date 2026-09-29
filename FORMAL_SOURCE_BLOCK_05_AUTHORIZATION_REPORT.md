# Formal Source Block 5 authorization

Status: **AUTHORIZED — not dispatched**. `scientific diff = NONE`; Codex provider requests: **0**.

| Position | Token | Task / condition | Initial memory |
|---:|---|---|---|
| 17 | `t11-F0` | 11 / F0 | empty |
| 18 | `t11-U0` | 11 / U0 | empty |
| 19 | `t11-F1` | 11 / F1 | only task-10 F1 final cumulative snapshot |
| 20 | `t11-U1` | 11 / U1 | only task-10 U1 final cumulative snapshot |

Position 21+ is not authorized.

F1 uses `formal-t10-f1` snapshot `snapshot-c90ff68145e344f8ad5a587b93bea595`; U1 uses `formal-t10-u1` snapshot `snapshot-1622e0756fe34f66975a199ae85107f1`, both from formal Block 4 run `e0-3430b92d62f0472aac17f2f07a917052`. The V2 resolver statically verified their same-condition immediate-predecessor lineage, snapshot/provenance hashes, cumulative immutable `experience_001.md`--`experience_004.md`, and contamination exclusions. F0/U0 are empty-memory conditions.

Bindings: protocol `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450`; source manifest `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e`; blocks `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a`; V2 entry `c3625f2ebf148de45e42facd2aa36f5bd537d6f505360ae93eb9f9a097a7efa9`; pending `cdd156f65af53f6814bb1ee6ba2c2139d10a33e9820aa04b3744889c25f66693`; authorization `beda4c0e4c155098c62d60fd15a432f965c303e4c8cafd90ff2baa397d54f0ff`.

Hard cap: USD 7.00. Frozen worst-case reservation: USD 6.41203200. Live is restricted to the Asia/Shanghai frozen off-peak window.

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v2 \
  --pending experiments/experience_value/formal_source_block_05.pending.json \
  --authorization experiments/experience_value/formal_source_block_05.authorization.authorized_20260928T220047+0800.json \
  --live
```
