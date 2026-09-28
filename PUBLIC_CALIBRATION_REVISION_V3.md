# Public calibration revision v3

Status: implemented and offline accepted. This revision sent **zero** provider
requests and made no paid evaluator calls.

`study_kind=development_public_calibration`

`included_in_primary_analysis=false`

## Why revision-v2 did not finish six episodes

The preserved revision-v2 run `e0-29cffaa38a01474891c27b43644ae20b` started
in the signed off-peak window and passed its credential-free DNS/TLS/HEAD
preflight. `dev-1-f0` then completed 7 provider responses and reached the
native 15-query SQL limit, a normal per-episode resource stop. `dev-1-u0`
completed 8 provider responses; its ninth provider attempt ended with
`APITimeoutError` / `ReadTimeout` before a provider response or usage was
available. The ledger therefore retained that attempt as `billing_unknown` and
the frozen v2 policy stopped the whole batch. The four later frozen episodes
were not started. This is a client transport failure, not a task score, and no
historical raw/native field or run artifact has been changed.

## Only operational change

The request transport deadline is now **120 seconds** rather than 45 seconds.
Episode timeout remains 1,080 seconds. Model/task retries remain zero.

One transport-only retry is allowed only after the first attempt raises
`APIConnectionError`, `APITimeoutError`, `ConnectError`, or `ReadTimeout` with
no provider response, usage, model content, or tool call, and before any agent
state or tool side effect. It sends the same model, messages, tools, generation
options, token limits, and serialized-body hash. The retry is pre-reserved and
logged independently. A successful retry records `infra_recovered=true` and
its first failure chain; only its completed response counts as a model
decision. A second transport failure is `INVALID_INFRA`, retains both unknown
billing records, and stops the batch. No retry occurs after any provider
response, including `finish_reason=length`.

Unchanged: DeepSeek `deepseek-v4-pro`, thinking low, 24,000 estimated input
tokens/request, 8,192 maximum output tokens, 15 native SQL, 8 file operations,
24 model decisions/episode, task order, F/U prompts, tools, evaluator, token
estimator, and all task-level retries (zero).

## Frozen analysis outcome

These are new derived fields only; `native_score` and the upstream evaluator
output remain raw evidence.

| Situation | analysis_score | analysis_status |
| --- | --- | --- |
| Native evaluator ran | native_score | `EVALUATED_NATIVE` |
| No score after common SQL/input/output/request/file/episode-time limit | 0 | `RESOURCE_LIMITED_FAILURE` |
| No valid provider response after infrastructure failure | null | `INVALID_INFRA` |
| Systemic implementation, evaluator, or leakage failure | null | `INVALID_SYSTEM` |

Thus resource-limited episodes remain zero-valued in formal analysis rather
than becoming missing/excluded; infrastructure and system-invalid episodes do
not become task failures.

## Offline acceptance

The real public-calibration entry ran with fake transport:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m unittest experiments.experience_value.tests.test_public_calibration_run -v
```

All 12 tests passed. They cover one exact-body timeout retry and recovery,
second retry failure without a third request, no retry after length, all common
resource-stop analysis scores, infrastructure/system analysis nulls, F/U shared
120-second/retry configuration, reference-feedback isolation, and unsigned
live rejection before provider attempts. The existing upstream SQLite
connection `ResourceWarning` remains unrelated to this change.

The unsigned v3 plan path also completed with zero provider requests:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_calibration_run --plan-only \
  --pending experiments/experience_value/public_calibration.revision_v3.pending.json \
  --authorization experiments/experience_value/public_calibration.revision_v3.authorization.pending.json
```

## Cost proposal and pending binding

DeepSeek's official pricing page was checked at
`2026-09-26T22:14:12+08:00`: off-peak cache-miss input remains USD 0.66/M and
output USD 1.98/M. The request reservation is unchanged:

`(24,000 × 0.66 + 8,192 × 1.98) / 1,000,000 = USD 0.03206016`.

There are still at most 144 completed model decisions, but a transport retry
can make at most 288 provider attempts. The conservative transport-inclusive
reservation is therefore `288 × 0.03206016 = USD 9.23332608`. The v3 pending
record proposes a USD 10.00 hard cap; this is a candidate for new authorization,
not an authorization or an expected charge.

- Pending config SHA-256: `9bd79c33ae9b481ae2682b42929d80c80a4e525495c375f5109f2ac055bf40ca`
- Pending authorization SHA-256: `82abe2da5962a41b6437372b6388ce024e095bece73794855382a4ba0545b948`
- Task manifest SHA-256: `be6cb33cfa743d2bad98de52613b9c66e3411b2093c709598ed4fae9474c1b6a`
- Entry SHA-256: `6afa5e11a99752abe642286f623d2325f9251e223006e39b00e44a499ea18ed6`
- Transport/ledger implementation SHA-256: `230f94cb59baeebef43aa12b95b71c722bc3e4a4a2267d277934efe47917a134` /
  `5232ca863350de999752142ba878d91b579104f5fc262da2da7757c32d8de238`

The required independent authorization is still pending. If it is granted, the
frozen live entry is:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_calibration_run --live \
  --pending experiments/experience_value/public_calibration.revision_v3.pending.json \
  --authorization experiments/experience_value/public_calibration.revision_v3.authorization.authorized_<timestamp>.json
```
