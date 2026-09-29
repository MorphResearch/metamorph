# Formal Source Block 4 authorization

Status: **AUTHORIZED — not dispatched**  
`study_kind=formal_source_v1` · `included_in_primary_analysis=true` · `scientific diff = NONE`

Codex sent **0 provider requests** and did not construct a provider client.

| Position | Token | Task / condition | Initial memory |
|---:|---|---|---|
| 13 | `t10-U1` | 10 / U1 | only task-9 U1 final cumulative snapshot |
| 14 | `t10-F0` | 10 / F0 | empty |
| 15 | `t10-U0` | 10 / U0 | empty |
| 16 | `t10-F1` | 10 / F1 | only task-9 F1 final cumulative snapshot |

Position 17 and later are not authorized.

## Immediate-predecessor checks

| Receiver | Block 3 predecessor | Snapshot | Cumulative immutable files | Newest artifact SHA-256 |
|---|---|---|---|---|
| `formal-t10-f1` | `formal-t09-f1` / `e0-9794526fea7b42f0906109faa8839faf` | `snapshot-8d13454e7f6c4cc29758d1e573740148` | `experience_001.md`--`experience_003.md` | `1a534025cd97480e324c087e8c009f99fc69431b3ba7627efe6835dc34f87e9c` |
| `formal-t10-u1` | `formal-t09-u1` / `e0-9794526fea7b42f0906109faa8839faf` | `snapshot-4f009377824c4a699e8c032fbf8d8278` | `experience_001.md`--`experience_003.md` | `e37cd39c3c4d0a4e47b6e4940fb8114519032dc99683f2dcd4c18286404e6007` |

F0/U0 were validated as empty-memory. The V2 resolver revalidated formal lineage, cumulative snapshot/artifact hashes, same-condition immediate predecessors, provenance, and contamination exclusions before the provider path. Cross-condition, development/calibration/viability, RAW, evaluator/reference, researcher-log, altered-snapshot, and external-memory sources are rejected pre-provider.

| Binding | SHA-256 |
|---|---|
| Protocol | `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450` |
| Source manifest | `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e` |
| Block definition | `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a` |
| V2 entry | `c3625f2ebf148de45e42facd2aa36f5bd537d6f505360ae93eb9f9a097a7efa9` |
| Block 4 pending | `6c7fe9574aa8d864cb22bff619beec5904f15f2cd116e12d60cbf82f6eb0f22d` |
| Block 4 authorization | `1f2315b0c18ac43a77b5ef4b1be9fdb97dbc140e53b7a00f7b31b91e8638af89` |

Hard cap: USD 7.00. Frozen worst-case reservation: USD 6.41203200. Live execution is restricted to the frozen Asia/Shanghai off-peak window.

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v2 \
  --pending experiments/experience_value/formal_source_block_04.pending.json \
  --authorization experiments/experience_value/formal_source_block_04.authorization.authorized_20260928T214148+0800.json \
  --live
```
