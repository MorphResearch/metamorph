# AppWorld context cost audit

## Scope and method

This is a read-only audit of `530b157_3 × G3 × seed 300` under
`dag_p1_formal_orchestrated_v3_20260907`.  It does not make provider calls and
does not treat this arm as formal P1 data.  Sources are the immutable
`result.json`, node checkpoints, phase traces, arm log, and AppWorld
environment log.

The arm was not an evaluator failure: it reached `dag_check`, then stopped
before the checker finalization request because the shared 150,000-token
budget had only 4,014 tokens remaining.  `protocol_valid=false` is therefore
an audit outcome, not a task-success result.

## Observed cumulative budget accounting

| boundary | provider calls completed | input tokens | output tokens | total tokens | tool calls | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| after selector + inspect | 3 | 12,779 | 5,983 | 18,762 | 0 | selector finalization once; inspect finalization twice |
| after act | 9 | 66,528 | 13,188 | 79,716 | 10 | includes the preceding selector/inspect work |
| after check stop | 16 | 126,946 | 19,040 | 145,986 | 21 | checker finalization did not start |

Thus the attributable **deltas** are:

| segment | input tokens | output tokens | total tokens | completed provider calls |
| --- | ---: | ---: | ---: | ---: |
| selector + inspect | 12,779 | 5,983 | 18,762 | 3 |
| act | 53,749 | 7,205 | 60,954 | 6 |
| check before budget stop | 60,418 | 5,852 | 66,270 | 7 |

The current trace schema records aggregate ledger snapshots only.  It does
**not** retain provider usage per request, so it cannot honestly separate
`tool_selector` from `inspect`, or finalization tokens from a phase's tool
turns.  Those fields are marked unavailable rather than estimated.

## Required attribution view

| stage | input/output tokens | tool calls | finalization | finding |
| --- | --- | ---: | --- | --- |
| `tool_selector` | unavailable separately (included in first 12,779 / 5,983 aggregate) | 0 | 1 call, 896-char response | selected 20 tools; its schema is later repeated on tool turns |
| `inspect` | unavailable separately (included in first aggregate) | 0 | 2 calls: empty response then 1,986-char truncated JSON | invalid contract; no tool evidence was needed or produced |
| `act` | 53,749 / 7,205 delta | 10 APIs in 2 constrained batches | 2 calls; first invalid, second completed | one normal tool dialogue plus two terminal JSON attempts |
| `check` | 60,418 / 5,852 delta before stop | 11 successful + 2 failed direct calls; 2 constrained batches | 0 calls; reservation absent, so it was denied before finalization | checker consumed more tokens than act while producing no verifier artifact |

`retry_tokens` for act and `finalization_tokens` for every stage are not
available from the old trace format.  This is an observability gap to close
for post-freeze reporting, not evidence that the values are zero.

## Context and observation findings

1. The task instruction is placed independently in the selector, inspector,
   executor, and verifier prompts.  This is intentional per-node task access,
   but it is repeated at least four times in G3.
2. Within a tool-using node, `_run_phase` appends every assistant tool call and
   every tool response to one growing `messages` list.  The terminal
   finalization request then receives that full local dialogue again.
3. The configured `MAX_TOOL_OUTPUT_CHARS` is 20,000.  Full output is persisted
   in the AppWorld log, but a code batch's unbounded visible output is also
   appended to model messages up to that 20,000-character ceiling.
4. This arm's immutable environment log is 59,674 bytes for 12 interactions;
   it includes large message-search results.  The compact trace records only
   placeholders for batch API outputs, so its 1,287/1,989-character apparent
   phase output totals understate what the model actually received.
5. The selected-tool list has 20 entries and `_tools()` repeats the full
   function schema plus synthetic code-executor schema on every tool turn.
   `act` made four tool-phase provider calls; `check` made seven.
6. `act` received a typed-null inspect handoff after the inspect contract
   failure.  `check` received the full `ExecutionArtifact`; it did not need
   planner/inspect raw conversation, but its own growing verification
   dialogue was still replayed into each later request and into finalization.
7. Existing finalization is correct in semantics (`tools=[]`, JSON mode, one
   correction retry), but it is not minimal in context because it copies the
   whole phase message history.

## Consequence for the final core protocol

The evidence supports deterministic context projection, bounded model-visible
tool observations, phase-local tool surfaces, minimal finalization context,
and downstream budget reservation.  It does not support changing task
selection, evaluator rules, repair conditions, artifact schemas, or provider.
