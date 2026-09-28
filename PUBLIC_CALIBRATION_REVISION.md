# Public calibration revision: token budget and batch-stop semantics

Status: implemented and offline accepted. This revision sent **zero** provider
requests and made no paid evaluator calls.

`study_kind=development_public_calibration`

`included_in_primary_analysis=false`

## dev-1-f0 score audit

Classification: **A — model/Agent completion failure, not a public-interface or
evaluator bridge failure.** The saved `dev-1-f0` trace contains nine successful
SQL actions and no SQL-tool error. Its sixth provider response had
`finish_reason=length` with empty text; the runner consequently sent an empty
ANSWER (its saved SHA-256 is the empty-content hash) to the real upstream
adapter. The native task marked that ANSWER complete with reward `0.0`, and the
native evaluator returned score `0.0` / accuracy `0.0`.

The trace therefore does not support changing the F0 prompt, adapter format, or
evaluator. No reference answer was used to reconstruct a task solution, and the
historical run was not changed.

## Corrected unified budget

The prior candidate reserved price using 24,000 **input tokens**, but also
enforced a 24,000-character pre-request stop. Those are different units; the
character branch caused the historical `dev-1-u0` stop. The revised candidate
has one research input budget: **24,000 estimated input tokens per request**.

The unchanged common limits are 2,048 output tokens, 15 SQL actions per
episode, eight file operations per episode, 24 provider requests per episode,
144 provider requests per six-episode batch, and application/SDK retries of
zero. Characters and UTF-8 bytes are retained as diagnostic fields only; they
cannot independently stop an episode. The 24,000-token budget is an artificial
uniform compute budget, not a claim about the provider's context capacity.

## Estimator and error evidence

The isolated environment has no cached exact DeepSeek tokenizer. The live path
therefore uses deterministic estimator
`calibrated_utf8_half_bytes_plus_chat_tool_overhead_v1` (version `1`):

`ceil(UTF-8 bytes of the serialized messages plus tool schema / 2) + 32 × message count + 64 × tool count`.

It evaluates the whole request, including the tool schema. For every completed
provider request the event and redacted transcript record the estimator name and
version, estimated tokens, diagnostic character/byte counts, returned
`prompt_tokens`, and `actual_prompt_tokens - estimated_tokens`. This is an
explicit operationally conservative estimate, not an assertion of exact DeepSeek
tokenization; returned usage is retained to calibrate its error before later
authorization decisions.

## Stop semantics

The following now produce `PER_EPISODE_RESOURCE_STOP`, preserve the current
episode's evidence, and continue the frozen sequence in a fresh session with
empty `/memory` and `/work`: input-token budget, output-token limit, provider
request limit, SQL limit, file-operation limit, and episode timeout. No current
episode receives extra tools, requests, or a finalization allowance.

The following stop the entire batch: provider/infrastructure failure, unknown
billing, authorization or hash mismatch, permission/security violation,
reference/evaluator leakage, workspace/snapshot contamination, batch USD cap,
or a confirmed systemic implementation/evaluator fault. Native terminal feedback
remains researcher-side only and is not returned to the model, memory, or a
later request.

## Same-entry offline acceptance

Using CPython 3.13 and fake transport through the public adapter, real SQLite
QUERY path, native evaluator path, workspace manager, snapshot logic, records,
and ledger:

- A message above 24,000 characters but below 24,000 estimated tokens passed
  the estimator; character length did not stop it.
- A synthetic public SQL feedback payload pushed the next request to at least
  24,000 estimated tokens. It emitted `provider.request_blocked` before a
  second provider call, recorded a per-episode resource stop, and began the
  next episode with a new conversation and no parent snapshot.
- Query limit (15) and file-operation limit (8) stopped only their episodes;
  the fake batch still expanded all six frozen episodes in order.
- An injected systemic adapter error stopped the entire batch after the first
  episode. Hash mismatch and unsigned live mode continued to reject before a
  provider request.
- F0/U0 had the same request-config hash and common limits. Fake provider
  messages contained neither ground-truth nor reference SQL.

Commands (all exit 0):

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m unittest experiments.experience_value.tests.test_public_calibration_run -v
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m experiments.experience_value.public_calibration_run --plan-only --pending experiments/experience_value/public_calibration.revision.pending.json --authorization experiments/experience_value/public_calibration.revision.authorization.pending.json --output-root /private/tmp/public-calibration-revision-plan
```

The test process emitted existing upstream SQLite `ResourceWarning` messages for
unclosed task connections, but all eight public-calibration tests passed. This
revision did not broaden scope to repair that unrelated upstream lifecycle
warning.

## New pending configuration and cost envelope

- Revised pending config SHA-256:
  `4389fd84ca2eaeb5ad85dfcd7925d03212a172aa716694e2a071c4979be35ee2`
- Pending authorization SHA-256:
  `1eb60320451b01461d7b908dc70623f80e77eed7b761aa0ee66faea337bc5e61`
- Task manifest SHA-256:
  `be6cb33cfa743d2bad98de52613b9c66e3411b2093c709598ed4fae9474c1b6a`
- Entry SHA-256: `395c4d9a23bf9eba65148b56c07963d9928b4bc3859f271a684af4c84b971036`

The official DeepSeek page checked on 2026-09-22 still lists off-peak
`deepseek-v4-pro` rates of USD 0.66/M cache-miss input and USD 1.98/M output.
The frozen upper bound remains
`(24,000 × 0.66 + 2,048 × 1.98) / 1,000,000 × 144 = USD 2.86488576`.
The candidate hard cap remains USD 3.00; it is a proposal only, not an
authorization.

Future live invocation, after a new authorization binds these hashes, would be:

```text
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_calibration_run --live \
  --pending experiments/experience_value/public_calibration.revision.pending.json \
  --authorization experiments/experience_value/public_calibration.revision.authorization.pending.json
```

No historical run, authorization, transcript, prompt, task, tool definition,
or evaluator was overwritten.
