# Tool-only interface revision

Status: **offline-only; zero real provider requests in this revision.** This is
a development interface change, not a result comparable with the completed
three-episode smoke.

## Implemented

- Added `list_dir` for direct discovery under the current logical `/memory` or
  `/work`. It reports names and types only, returns a real empty list, makes
  truncation explicit, and rejects missing paths, non-directories, escapes, and
  symlink traversal. It does not expose absolute host paths or research roots.
- Added common tool-only guidance: task text is in the current message; use
  `list_dir` before `read_file`; `query_sql` is read-only one-statement SQLite
  with a semicolon restriction; artifacts are optional except in a labeled
  positive control. No fixture schema or answer was added.
- `list_dir` is in the identical F/U/E* allowlist and consumes the existing
  tool-call counter.
- Future real runs will save redacted request/response evidence at
  `artifacts/experience_value/<run>/research_records/provider_transcripts.jsonl`.
  It records messages, tools, whether `tool_choice` was actually present,
  structured tool calls, content, usage, and stop reason, while redacting
  credential-shaped fields and never mounting records for the agent.
- Budget-truncated calls now receive an explicit runner rejection and paired
  tool feedback before the next model request; accepted and rejected calls keep
  distinct count units.

## Offline verification

```text
./.venv/bin/python -m unittest experiments.experience_value.tests.test_e0_acceptance -v
./.venv/bin/python -m unittest discover -s tests -q
```

The suite covers empty/non-empty/nested directory listings, directory-to-file
discovery in a fresh inherited session, missing/non-directory/escape/symlink
rejection, list-dir tool accounting, transcripts without credential material,
explicit budget-rejection pairing, and the prior isolation/result semantics.

## Pending file positive control

[file_positive_control.pending.json](experiments/experience_value/file_positive_control.pending.json)
and [file_positive_control.tasks.md](experiments/experience_value/file_positive_control.tasks.md)
freeze a separate three-episode engineering positive control. PC-SOURCE is
explicitly asked to save an artifact from actual SQLite feedback; PC-MEMORY and
PC-EMPTY use the same E* probe prompt and differ only in the frozen clone versus
empty memory. It remains pending, excluded from primary analysis and F/U
research samples, with no live authorization.

The candidate limit remains 6 requests and 6 tools per episode. The enlarged
schema is still covered by the same 5,120-input/512-output reservation ceiling:
USD 0.00878592 per request and USD 0.15814656 for 18 requests, below the
candidate USD 0.20 cap. This is a recomputation under fixed limits, not an
approved spend.

Public-environment integration and arbitrary agent-code execution remain
**BLOCKED**; no AppWorld or 78-episode work was started.
