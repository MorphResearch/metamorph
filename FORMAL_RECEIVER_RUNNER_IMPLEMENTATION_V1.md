# Formal Receiver Runner Implementation V1

## Status

**OFFLINE IMPLEMENTATION AND ACCEPTANCE COMPLETE — NO FORMAL RECEIVER EXECUTION**

`runner_scientific_diff_from_sealed_receiver_protocol = NONE`

This supersedes the earlier pre-addendum audit. The sealed receiver protocol is
the original receiver manifest plus Formal Receiver Protocol Addendum V1. No
source seal, receiver resource, receiver manifest, or addendum was modified.

- Formal provider requests: `0`
- Formal native evaluator calls: `0`
- Real probes opened: `0`; `probe_content_read=false`
- `receiver_started=false`; live authorization created: `false`

The fake R1 integration test uses only an injected synthetic transport and
synthetic task/evaluator. Its five test-fixture evaluator callbacks are not
formal native evaluator calls; it never calls `DatabaseExplorationAdapter.reset`
or opens task 15–20 content.

## Revalidated sealed bindings

The runner rejects with `FROZEN_BINDING_MISMATCH` before client/task setup if a
binding changes. It revalidates formal protocol, receiver manifest, analysis
plan, addendum JSON/Markdown/seal, source seal, resource manifest, all bound
source runtime hashes, M_F/M_U trees, RAW payloads, source completion `32/32`,
and `receiver_started=false`.

| Binding | Verified SHA-256 |
| --- | --- |
| Addendum canonical | `96b033729af9768b6a5ebe6fe2c2a1436f13270161b8f2370dc2b3a7960c95e7` |
| Tool schema canonical | `cb9348286035ae1db212e0d5f737b3ced1ede25d7691c709f1cb0d2a914da4ce` |
| Source seal canonical | `f6a1ca4f44a5f0d6720ace90b8634b11d5e03b9025e715ca364fcb52fa100d46` |
| Resource manifest canonical | `6ea6e4b1054f387a394ab2c3c2e71a0ca93a2b7f1235444b1a6a72589a6d96bf` |
| M_F / M_U trees | `2c5f05ac705b9e36489a479fd657b38c95e41fc949fbc5f3981b37db1d702348` / `633d26c5badb50d5e7ae9d1626f1181fac7f98279bf787f2bb122dce8015fd50` |
| RAW_F / RAW_U payloads | `0c8de1725a907eff3f7bf80ced429b2dacd3247e9e26f90c8efa012ee1288da3` / `62a8baa1e801c2c4dfe72d77291330881623b2a0a39414f7c371ebddf9cb08e1` |

## Exact common receiver and isolation

[`formal_receiver_run.py`](experiments/experience_value/formal_receiver_run.py)
uses the shared frozen schema, loop, ledger, workspace, estimator/pricing
bridge, and public-adapter binding. The common configuration is exactly:
`deepseek-v4-pro`, thinking with low effort, 24 decisions, SQL 15, file ops 8,
24,000/8,192 token limits, 120/1,080-second timeouts, one pre-response retry,
and disabled consolidation. It uses the sealed estimator
`ceil(diagnostic * .5) + 256`, stopping pre-dispatch at `>=24000`.

Each episode receives a fresh conversation, task state, `/work`, `/memory`
clone, transcript, and ledger. The only variable is starting resource content;
resource IDs are absent from the agent prompt. EMPTY has zero files; M_U retains
the absent `experience_006.md`; RAW bytes are cloned unchanged. Mount and use
are distinct: only a successful resource `read_file` records `resource_used`.
Source resource tree hashes are checked before and after each clone.

The shared terminal implementation supplies one empty-schema decision after
SQL15 only if fewer than 24 decisions were used. It forbids SQL16, decision25,
rescue/finalization calls, evaluator feedback, post-evaluation requests, and
consolidation. A native score is missing unless one accepted native ANSWER
exists. Per-attempt reservation is `$0.03206016`; independent 5-episode
reservation is `$7.69443840`, capped at `$8.00`; unknown billing stops a block.

## Operational outputs

| Artifact | SHA-256 |
| --- | --- |
| `formal_receiver_run.py` | `38ac4988b5a7ae021e479f9bbfb00dc84a8ba2aac84ba84ca1d362b7b162b644` |
| `FORMAL_RECEIVER_EXECUTION_PLAN_V1.json` | `477ba457795d696e95d198276a94d5e6ee8e972d225dabada9d14e2c31b588bb` |
| `FORMAL_RECEIVER_BLOCKS_V1.json` | `0440bc8b9c93ba4427bc8b718d2a08a2224a5c22894dbfecabdabe3eeef269cc` |
| R1 pending | `30d3ec99a47f678cff08c774391dfcb2ca061c5f61662e929e4d98d30a3d5574` |
| R1 pending authorization | `5a06457f4934f574be25a3f021088b83ae364b5f8f7023cd074586ac6a7c4f86` |

The plan mechanically expands the exact 30-token manifest order without probe
bodies. Blocks R1–R6 exactly preserve the sealed five-item groups and do not
autostart successors. R1 contains only `t15-EMPTY`, `t15-M_F`, `t15-M_U`,
`t15-RAW_F`, and `t15-RAW_U`.

Both pending files set `live_requests_authorized=false`, provider/evaluator
calls to zero, and `probe_content_read=false`. They bind protocol, manifest,
analysis plan, source seal, resource manifest, addendum/seal, plan, block
definition, entry code, schema, shared loop, provider/estimator/pricing,
evaluator, workspace, and the `$8.00` cap. No `authorized_*.json` exists.

## Offline acceptance

```text
.venv/bin/python -m unittest experiments.experience_value.tests.test_formal_receiver_run -v
Ran 4 tests — OK
```

The tests cover source/resource/addendum/schema/pricing/estimator bindings;
30-token expansion and R1–R6 mapping; EMPTY and exact M_F/M_U/RAW cloning;
M_U gap; source immutability; five fresh fake sessions; resource-label hiding;
mount-versus-use evidence; one-answer/evaluator isolation; no consolidation or
post-evaluation request; SQL15 terminal-only with no SQL16/decision25;
plan-only zero requests; and unsigned-live rejection before provider setup.
Runner and tests also passed Python compilation.

No R1 execution, DNS/TLS/HEAD preflight, provider call, native evaluator call,
live authorization, commit, or push occurred. Completion stops here.
