# Formal Source Block 8 authorization

`study_kind=formal_source_v1`  
`included_in_primary_analysis=true`  
`scientific diff = NONE`  
`Codex provider requests = 0`

## Authorized frozen scope

| Position | Token | Task | Condition | Initial formal memory |
|---:|---|---:|---|---|
| 29 | `t14-U1` | 14 | U1 | Block 7 task 13 U1 cumulative snapshot |
| 30 | `t14-F0` | 14 | F0 | empty |
| 31 | `t14-U0` | 14 | U0 | empty |
| 32 | `t14-F1` | 14 | F1 | Block 7 task 13 F1 cumulative snapshot |

This is the final frozen source block. Position 33 does not exist; no additional source episode, receiver condition, probe, RAW receiver condition, or result analysis is authorized.

## Immediate predecessor lineage

F1 resolves to immediate task 13 F1 in Block 7 run `e0-3298ad04692e43a99ebcb57ba71ccb48`, snapshot `snapshot-ac03888be0f7466b9f1be44b82d4267b`, hash `175969862eb9a2370bfdfd392f19f94078d2fb675b405ea90f6caab23a52503c`. Its complete immutable memory tree is `experience_001.md` through `experience_007.md`; the new `experience_007.md` artifact provenance/content hash is `f5ba77c58c255b9c56b3985cf2ef58539e79faaa67df37b904ab7d5cc4d4ea6e`.

U1 resolves to immediate task 13 U1 in the same Block 7 run, snapshot `snapshot-2d99165456a041c1aa550a8aa6810ddb`, hash `678cd73dfcde7dd766f3b76142c5153f8bdfa092b9980094f8c446b39a7d9d08`. It contains exactly `experience_001.md`–`experience_005.md` and `experience_007.md`. `experience_006.md` is absent as a frozen historical fact and remains absent: it is neither fabricated nor renumbered, and the resolver does not fall back to task 12 or earlier snapshots.

Both references are same-condition, immediate-predecessor, `formal_source_v1`, primary-analysis included, snapshot/hash/provenance verified, and contamination-free. F0/U0 have no predecessor reference and are asserted to begin with empty `/memory`. The resolver pre-provider rejects cross-condition/skip lineage, altered or non-immutable snapshots, hidden additions/deletions/modifications, and development/calibration/viability/RAW/evaluator/reference/researcher material.

## Frozen bindings

- Formal protocol: `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450`
- Source manifest: `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e`
- Block definition: `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a`
- V3 entry: `168857fbb58d1566cfdc6ee780dca17c85f001d23f77aaccef7f995931c015cd`
- Block 8 pending: `df235218b9b0e591108f23b4f71381615410b47fed73b1c6f8bd4d83658815e3`
- Authorization: `c11b97a8d175b061e6cdfd1b64577a8bf7497357eaff55f90462311c92acff9a`

The new independent authorization is unused and binds only positions 29–32, the listed V3/runner/provider/task hashes, the two Block 7 predecessor identities, `USD 7.00` hard cap, and the Asia/Shanghai `18:05–08:55` off-peak window. Block 7 authorization remains consumed and is not reused.

## Static validation

The V3 plan-only path completed its full pending/authorization, manifest/block, and predecessor resolver checks without constructing a provider client or sending a provider request.

## User terminal command

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v3 \
  --pending experiments/experience_value/formal_source_block_08.pending.json \
  --authorization experiments/experience_value/formal_source_block_08.authorization.authorized_20260928T225534+0800.json \
  --live
```
