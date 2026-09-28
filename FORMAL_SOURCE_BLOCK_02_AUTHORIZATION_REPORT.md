# Formal Source Block 2 authorization check

Status: **NOT_AUTHORIZED — pre-provider implementation rejection**

`study_kind=formal_source_v1`  
`included_in_primary_analysis=true`

No provider client was constructed, no credential-free network preflight was
run, and Codex sent **0 provider requests**.

## Frozen manifest binding

The frozen source manifest and block definition resolve Block 2 to exactly:

| Manifest position | Token | Task | Condition |
|---:|---|---:|---|
| 5 | `t08-U0` | 8 | U0 |
| 6 | `t08-F1` | 8 | F1 |
| 7 | `t08-U1` | 8 | U1 |
| 8 | `t08-F0` | 8 | F0 |

Position 9 (`t09-F1`) is outside Block 2 and is not authorized.

## Required predecessor linkage: provenance check passed

The only eligible predecessors are in the completed formal Block 1 run
`e0-e808a2e0f18a4eccad1e69f0d5d70f9c`:

| Receiving condition | Required predecessor | Snapshot | Artifact | Artifact SHA-256 |
|---|---|---|---|---|
| F1 | `formal-t07-f1` | `snapshot-c2e5d0df8d7f45bdb43d27f7ffb9f995` | `/memory/experience_001.md` | `56ef6d03541168dd9eda2a02820fbc788ff2477ad187df1e07540c383f61ff71` |
| U1 | `formal-t07-u1` | `snapshot-d0eb99e062e14024bcdc0dc7c9d4aeee` | `/memory/experience_001.md` | `c19b252e079de0ece47d38a3009755533cf4d10d49b5b6a3481f9b7d0436896f` |

F0 and U0 must start with empty `/memory`; neither may mount a Block 1
artifact. Development IDs 1–6, calibration/viability artifacts, RAW, and
researcher/evaluator/reference records remain excluded.

## Blocking implementation discrepancy

The current live entry is still deliberately Block-1-only:

- It accepts only pending status
  `PENDING_FORMAL_SOURCE_BLOCK_01_USER_SIGNOFF_NO_LIVE_CALLS`.
- It rejects every `block_id` other than `formal_source_block_01`.
- It additionally hard-requires positions 1–4 and the four task-7 tokens.
- Each episode calls `prepare_task(...)` without a parent snapshot and emits
  `inheritance_source=null`; hence task 8 F1/U1 cannot receive the verified
  eligible immutable predecessor.

Creating a Block 2 live authorization against that entry would authorize a
run that either rejects before dispatch or silently violates the frozen F1/U1
inheritance protocol. Therefore no `formal_source_block_02.pending.json`,
no pending authorization, and no authorized live record were created.

## Hashes checked

| Object | SHA-256 |
|---|---|
| Formal protocol | `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450` |
| Source manifest | `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e` |
| Block definition | `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a` |
| Current formal source entry | `931475e0c29952c29d700a570f15369b0dca4ec8dd0e2fb3977fb13cc3c7a001` |

## Scientific diff

`NONE` — no scientific field, task, prompt, budget, metric, or historical
run was changed. The required next action is an explicitly authorized
operational entry revision plus offline inheritance validation; it must bind
a new code hash before Block 2 can be authorized.
