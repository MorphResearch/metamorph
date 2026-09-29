# Formal Source Block 2 authorization

Status: **AUTHORIZED — not dispatched**  
`study_kind=formal_source_v1`  
`included_in_primary_analysis=true`

This authorization was created from the user's Block 2-only authorization on
2026-09-28. Codex performed no DNS/TLS preflight, constructed no provider
client, and sent **0 provider requests**.

## Authorized frozen block

| Manifest position | Token | Task | Condition | Initial memory |
|---:|---|---:|---|---|
| 5 | `t08-U0` | 8 | U0 | empty |
| 6 | `t08-F1` | 8 | F1 | only verified task-7 F1 snapshot |
| 7 | `t08-U1` | 8 | U1 | only verified task-7 U1 snapshot |
| 8 | `t08-F0` | 8 | F0 | empty |

Manifest position 9 (`t09-F1`) and all later source positions are explicitly
outside this authorization. The entry stops after position 8 and does not
authorize a receiver, calibration, viability, smoke, development task, or
Block 3+ execution.

## Verified predecessor linkage

| Receiving episode | Formal predecessor | Snapshot | Artifact SHA-256 |
|---|---|---|---|
| `formal-t08-f1` | Block 1 run `e0-e808a2e0f18a4eccad1e69f0d5d70f9c`, `formal-t07-f1` | `snapshot-c2e5d0df8d7f45bdb43d27f7ffb9f995` | `56ef6d03541168dd9eda2a02820fbc788ff2477ad187df1e07540c383f61ff71` |
| `formal-t08-u1` | Block 1 run `e0-e808a2e0f18a4eccad1e69f0d5d70f9c`, `formal-t07-u1` | `snapshot-d0eb99e062e14024bcdc0dc7c9d4aeee` | `c19b252e079de0ece47d38a3009755533cf4d10d49b5b6a3481f9b7d0436896f` |

The V2 resolver revalidated these output snapshots, their committed artifact
bytes, formal-run/authorization lineage, same-condition immediate-predecessor
relationship, and contamination flags before any provider-client path. F0/U0
were verified to have no predecessor. Cross-condition, development,
calibration/viability, RAW, evaluator/reference, researcher-log, altered, and
external-memory sources are rejected pre-provider.

## Frozen bindings

| Object | SHA-256 |
|---|---|
| Formal protocol | `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450` |
| Source manifest | `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e` |
| Source blocks | `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a` |
| Block 2 pending | `4c920437d8135d0efb836c6127732d56b376ea79b3f2aebf2b48d0580aaf396b` |
| V2 entry | `c3625f2ebf148de45e42facd2aa36f5bd537d6f505360ae93eb9f9a097a7efa9` |
| Block 2 authorization | `5f60275b7512a260cd973943ec68171b1c346111ed68b8f766d4873912bd8e0e` |

`scientific diff = NONE`. Block 1 remains bound to the unmodified V1 entry
and its consumed authorization. Block 2 is bound to V2 and starts with zero
authorization consumption.

## Budget

- Hard cap: **USD 7.00**.
- Frozen worst-case transport-inclusive reservation: **USD 6.41203200**.
- Live execution remains restricted to the frozen Asia/Shanghai
  18:05--08:55 off-peak window; V2 performs its own time, credential-free
  preflight, no-shim, hash, and authorization checks before dispatch.

## Sole live command

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v2 \
  --pending experiments/experience_value/formal_source_block_02.pending.json \
  --authorization experiments/experience_value/formal_source_block_02.authorization.authorized_20260928T205253+0800.json \
  --live
```
