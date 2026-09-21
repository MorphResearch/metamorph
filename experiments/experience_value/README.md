# Experience-value E0 harness

This is a deliberately small, offline-first harness for the Day-1 E0
engineering acceptance. It is not an E1/E2 result runner and it does not
construct an LLM provider during import, collection, dry-run, or tests.

The four development conditions are `F0`, `U0`, `F1`, and `U1`. `F` currently
means `prompt_prescribed_v0`: the same single-agent loop gets a phase-oriented
prompt, rather than a controller that enforces stages. The only legal
cross-task channel is an agent-visible `/memory` clone. `/work` is fresh for
every task. Frozen snapshots, logs, fixture databases, source provenance, and
hidden evaluator material remain outside the agent's logical file interface.

The local SQLite fixture is engineering smoke data only. Its IDs are local,
its data are synthetic, and it is never a CL-Bench result or primary-analysis
input. There is no verified code-execution sandbox in this repository, so
arbitrary agent code execution is intentionally absent and marked `BLOCKED`.

Commands actually verified for this implementation:

```bash
python -m unittest experiments.experience_value.tests.test_e0_acceptance -v
python -m experiments.experience_value.runner --output-root /private/tmp/metamorph-e0-plan --plan-only
```

The second command writes a 78-episode, zero-request dependency plan (E1 48
plus E2 30); it does not create task episodes or use an API. A live smoke is
not exposed as a casual CLI command. It requires a caller to provide an
explicitly validated `LiveAuthorization` with provider, exact model, currency,
hard cap, request limit, and price basis, plus all E0 gate checks.

