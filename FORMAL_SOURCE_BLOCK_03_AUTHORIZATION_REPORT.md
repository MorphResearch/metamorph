# Formal Source Block 3 authorization

Status: **AUTHORIZED — not dispatched**  
`study_kind=formal_source_v1`  
`included_in_primary_analysis=true`

Codex made no network preflight, constructed no provider client, and sent
**0 provider requests**.

## Exact frozen block

| Position | Token | Task | Condition | Initial memory |
|---:|---|---:|---|---|
| 9 | `t09-F1` | 9 | F1 | task-8 F1 cumulative immutable snapshot |
| 10 | `t09-U1` | 9 | U1 | task-8 U1 cumulative immutable snapshot |
| 11 | `t09-F0` | 9 | F0 | empty |
| 12 | `t09-U0` | 9 | U0 | empty |

Position 13 is not authorized. The V2 entry can only execute the four listed
manifest positions and stops before Block 4.

## Verified immediate predecessors

Both accepted predecessors are from completed Block 2 run
`e0-53015e067721498eb3e8835b5dd3411d`, have
`study_kind=formal_source_v1`, `included_in_primary_analysis=true`, matching
protocol/manifest lineage, complete provenance, and no development or
evaluator/reference contamination.

| Receiver | Predecessor | Snapshot | Immutable files | Newest artifact SHA-256 |
|---|---|---|---|---|
| `formal-t09-f1` | `formal-t08-f1` | `snapshot-ee8a65216ecc4d958c431b99faa57de7` | `experience_001.md`, `experience_002.md` | `932695d5d343ecdff82f4b103daab7633df7f202234ae9ac9a33c013c8bd1b47` |
| `formal-t09-u1` | `formal-t08-u1` | `snapshot-ac297505188943c6b41a22876036d009` | `experience_001.md`, `experience_002.md` | `32901b6f21aa80e69fe95661176f53691158436f6bab8231dd22c1117352091d` |

F0/U0 were statically verified as empty-memory conditions. Cross-condition,
development/calibration/viability, RAW, evaluator/reference, researcher-log,
altered-snapshot, and external-memory inputs are rejected before provider
client construction.

## Frozen bindings and budget

| Object | SHA-256 |
|---|---|
| Formal protocol | `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450` |
| Source manifest | `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e` |
| Blocks definition | `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a` |
| V2 entry | `c3625f2ebf148de45e42facd2aa36f5bd537d6f505360ae93eb9f9a097a7efa9` |
| Block 3 pending | `ce018a59f7f0a79b9d0d056fb653c7513e12887f531e78318cfa5eaf0e61eee4` |
| Block 3 authorization | `adeff87dca76411fb69b657afc39060f53406e470440f663294dc91d4ab27f1e` |

- `scientific diff = NONE`
- Hard cap: USD 7.00
- Frozen worst-case transport-inclusive reservation: USD 6.41203200
- Live execution remains restricted to Asia/Shanghai 18:05--08:55.

## Sole live command

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v2 \
  --pending experiments/experience_value/formal_source_block_03.pending.json \
  --authorization experiments/experience_value/formal_source_block_03.authorization.authorized_20260928T211208+0800.json \
  --live
```
