# Consolidation commitment audit

Scope: read-only audit of completed public viability run
`e0-cadce996332b4dcab4900c83c3ac1bb9`.

No provider request was sent for this audit.  This report does not modify the
historical run, native evaluator result, task answer, or reference material.
The conclusions below use only the model-visible consolidation request and its
response, tool events, run JSON, and immutable output snapshots.

## Shared consolidation boundary

Both episodes received exactly one consolidation request after main execution
and before researcher-side evaluation.  Its tool schema exposed only
`list_dir`, `read_file`, and `write_file`; no SQL schema was exposed.  The
visible input comprised the common system tool-policy message, the current
task text, the agent's own prior assistant/tool trajectory, agent-visible SQL
feedback, and the empty `/memory` and `/work` state.  For task 2 it also
included the agent's own terminal ANSWER text as part of that trajectory.
Neither request contained a native score, correct answer, reference SQL,
evaluator output, research diagnosis, or a prior source artifact.

## Per-episode evidence

### `viability-1-f0` / task 1 / F0

- Consolidation request identifier: ledger reservation
  `3e0a24b4c0ec4796acc2262ce6b76b19`; request-body hash
  `114cde7c90133ad376fe969ecfa7d5c353ad27e001b35ee5f1f382e22c17fdab`.
- Response: `finish_reason=tool_calls`; `completion_tokens=4411`;
  `reasoning_tokens=4321`; visible content length `0` (SHA-256 of empty text:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
  No visible reasoning text was returned.
- It proposed one `query_sql` call, despite the consolidation schema.  The
  runner recorded it as outside the allowlist; it did not reach the public SQL
  environment.  File-tool counts are list/read/write proposed `0/0/0` and
  successful/dispatched file operations `0/0/0`.
- No text expresses a voluntary choice not to save.  No non-empty reusable
  experience text exists.  Final `/memory` snapshot is empty
  (`e3b0c442…b855`); no provenance item exists.

**Failure class: `B_CONSOLIDATION_GENERATION_FAILURE`.** The response consumed
almost all completion tokens as reasoning tokens, exposed no usable ordinary
text, and then attempted an unavailable capability.  The evidence does not
support `C_VOLUNTARY_NO_MEMORY`.

### `viability-2-u0` / task 2 / U0

- Consolidation request identifier: ledger reservation
  `520e91f2095344e6b0e1c89dafa1a311`; request-body hash
  `c507d9d60527dd97a8aa46b4754ffd68edab23c1fc5422ae9a85da9e6763aeba`.
- Response: `finish_reason=stop`; `completion_tokens=5254`;
  `reasoning_tokens=4959`; visible content length `1003`; visible-content
  SHA-256 `d9654d729ede1506a48959bfe6758909b5bd64efc6d1c82e0b0316d17b36d2b2`.
  It made no tool call: list/read/write proposed and dispatched counts were
  all zero.
- Visible text is non-sensitive and was a task-analysis summary: it identifies
  the `g1` dataset as office products, records that `main_cat` is unreliable,
  gives a reusable query pattern joining `fdbk_g1` with `items_g1` and filtering
  `prc > 50`, and states the task's final numeric answer.  It does not say
  “do not save” or give a reason for declining persistence.
- This is not a generic polished experience note, but it is non-empty,
  interpretable model-visible text with potentially reusable schema/query
  information.  The final `/memory` snapshot is nevertheless empty
  (`e3b0c442…b855`); no provenance item exists.

**Failure class: `A_ARTIFACT_COMMITMENT_FAILURE`.** The model supplied visible,
potentially reusable text but did not invoke `write_file`; it did not
explicitly choose not to retain it.

## Failure-layer conclusion

The run has one instance of A and one of B, not two voluntary non-saves.  Thus
the completed gate establishes neither a successful artifact-commitment path
nor evidence that the current prompt measures voluntary memory production.
It does establish that the model can emit reusable-looking ordinary text in
the consolidation position without committing it to `/memory`.

No `C_VOLUNTARY_NO_MEMORY` classification is supported.  `D_UNKNOWN` is not
needed because both outcomes have direct transcript and event evidence.

## Minimal measurement/interface changes to consider — not implemented

For the observed A case, the narrowest commitment fix is to treat consolidation
as an **experience generation decision**: preserve the same one model decision
and consolidation prompt, then deterministically save non-empty ordinary
response text byte-for-byte as `/memory/experience.md`.  The runner must not
edit, summarize, add, evaluate, or correct the text.  Empty visible content
creates no artifact.  Provenance should bind the original provider reservation
or response identifier and content hash.  F0/U0 snapshots would remain
archived-only; permitted F1/U1 receivers would receive an immutable clone.

The observed B case means deterministic saving alone would still leave some
episodes empty.  A minimal common prompt change to evaluate separately would
require the one consolidation decision to output a short reusable-experience
text for a future task, while leaving its content free and withholding all
evaluator/reference material.  The runner would then use the same deterministic
commit rule.  This does not add a decision, SQL, or file operation budget, but
it changes the construct from *voluntary externalization* to a fixed
externalization opportunity and must be named as such.

For either variant, save a research-side RAW baseline consisting only of the
agent-visible pre-consolidation trajectory.  It must remain immutable and
unmounted by default; it is not automatically supplied to F1/U1.  It can only
serve a separately specified future `RAW_F`/`RAW_U` receiver comparison.

These are measurement/interface commitment fixes, not performance tuning. They
do not require a change to the underlying scientific question if the question
is transfer from externalized experience.  They *do* require the protocol to
stop interpreting “no file tool call” as evidence that no experience text was
generated or that the agent voluntarily elected not to externalize it.

## Next-step decision

A new paid viability run is needed before any formal matrix if either proposed
interface is adopted: the changed interface must demonstrate, with a real
provider, terminal/native scoring, deterministic snapshot/provenance, no
evaluator leakage, and a non-empty artifact opportunity.  This audit neither
authorizes nor starts that run.

Current gate outcome remains **`NO_GO_FOR_EXPERIENCE_TRANSFER`**.  Task
measurement reachability remains independently evidenced by the historical
terminal ANSWER and native-evaluator path.
