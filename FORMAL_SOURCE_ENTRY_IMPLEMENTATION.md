# Formal source live-entry implementation

Status: **offline accepted; zero real provider requests; no Block 1 authorization created.**

## Entry and scientific diff

New entry: `experiments/experience_value/formal_source_run.py`.

Scientific diff: **NONE**. The entry consumes the already frozen formal protocol, source manifest, block-definition manifest, and formal pending configuration. It does not accept task IDs, conditions, episode lists, prompts, budgets, model parameters, or ordering on its CLI. It permits only `formal_source_block_01`, which derives positions 1–4 directly from `FORMAL_SOURCE_MANIFEST_V1.json`: `t07-F0`, `t07-U0`, `t07-F1`, `t07-U1`; position 5 is recorded as the next frozen position and is never started.

The runner reuses the public Database Exploration adapter, restricted tool loop, terminal-only ANSWER path, researcher-side native evaluator, deterministic experience generation/commit, RAW archive, workspace snapshots, price ledger, Asia/Shanghai off-peak guard, credential-free DNS/TLS/HEAD preflight, no-shim assertion, 120-second transport timeout, and one strict pre-response retry. A first durable provider dispatch consumes a future block authorization; pre-dispatch rejections do not.

F0/U0 start empty. F1/U1 task 7 start empty; the workspace API remains capable of cloning only same-condition formal predecessor snapshots for later task 8 and rejects writes to inherited immutable files. Development IDs 1–6 are rejected from the selected manifest before client construction; no development object is supplied as a parent snapshot.

## Offline acceptance

Executed with the CL-Bench Python 3.13 environment:

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m unittest \
  experiments.experience_value.tests.test_formal_source_run -v
```

Result: **3 tests passed, zero provider requests.** They drive the actual public adapter with fake transport, verify positions 1–4 and task-7 F0/U0/F1/U1 order, deterministic byte-equal commits, no position-5 start, unsigned live rejection before provider construction, empty F0 control memory, same-condition F1 task-8 clone behavior, and immutable inherited-file rejection. Existing public viability operational and deterministic-commit acceptance tests remain the reused verification for off-peak/preflight/no-shim/transport retry and consolidation/RAW isolation.

## Frozen bindings

- Formal protocol SHA-256: `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450`
- Source manifest SHA-256: `8dbbd43a711cff57d2b360d212995d15612610e3282e94ac33f31f9fb72f0a7e`
- Block definition SHA-256: `c54f6efabffad684c9612833a3151f6a2d60bec21dd75735ec394235fd24949a`
- Entry SHA-256: `931475e0c29952c29d700a570f15369b0dca4ec8dd0e2fb3977fb13cc3c7a001`
- Block pending: `experiments/experience_value/formal_source_block_01.pending.json`
- Block authorization pending: `experiments/experience_value/formal_source_block_01.authorization.pending.json`

The pending block is four source episodes, max 200 provider attempts (24 main + one consolidation decision, each with at most one transport retry), USD 7.00 hard cap, and `live_requests_authorized=false`. Its conservative reservation is USD 6.41203200.

## Future live command

Only after a separate bound authorization record is created:

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.formal_source_run \
  --pending experiments/experience_value/formal_source_block_01.pending.json \
  --authorization experiments/experience_value/formal_source_block_01.authorization.authorized_<timestamp>.json \
  --live
```

No Block 1 episode, receiver episode, or formal provider request ran during this implementation turn.
