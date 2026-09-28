# Public calibration revision v2

Status: implemented and offline accepted. This turn sent **zero** provider
requests and made no paid evaluator calls.

`study_kind=development_public_calibration`

`included_in_primary_analysis=false`

## Only experimental configuration change

`max_output_tokens_per_request` changes from **2,048** to **8,192**. The input
budget remains 24,000 estimated tokens, and SQL (15), file operations (8),
provider requests (24 per episode / 144 batch), retries (0), thinking,
`reasoning_effort=low`, timeouts, task order, F/U prompts, tools, evaluator,
and token estimator are unchanged.

The change is a common development-calibration execution-space adjustment. It
addresses the historical `dev-1-f0` observation that a response ended with
`finish_reason=length` and empty visible content; it does not assert that 8,192
tokens will solve that task or favor either condition.

## Pricing and candidate cap

The official DeepSeek pricing page was rechecked at
`2026-09-24T11:01:30+08:00`. It lists `deepseek-v4-pro` off-peak cache-miss
input at USD 0.66/M and output at USD 1.98/M. The recalculation is:

`(24,000 × 0.66 + 8,192 × 1.98) / 1,000,000 = USD 0.03206016` per request.

At 144 requests the conservative upper bound is **USD 4.61666304**, below the
candidate hard cap of **USD 5.00**. This remains a proposed cap, not an
authorization or estimate of inevitable spend.

## Offline acceptance

The same public-calibration entry ran with fake transport and passed 9/9 tests:

- Every v2 fake provider request received `max_tokens=8192` at the actual
  provider-adapter boundary.
- F0/U0 shared the same request configuration; only their existing prompts
  differed.
- A fake `finish_reason=length` response was persisted, caused a
  `PER_EPISODE_RESOURCE_STOP` with `output_token_limit_reached`, and generated
  no automatic follow-up provider request for that episode.
- Input-token, SQL, file, request, and timeout resource-stop behavior remains
  per-episode; injected systemic failure remains batch-wide; unsigned live mode
  rejects before a provider request.
- The existing token estimator/context policy and evaluator/reference-feedback
  isolation tests remain in the same entry path.

Passed commands:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m unittest experiments.experience_value.tests.test_public_calibration_run -v
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m experiments.experience_value.public_calibration_run --plan-only --pending experiments/experience_value/public_calibration.revision_v2.pending.json --authorization experiments/experience_value/public_calibration.revision_v2.authorization.pending.json --output-root /private/tmp/public-calibration-revision-v2-plan-final
```

The public-task test process still emits its existing upstream SQLite connection
`ResourceWarning`; all tests exit 0. This revision does not broaden scope to
repair that unrelated lifecycle warning.

## Pending v2 record

- Pending config SHA-256:
  `a32963d29d401c88e89a4cef8a0b10592777e57668f100eb5fc3b96200df2a00`
- Pending authorization SHA-256:
  `a4f25a53bfa7bc9b1a58b53e580d08789fbec82646e9927128358c67b2bd3e0f`
- Task manifest SHA-256:
  `be6cb33cfa743d2bad98de52613b9c66e3411b2093c709598ed4fae9474c1b6a`
- Entry SHA-256:
  `7760e067dac1e62be3b27787aa879fac357ca14f535c7d769857180402551d6a`

After a new authorization binds these hashes, the live command would be:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_calibration_run --live \
  --pending experiments/experience_value/public_calibration.revision_v2.pending.json \
  --authorization experiments/experience_value/public_calibration.revision_v2.authorization.pending.json
```

The old revision files and all historical run evidence remain unchanged.
