# Formal Receiver Live Entry V2 Implementation

## Status

V1 intentionally had only `--plan-only`; therefore its R1 authorization was
never consumed and is superseded solely because it bound the older runner hash.
V2 adds live orchestration only. It imports the sealed V1 bindings and does not
alter model, prompt, schemas, permissions, budgets, estimator, terminal
semantics, evaluator contract, resources, block order, accounting, hard cap,
or failure semantics.

`runner_scientific_diff_from_sealed_receiver_protocol = NONE`

- Provider requests: `0`
- Native evaluator calls: `0`
- `probe_content_read=false`
- `receiver_started=false`
- DNS/TLS/HEAD preflight: not run

## V2 contract

[`formal_receiver_run_v2.py`](experiments/experience_value/formal_receiver_run_v2.py)
supports exactly `--plan-only` and `--live --pending PATH --authorization PATH`.
Before client construction, live validates the pending/authorization state,
pending and V2 code hashes, frozen protocol/manifest/addendum/seal/resource
bindings, exact R1 positions/tokens, unused authorization, and `$8.00` cap.
It runs only the pending block, never accepts a CLI episode list, and ends with
R2 `NOT_STARTED`.

After validation it reuses the sealed Asia/Shanghai guard, credential-free
preflight, no-shim guard, provider client, shared agent loop, exact schemas,
formal estimator, terminal-only SQL15 semantics, public adapter, evaluator
isolation, ledger, transport retry, unknown-billing stop, and hard-cap logic.
The first provider completion path consumes authorization; preflight failure
and any pre-dispatch stop leave it unused. A consumed authorization cannot be
reused.

## Offline acceptance

```text
.venv/bin/python -m unittest experiments.experience_value.tests.test_formal_receiver_run_v2 -v
Ran 3 tests — OK
```

The fake-live test uses a temporary synthetic authorization, transport, and
task adapter. It traverses V2 live orchestration for all five frozen R1 tokens,
fresh sessions and resource clones, terminal ANSWER/evaluator isolation, no
consolidation, first-dispatch consumption, `$8` ledger path, block stop, and no
R2 start. Rejection tests cover unsigned/wrong pending/wrong token scope and
consumed reuse at zero dispatch; preflight failure remains unconsumed;
plan-only remains zero-request. No real task 15–20 body was read.

## Artifacts

| Artifact | SHA-256 |
| --- | --- |
| V2 runner | `a8c6a0bfdb4299cbd59e4d78a9c8be47a32367798e26c154080b42e16f63a252` |
| R1 V2 pending | `a9252cf8c3550aeb47ac98625c80d8b6a2d24411a851c7333f5efe991050c9cb` |
| R1 V2 pending authorization | `3c9ff685bac2c6e43bb07ed5295484af45f06403139dd7bee25f607281883cef` |

The V2 pending files set `live_requests_authorized=false`; no authorized V2
copy exists. The old authorization supersession is recorded in
`FORMAL_RECEIVER_BLOCK_01_AUTHORIZATION_SUPERSESSION.md`.
