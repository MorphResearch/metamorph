# Formal Source Block 7 authorization

`study_kind=formal_source_v1`  
`included_in_primary_analysis=true`  
`scientific diff = NONE`  
`Codex provider requests = 0`

## Authorized scope

| Manifest position | Frozen token | Task | Condition | Formal initial memory |
|---:|---|---:|---|---|
| 25 | `t13-F1` | 13 | F1 | Block 6 task 12 F1 CASE A snapshot |
| 26 | `t13-U1` | 13 | U1 | Block 6 task 12 U1 CASE B output snapshot |
| 27 | `t13-F0` | 13 | F0 | empty |
| 28 | `t13-U0` | 13 | U0 | empty |

Only positions 25–28 are authorized. Position 29 and all later source entries, Block 8, receiver work, calibration, viability, development, and smoke requests are excluded. The block stops after position 28.

## Predecessor verification

F1 is CASE A and resolves to Block 6 run `e0-dbae883e65154899b20be4a9d9cd20ba`, episode `formal-t12-f1`, snapshot `snapshot-9786f4a81f194eec85b9ee4b2073ed37`, hash `1f79e1b47bb13a6fc4e6ec4e24e24014aa729a3ccafe07c4f011681df4b99af9`. It contains immutable `experience_001.md` through `experience_006.md`; `experience_006.md` has provenance/content hash `1c6a1902e02ca49d4ddc12475a2206ee0cbfdc2b48ca4fd4af0a72d97a20bb54`.

U1 is CASE B and resolves to Block 6 run `e0-dbae883e65154899b20be4a9d9cd20ba`, episode `formal-t12-u1`. It binds the retained, verified output snapshot `snapshot-665b386530fe49d18e1753aa1cf0c5b8`, stored in the Block 5 run `e0-dc6e03395e4a4aa7b86c52430d97bda2`, with hash `7009a08bdc7ef78ec20200dca1825eaf77637f055c92bac940854feb8b8b7686`. Its input and output immutable `/memory` trees match byte-for-byte and contain exactly `experience_001.md` through `experience_005.md`. No `experience_006.md` is fabricated; the resolver preserves the immediate task 12 lineage rather than falling back to task 11 or clearing memory.

F0 and U0 have no predecessor references and are statically asserted to start with empty `/memory`.

The V3 resolver rejects cross-condition or skipped lineage, altered snapshots, hidden additions, deletions, modifications, writable inherited files, development/calibration/viability paths, RAW, and evaluator/reference/researcher material before provider-client construction.

## Frozen bindings

- Formal protocol: `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450`
- Source manifest: `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e`
- Block definition: `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a`
- V3 entry: `168857fbb58d1566cfdc6ee780dca17c85f001d23f77aaccef7f995931c015cd`
- Block 7 pending: `32035ebd4990823318991aaa8f481f8fdf000af3dbac68d0844e3bef87990795`
- Authorization: `a8c2d20c5c25fb0addab78ee9cdd2c53f35f2eb5ff1ac06b802d073f6c8c27a0`

The authorization is independent of the consumed Block 6 authorization, has hard cap `USD 7.00`, is unused (`real_model_requests_sent_under_this_authorization=0`), and permits execution only in the frozen Asia/Shanghai `18:05–08:55` off-peak window. It includes the required runner, loop, workspace, ledger, provider, task/database, and predecessor bindings.

The historical runner binding remains V1 for Block 1 and V2 for Blocks 2–6. Block 7 alone is bound to V3; historical runs were not modified.

## Static check

The V3 plan-only path verified the signed authorization, V3 dependency hashes, frozen manifest/block mapping, and CASE A/CASE B resolver. It created no provider client and sent zero provider requests.

## User terminal command

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v3 \
  --pending experiments/experience_value/formal_source_block_07.pending.json \
  --authorization experiments/experience_value/formal_source_block_07.authorization.authorized_20260928T224139+0800.json \
  --live
```
