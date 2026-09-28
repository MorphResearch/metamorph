# Public experience-commit revision

Status: **PENDING_USER_SIGNOFF — zero real provider requests in this revision.**

`study_kind=development_public_viability_gate`  
`included_in_primary_analysis=false`

## Scope

The completed operational-v2 viability gate remains `NO_GO_FOR_EXPERIENCE_TRANSFER` and is not modified. Its consolidation audit found two different layers: `viability-1-f0` had no usable visible consolidation text (`B_CONSOLIDATION_GENERATION_FAILURE`), while `viability-2-u0` produced non-empty reusable-looking visible text but did not call `write_file` (`A_ARTIFACT_COMMITMENT_FAILURE`). The latter means the old artifact measure conflated experience generation with remembering to use a file tool.

This revision changes only that measurement interface. It leaves the public tasks, F/U workflows, model, thinking mode, formal and diagnostic input estimators, 15-query native limit, 24 main decisions, terminal ANSWER interface, output cap, transport timeout/retry, native evaluator, and off-peak/preflight/no-shim wrapper unchanged.
It does not require a change to the scientific question: the measured construct is now explicitly the agent's visible generated experience text, rather than a compound of that text and a file-tool action.

## Consolidation construct and deterministic commit

Each source episode still receives exactly one consolidation model decision after the main task and before native evaluation. It has an empty tool schema: no SQL and no file tools. Its common prompt is:

> 根据你在当前任务中实际观察到的信息，输出一份简短、可能对未来类似任务有帮助的可复用经验文本。内容由你自行决定。如果你认为没有任何值得保留的经验，请只输出：NO_MEMORY。不要尝试调用工具，也不要继续查询环境。

The runner treats the provider-visible output as follows:

- Non-empty text other than exact trimmed `NO_MEMORY`: commits the exact UTF-8 bytes to the episode's allocated `/memory/experience_NNN.md`.
- Exact trimmed `NO_MEMORY`: no artifact; records `voluntary_no_memory=true`.
- Empty visible content: no artifact; records `consolidation_generation_failure=true`.
- Any tool call: rejects without dispatch or retry; records protocol-invalid consolidation.

The runner never edits, summarizes, titles, validates, or augments the committed text. A committed file's hash must equal the SHA-256 of the raw visible content. This is a measurement/interface commitment fix, not performance tuning: it measures generated externalized experience, not tool-call recall.

The allocated paths are episode-unique (`experience_001.md`, `experience_002.md`, …). Snapshot files inherited by a permitted F1/U1 session are read-only to agent file writes; a later source can add only its own allocated file. F0/U0 snapshots are archived and start the next source from empty memory. Gate and calibration snapshots are declared ineligible for any formal sample.

## Provenance and RAW baseline

For every deterministic artifact, research-only provenance records source episode and condition, provider response/reservation ID, raw-content hash, committed-file hash, path, frozen snapshot hash, timestamp, the available evidence categories, and `evaluator_or_reference_visible=false`. The agent cannot read that provenance.

Before consolidation, the runner archives a research-only immutable `RAW_source_episode` payload containing only the agent-visible task, model messages, tool calls, SQL feedback, and main terminal answer when present. It excludes evaluator output, reference SQL/answer, researcher logs, and consolidation output. RAW is never mounted by default; it is reserved for the preregistered common receiver conditions `RAW_F` and `RAW_U`, not M_F/M_U transfer.

## Native metric audit

`viability-2-u0`'s `native_score=0.0` and `correct=1.0` is **A — upstream normal definition**, not an adapter mapping error. In the upstream Database Exploration evaluator, `correct`/`accuracy` describes answer correctness, whereas `TaskResult.score` is `1 - normalized_regret`, driven by query efficiency. The run used all 15 permitted queries, yielding score zero despite accuracy one. Protocols and reports will retain both fields with these meanings; no historical score is rewritten and no answer material was exposed to an agent.

## Offline verification

Executed with the isolated CL-Bench Python 3.13 interpreter:

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python -m unittest \
  experiments.experience_value.tests.test_public_experience_commit_revision \
  experiments.experience_value.tests.test_public_viability_operational_v2 \
  experiments.experience_value.tests.test_public_viability_gate_run -v
```

Result: **17 tests passed; zero provider requests.** The tests cover byte-for-byte commit/hash equality, `NO_MEMORY`, empty visible content, tool-call rejection without dispatch/retry, unique immutable paths, F0/U0 non-inheritance, allowed F1/U1 snapshot inheritance, RAW non-mounting/no evaluator visibility, terminal ANSWER behavior, formal-versus-diagnostic cutoff behavior, and existing off-peak/preflight/no-shim/retry protections. An unsigned v3 live invocation rejects before any provider attempt; a separately simulated signed v3 invocation exercises the same operational wrapper with a fake transport only.

## Frozen candidate

- Pending: `experiments/experience_value/public_viability_gate.experience_commit_v3.pending.json`
  - SHA-256: `3ff57258fbac867fe4cd9261c3926c5f7b6de49edc7fb8e18069a37356fde463`
- Pending authorization: `experiments/experience_value/public_viability_gate.experience_commit_v3.authorization.pending.json`
- Task manifest SHA-256: `63a759c611c4ea7a267d633572d2ba71b4074340c594fa90de4f7911366d1a8c`
- Entry SHA-256: `4ad6bc58c7804b86b9afeaa812c97e508e7a0754311b1583e8a96781b6fa129f`
- Live bridge SHA-256: `0573543a1b24f568e918c9e8fcf9cc54ff361af927c299383147efd79f4858dc`
- Loop SHA-256: `220718303d4c570e373e108befa908f3978212650de393494193be58595fc5f0`
- Workspace SHA-256: `8c46ac35f5b17acf0b1965604feda4933ea1a832112588d5c9b99fcbdee0f82b`

Compared with operational-v2, the pending changes only the consolidation/commit, immutable-snapshot, RAW-baseline, authorization/status, and consequent ledger reservation fields. No main-task scientific parameter changes.

## Future viability gate (not executed)

The candidate remains two development-contacted episodes only: `viability-1-f0` and `viability-2-u0`. It retains the existing GO criterion: at least one native ANSWER/evaluation, one non-empty committed artifact whose bytes equal the provider-visible text, complete snapshot/provenance/estimator logs, no evaluator/reference leakage, and documented native metric semantics. Artifact content quality and score magnitude are not gate criteria.

DeepSeek's pricing page was rechecked on 2026-09-27: off-peak `deepseek-v4-pro` cache-miss input is USD 0.66/M and output is USD 1.98/M. With 24,000 input and 8,192 output tokens, each provider attempt reserves `(24000×0.66 + 8192×1.98)/1e6 = USD 0.03206016`. Two episodes permit up to 50 logical decisions (24 main + 1 consolidation each) and, with one strict transport retry per decision, at most 100 attempts: **USD 3.206016** conservative reservation. The proposed USD 4.00 cap is not authorization. [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/)

After a separate user authorization creates a bound authorized copy, the only live command would be:

```bash
benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.public_viability_gate_run \
  --pending experiments/experience_value/public_viability_gate.experience_commit_v3.pending.json \
  --authorization experiments/experience_value/public_viability_gate.experience_commit_v3.authorization.authorized_<timestamp>.json \
  --live
```

No viability gate, formal matrix, receiver experiment, or provider request was run here.
