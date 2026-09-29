# Formal Source Runner V3 implementation

`scientific diff = NONE`  
`provider requests during this revision = 0`

## Scope

V3 adds [formal_source_run_v3.py](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/formal_source_run_v3.py). It leaves the historical V1 and V2 runners unchanged:

- V1 SHA-256: `931475e0c29952c29d700a570f15369b0dca4ec8dd0e2fb3977fb13cc3c7a001`
- V2 SHA-256: `c3625f2ebf148de45e42facd2aa36f5bd537d6f505360ae93eb9f9a097a7efa9`
- V3 SHA-256: `168857fbb58d1566cfdc6ee780dca17c85f001d23f77aaccef7f995931c015cd`

V2 incorrectly required every formal immediate predecessor to have a new artifact provenance record. That conflicts with the frozen protocol: a F1/U1 episode may finish without adding an artifact while its inherited immutable `/memory` remains a valid output state.

## Operational resolver rule

CASE A keeps V2's existing checks: a new artifact must have matching provenance, response/content hash, snapshot hash, and immutable cumulative snapshot contents.

CASE B accepts no new artifact only when all of the following hold before a provider client is built:

- the predecessor is same-condition, immediate prior formal source task, `formal_source_v1`, primary-analysis eligible, and in the same frozen protocol/manifest lineage;
- its formal record and consumed authorization bind to its recorded run;
- contamination and evaluator/reference-visibility checks are false;
- its output snapshot is hash-verified;
- its input and output agent-visible `/memory` trees have exactly the same relative paths, sizes, byte hashes, and read-only flags; and
- the input snapshot itself resolves to the immediate preceding formal output record and authorization, rather than an external snapshot.

The physical snapshot can be retained from the prior run when no source episode writes memory. V3 separately binds the predecessor record run and the snapshot storage run; it does not fall back across task lineage.

## Block 6 U1 regression

`formal-t12-u1` in `e0-dbae883e65154899b20be4a9d9cd20ba` is a valid CASE B predecessor for task 13 U1:

- outcome: `RESOURCE_LIMITED_FAILURE`; no new artifact provenance;
- output hash: `7009a08bdc7ef78ec20200dca1825eaf77637f055c92bac940854feb8b8b7686`;
- output storage snapshot: `snapshot-665b386530fe49d18e1753aa1cf0c5b8` in Block 5 run `e0-dc6e03395e4a4aa7b86c52430d97bda2`;
- retained immutable files: `experience_001.md` through `experience_005.md`.

The resolver verifies byte continuity to the task 11 U1 output snapshot. It neither fabricates `experience_006.md`, empties memory, nor skips task 12.

The matching Block 6 F1 predecessor is CASE A and retains the V2 provenance checks for `experience_006.md`.

## Block 7 binding

The new pending configuration resolves exactly these frozen manifest entries:

| Position | Token | Task | Condition | Initial memory |
|---:|---|---:|---|---|
| 25 | `t13-F1` | 13 | F1 | Block 6 task 12 F1 CASE A snapshot |
| 26 | `t13-U1` | 13 | U1 | Block 6 task 12 U1 CASE B snapshot |
| 27 | `t13-F0` | 13 | F0 | empty |
| 28 | `t13-U0` | 13 | U0 | empty |

Position 29 is outside the block and cannot be selected. Development, calibration, viability, RAW, evaluator/reference, and researcher-log material remain excluded by the resolver's formal-run roots and provenance checks.

## Offline verification

Executed with the isolated Python 3.13 environment:

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m unittest \
  experiments.experience_value.tests.test_formal_source_run_v3 \
  experiments.experience_value.tests.test_formal_source_run_v2 \
  experiments.experience_value.tests.test_public_viability_operational_v2 -v
```

Result: `17` tests passed. The V3 suite verifies real Block 6 CASE A/CASE B resolution, Block 7 scope, empty F0/U0 memory, fake end-to-end execution through position 28 only, unsigned-live rejection, and no provider use for plan-only. It also checks rejection of wrong/cross-condition lineage and changed, added, deleted, or writable inherited files. A synthetic Block 8 forward simulation validates the same continuity path for `NO_MEMORY`, resource-limited, and consolidation-generation-failure outcomes.

The checked-in Block 7 plan-only command also completed with zero provider requests.

## Frozen pending artifacts

- [Block 7 pending](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/formal_source_block_07.pending.json): SHA-256 `32035ebd4990823318991aaa8f481f8fdf000af3dbac68d0844e3bef87990795`
- [Block 7 authorization pending](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/formal_source_block_07.authorization.pending.json): SHA-256 `2a4b1544366e34756178e80b09db1742d483f2b4f26741c43f307f9672d89f75`

Both retain `live_requests_authorized=false`. No `authorized_*.json` was created.

## Future live command template

After a separate user authorization creates an authorized copy, the only live command is:

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v3 \
  --pending experiments/experience_value/formal_source_block_07.pending.json \
  --authorization experiments/experience_value/formal_source_block_07.authorization.authorized_<timestamp>.json \
  --live
```

V3 reuses V2's off-peak, credential-free preflight, no-shim, transport retry, billing, hard-cap, evaluator, consolidation, deterministic commit, RAW, and report path. The V3 authorization is consumed only after the first real provider dispatch; V3 mirrors that dispatch to its own authorization record while retaining V2 solely as an internal loop bridge.
