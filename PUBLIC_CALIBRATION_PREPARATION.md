# Public Database Exploration calibration preparation

Status: implemented and offline accepted. Real model requests and paid
evaluator requests this turn: **0**.

`study_kind=development_public_calibration`

`included_in_primary_analysis=false`

## Actual entry, interpreter, and shim policy

The entry is `experiments/experience_value/public_calibration_run.py`
(SHA-256 `d6ec0fd65f9f34d4642394d4ad06a3efaeb4c44a47b32143c7fe6fe8e02c5ded`).
It is a thin binding of the existing `ExperimentRunner`, workspace/snapshot
isolation, `run_tool_only_episode`, provider adapter, transcript writer,
`CostLedger`, and `DatabaseExplorationAdapter`; no parallel Agent framework was
created.

The local changes are limited to the public adapter, this entry/config/task/
pending-authorization set, its fake end-to-end test, and small optional loop/
tool-service extensions for independently metered tool groups and the frozen
input reservation. The original virtual environment and existing Atomic files
were not changed.

```bash
# passed, exit 0, zero provider requests
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_calibration_run --plan-only

# actual future live entry; exercised with pending authorization, exit 1 before client/provider construction
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_calibration_run --live
```

The interpreter is the repository-local CPython 3.13.15. Metamorph's original
`.venv` was unchanged. Required isolated-environment versions are:
`litellm 1.81.6`, `openai 2.16.0`, `pydantic 2.12.5`,
`huggingface-hub 1.32.0`, `httpx 0.28.1`, `tiktoken 0.14.0`, and
`tokenizers 0.23.2`.

The live path calls `DatabaseExplorationAdapter.assert_real_litellm_available()`
before `build_authorized_client`. It rejects a module without an installed
distribution/specification, so the older no-model LiteLLM shim cannot be used
for fake or live public calibration. The check returned real
`litellm=1.81.6` and `openai=2.16.0` without constructing a provider client or
making a request.

## Frozen candidate

| Input | SHA-256 |
| --- | --- |
| `public_calibration.pending.json` | `a946035999647f178302153aa10936f5cbf5921eae8562d45e9911d21721f64a` |
| `public_calibration.tasks.md` | `be6cb33cfa743d2bad98de52613b9c66e3411b2093c709598ed4fae9474c1b6a` |
| `public_calibration.authorization.pending.json` | `04f382abac81103d65e18f254530c8a23f7206ad72dd09a1ecc8da834c778326` |
| entry | `d6ec0fd65f9f34d4642394d4ad06a3efaeb4c44a47b32143c7fe6fe8e02c5ded` |
| public adapter | `efc6ee515af01da0f8ebbf5e23dc259a4a35ba9f3658e4725d085c7ed44c8a52` |
| `live.py` | `1f523d5de5bf782adf1abccbdb3a71dd8d511c03b38b427375a4615bd3c239f8` |
| `records.py` | `93a439ae288582dbc276f9bd48c54d1c8a67a50d79c7a5a2b25e5ae79b96ddb2` |
| `graphs/loop.py` | `954101943af7dc159c13bc738dc5237d474bfa11611382bdd8e9f8d1026003f2` |

The public source remains commit `5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26`,
pre-migration `products.db` SHA-256
`edf8ee80ff125de0bfd6c37a1d185efa9e3037ce28eb1bd1d32ae0829bd264a6`, and
`questions.json` SHA-256
`f98e515c14b74f4d30c29401fb79cca9ceeb15fe9ee2432b10265a4a649d1771`.

The pending authorization is independent, has `live_requests_authorized=false`,
zero real/provider/evaluator requests, and no 78-episode scope. It does not
reuse Atomic or any earlier authorization/balance.
It also binds the public adapter, live bridge, runner, workspace, records,
loop, provider adapter, and provider client hashes; any mismatch rejects before
provider construction.

## Six fixed development episodes

Every episode starts a fresh conversation with empty `/memory` and `/work`,
uses the same stable pre-migration database and restricted tool schema, and
receives no prior snapshot. Only the existing F0 fixed-workflow vs U0 autonomous
workflow text differs; the actual public task text for each F0/U0 task-ID pair
is the same.

| Order | Episode | Task | Condition | Fake prompt SHA-256 |
| ---: | --- | ---: | --- | --- |
| 1 | `dev-1-f0` | 1 | F0 | `27fc02d3ebaf90ed5e0f3c9616f1f1e04baa947b20379275f511b4ba6fc769de` |
| 2 | `dev-1-u0` | 1 | U0 | `4ad0aa47196905bb571483837bdad3edcf620932f44b4fb40cb3b2978ff85a9d` |
| 3 | `dev-2-u0` | 2 | U0 | `2ad91d1179e71e25a0bc3e5402bbb40b31704097eb59e4f274f27cb80a9465c7` |
| 4 | `dev-2-f0` | 2 | F0 | `ac8b27b9671bcdcb40756837ebcc62342bb6c2909b2b6873df2cedf19166d97e` |
| 5 | `dev-3-f0` | 3 | F0 | `c6a45d2f3fe416a233a0174477b5682971592a20114f3c1eab7b798629282693` |
| 6 | `dev-3-u0` | 3 | U0 | `a8d24b29d6ba5ebcf9d478df83edd0219ad3e85ac00a6c0d8cd7ac8880efc027` |

