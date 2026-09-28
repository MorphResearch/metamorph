# Formal Source Runner V2 implementation

Status: **offline accepted; no live authorization created**  
`scientific diff = NONE`

## Scope and historical traceability

Block 1 remains historical formal data executed by
`formal_source_run.py` (SHA-256
`931475e0c29952c29d700a570f15369b0dca4ec8dd0e2fb3977fb13cc3c7a001`).
It was not edited, rerun, or reinterpreted.

The new [formal_source_run_v2.py](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/formal_source_run_v2.py)
(SHA-256 `c3625f2ebf148de45e42facd2aa36f5bd537d6f505360ae93eb9f9a097a7efa9`)
is the intended common entry for Blocks 2--8.  This is an operational
correctness revision: V1 deliberately accepted only Block 1 and always
started a source episode with no parent snapshot, so it could not safely run
the frozen F1/U1 inheritance protocol at task 8.

## V2 architecture

V2 reads a block ID exclusively from block-scoped pending configuration, then
resolves contiguous positions and tokens from the frozen source manifest and
block definition. It has no CLI for episode, task, or condition selection and
stops after that block's final manifest position.

For F0/U0, V2 rejects any predecessor reference and starts empty. F1/U1 task
7 also start empty. For every later F1/U1 task, V2 requires exactly one
immediate same-condition predecessor output snapshot; it never merges files
from all earlier tasks. Before constructing a provider client it validates:

- protocol and manifest lineage, formal study flags, predecessor task and
  condition, and Block-authorization/run linkage;
- output snapshot tree hash, committed artifact bytes/hash, and provenance;
- absence of development mount and evaluator/reference visibility;
- all provenance paths remain inside the formal runner's research roots.

Inherited snapshot files are cloned into a fresh session as immutable memory.
The episode may only add its allocated `experience_NNN.md`; a `NO_MEMORY`,
empty, or protocol-invalid consolidation retains all inherited files in its
new output snapshot for the next immediate predecessor link.

## Block 2 frozen resolution

| Position | Token | Initial memory |
|---:|---|---|
| 5 | `t08-U0` | empty |
| 6 | `t08-F1` | only task 7 F1 immutable snapshot |
| 7 | `t08-U1` | only task 7 U1 immutable snapshot |
| 8 | `t08-F0` | empty |

Position 9 is excluded. The two verified formal predecessor sources are both
from Block 1 run `e0-e808a2e0f18a4eccad1e69f0d5d70f9c`:

| Receiver | Predecessor snapshot | `experience_001.md` SHA-256 |
|---|---|---|
| F1 | `snapshot-c2e5d0df8d7f45bdb43d27f7ffb9f995` | `56ef6d03541168dd9eda2a02820fbc788ff2477ad187df1e07540c383f61ff71` |
| U1 | `snapshot-d0eb99e062e14024bcdc0dc7c9d4aeee` | `c19b252e079de0ece47d38a3009755533cf4d10d49b5b6a3481f9b7d0436896f` |

Development IDs 1--6, calibration/viability objects, RAW, evaluator outputs,
reference material, researcher logs, cross-condition snapshots, altered
snapshots, and externally specified memory paths are all rejected before any
provider client can be constructed.

## Offline acceptance

The verified Python 3.13 environment ran:

```text
python -m unittest \
  experiments.experience_value.tests.test_formal_source_run_v2 \
  experiments.experience_value.tests.test_formal_source_run \
  experiments.experience_value.tests.test_public_viability_operational_v2 -v
```

Result: **14 tests passed**. Coverage included Block 1 V2 parsing with empty
memory, an actual Block 2 fake-transport execution, immutable F1/U1 inherited
files plus new `experience_002.md`, changed/cross-condition/missing
predecessor rejection, unsigned-live rejection, all eight frozen block
definitions, task-9 cumulative snapshot simulation, and the operational
wrapper regression suite.

The same V2 entry also completed a `--plan-only` pass for Block 2 with zero
provider requests, yielding only positions 5--8 and next position 9.

## Pending objects and hashes

| Object | SHA-256 |
|---|---|
| Formal protocol | `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450` |
| Source manifest | `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e` |
| Block definition | `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a` |
| [Block 2 pending](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/formal_source_block_02.pending.json) | `4c920437d8135d0efb836c6127732d56b376ea79b3f2aebf2b48d0580aaf396b` |
| [Block 2 authorization pending](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/formal_source_block_02.authorization.pending.json) | `ea2d2c133d73857da2ab4fd8eb922015926465279480d9eac3e5471d9eef464e` |

The Block 2 pending reservation is USD 6.41203200 under the frozen pricing
inputs and remains below its candidate USD 7.00 cap. It has
`live_requests_authorized=false`; no `authorized_*.json` exists.

## Future live command template

Only after a separate Block 2 live authorization is created and bound to
these hashes, the sole command template is:

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run_v2 \
  --pending experiments/experience_value/formal_source_block_02.pending.json \
  --authorization experiments/experience_value/formal_source_block_02.authorization.authorized_<timestamp>.json \
  --live
```

Codex provider requests in this implementation-and-acceptance run: **0**.
