# Formal Receiver Block R1 Authorization Report

## Authorization status

**AUTHORIZED_FORMAL_RECEIVER_BLOCK_01_NOT_DISPATCHED**

This authorization covers only the five frozen R1 entries below. It creates no
provider request, preflight, task reset, probe execution, evaluator call, or
consumption record.

| Receiver manifest position | Frozen token | Probe task ID | Resource |
| ---: | --- | ---: | --- |
| 1 | `t15-EMPTY` | 15 | `EMPTY` |
| 2 | `t15-M_F` | 15 | `M_F` |
| 3 | `t15-M_U` | 15 | `M_U` |
| 4 | `t15-RAW_F` | 15 | `RAW_F` |
| 5 | `t15-RAW_U` | 15 | `RAW_U` |

Each resource occurs once and the order is exactly the frozen receiver
manifest/plan order. R2–R6, source, calibration, viability, development,
smoke, and all extra episodes are **NOT_AUTHORIZED**.

## Frozen bindings and common configuration

All required frozen inputs were revalidated before authorization. The addendum
canonical hash is `96b033729af9768b6a5ebe6fe2c2a1436f13270161b8f2370dc2b3a7960c95e7`;
the canonical tool schema hash is
`cb9348286035ae1db212e0d5f737b3ced1ede25d7691c709f1cb0d2a914da4ce`.
`receiver_started=false` remains true in the sealed source state, and
`runner_scientific_diff_from_sealed_receiver_protocol = NONE`.

The five episodes bind the same model (`deepseek-v4-pro`), enabled low-effort
thinking, receiver prompt, schemas/permissions, 15 SQL and 8 file-operation
limits, 24 decisions, 24,000/8,192 token limits, estimator, terminal ANSWER
semantics, evaluator isolation, timeout/retry, ledger, and stop semantics.
The starting frozen resource is their only experimental difference and no
resource ID is agent-visible.

Resource bindings: EMPTY has zero files; M_F tree is
`2c5f05ac705b9e36489a479fd657b38c95e41fc949fbc5f3981b37db1d702348`; M_U
tree is `633d26c5badb50d5e7ae9d1626f1181fac7f98279bf787f2bb122dce8015fd50`
with no `experience_006.md`; RAW_F and RAW_U payload hashes are respectively
`0c8de1725a907eff3f7bf80ced429b2dacd3247e9e26f90c8efa012ee1288da3` and
`62a8baa1e801c2c4dfe72d77291330881623b2a0a39414f7c371ebddf9cb08e1`.
Every actual episode must create a fresh clone; sealed sources remain immutable.

## Cost and authorization artifact

- Worst-case R1 reservation: `$7.69443840`
- Independent R1 hard cap: `$8.00`
- Cross-block budget borrowing: prohibited
- Provider requests in this authorization turn: `0`
- Evaluator calls in this authorization turn: `0`
- R2 status: `NOT_AUTHORIZED`

Authorization: `experiments/experience_value/formal_receiver_block_01.authorization.authorized_20260929T121932+0800.json`

Authorization SHA-256:
`0c3ca4bbbafca5069bff334ea15296985a9b5650c2b103421d13c318d0dee522`

It binds the formal protocol, receiver manifest, analysis plan, addendum/seal,
source/resource seals, R1 plan/block, pending config, runner code, and shared
provider/tool/loop/evaluator/estimator/pricing/runtime hashes.