The common fake request-config hash is
`93186a1037e9aafc0866e504ecb39de20c82f293f4764828548348c5566c923f`.
IDs 4–6 are not run. This is calibration only, not an F/U result or selection
of a better condition; calibration artifacts remain outside formal sequences.

## Native semantics, budgets, and feedback isolation

`query_sql` maps to the actual public task `QUERY` action and preserves its
read-only SQLite results/errors, 10-second SQL timeout, row limit, and native
15-query allowance. The minimal loop extension enforces a 15-query SQL quota
and an independent aggregate 8-operation quota for `list_dir`/`read_file`/
`write_file`; neither category consumes or resets the other. Total dispatched
tools cannot exceed 23. Oversized file reads (>32,768 bytes) fail visibly rather
than truncate content.

At query 15 the task is still awaiting its final `ANSWER`; no 16th QUERY is
dispatched. The final model decision counts within the 24-request cap. If the
native task has already completed, the entry sends neither an extra QUERY nor a
duplicate ANSWER.

The final model text is passed once to native `ANSWER`, then the researcher-side
native evaluator runs. Terminal feedback may contain reference answers/SQL, so
the adapter returns only a completion notice and does not append that feedback
to a model message, transcript, `/memory`, RAW experience, or follow-up request.
Only aggregate evaluation fields are recorded. There is no post-evaluation
experience-organizing request, and the model receives no correctness supervision.

The separate researcher-side evaluator check was rerun with the same isolated
interpreter: a legal public SQL query was accepted; a verifier-only wrong answer
scored `0.0`/false and the verifier-only development answer scored `0.9333`/true.
The verifier's answer material was not placed in an adapter prompt, workspace,
memory, fake transport, or transcript.

## Same-entry fake end-to-end evidence

`test_public_calibration_run` uses a fake provider only. It still executes the
real public adapter, SQLite QUERY feedback, native ANSWER, evaluator, workspace,
snapshot, transcript, and ledger paths in an isolated temporary directory.

- Exactly six episodes, six distinct conversations/workspaces, and the frozen
  order passed.
- The representative F0 episode made one `list_dir` and one real SQL query.
  Task-2 U0 made exactly 15 real QUERY actions, then a terminal ANSWER in 16
  model decisions with `model_finished` termination.
- The fake batch had 36 model-loop decisions, 20 SQL queries, nine dispatched
  file actions, and one explicitly paired rejected ninth file proposal. The
  rejection did not consume the subsequent SQL slot or terminal-answer request.
  There were zero paid evaluator requests and no reference answer/SQL in fake
  provider messages or memory.
- Serialized request history ranged from 2,226 to 8,517 characters (2,232 to
  8,523 UTF-8 bytes). The frozen 24,000-character bound and enabled 24,000-byte
  conservative input-token reservation are above this observed path. If either
  is exceeded, the live path stops before dispatch: it does not truncate,
  summarize, or start a replacement conversation.
- Hash mismatch rejected before fake transport (zero requests); pending `--live`
  rejected before client/provider construction; an injected shim was rejected.

Passed commands:

```text
python -m unittest experiments.experience_value.tests.test_public_calibration_run -v  # 3 passed
python -m unittest discover -s experiments/experience_value/tests -p test_e0_acceptance.py -v  # 21 passed
python -m unittest experiments.experience_value.tests.test_file_positive_control_run -v  # 7 passed
python -m experiments.experience_value.verify_clbench_database_exploration \
  benchmarks/continual-learning-bench /private/tmp/public-calibration-native-evaluator-final  # exit 0
```

## Candidate cost envelope — not authorization

The candidate is direct DeepSeek `deepseek-v4-pro` at
`https://api.deepseek.com`, `DEEPSEEK_API_KEY`, thinking enabled with
`reasoning_effort=low`, temperature omitted, 45-second request timeout,
1,080-second episode timeout, 24,000 input-token reservation, 2,048 output
tokens, and zero application/SDK retries.

| Limit | Candidate |
| --- | ---: |
| Native SQL queries / episode | 15 |
| File operations / episode | 8, separate |
| Provider requests / episode | 24 |
| Episodes / batch | 6 |
| Provider requests / batch | 144 |
| Worst-case request reservation | USD 0.03979008 |
| Worst-case batch reservation | USD 5.72977152 |
| Suggested hard cap | USD 6.00 |

Pricing is the official DeepSeek page checked 2026-09-21, using its peak
cache-miss input rate USD 1.32/M and peak output rate USD 3.96/M. The upper
bound is `(24,000 × 1.32 + 2,048 × 3.96) / 1,000,000 × 144`. It is not expected
spend or permission to run, and deliberately does not reuse Atomic's 512-token
output limit or USD 0.20 cap.

## Remaining prerequisites

1. A new signed authorization must bind these same config/task/code hashes,
   DeepSeek model/endpoint, six episodes, zero retries, and USD 6.00 cap.
2. A live batch must stop on a limit, unknown billing, native completion, or
   infrastructure fault; it cannot add a finalization request, task, retry, or
   episode.
3. There is still no verified Agent code-execution sandbox. This is tool-only:
   saved files are static artifacts, not executable skills.

Atomic was not modified or rerun. No real model, paid evaluator, 78-episode
batch, provider client call, commit, push, or background task was started.
