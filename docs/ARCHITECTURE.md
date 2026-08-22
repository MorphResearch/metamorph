# Metamorph v0.1 architecture

## Purpose

Metamorph is not initially intended to retrain a language model. It is a controllable evolution loop around a frozen model. The mutable part is the agent harness: prompts, planner policy, memory retrieval, skills, tools, and orchestration logic.

## Components

```text
                    ┌─────────────────────┐
                    │   Web UI / CLI       │
                    └──────────┬──────────┘
                               │ HTTPS / localhost API
                    ┌──────────▼──────────┐
                    │   Task API           │
                    │   auth + run state   │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────▼──────────────────────┐
        │              Execution runtime                │
        │ model adapter · planner · context builder    │
        └───────────────┬───────────────┬──────────────┘
                        │               │
                 ┌──────▼─────┐  ┌────▼────────┐
                 │ Memory     │  │ Tool layer  │
                 │ read/gate  │  │ allowlists  │
                 └──────┬─────┘  └────┬────────┘
                        │               │
                        └──────┬────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Execution sandbox   │
                    │ bounded workspace   │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Evidence store      │
                    │ runs/artifacts/logs │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Evaluator           │
                    │ tests + policy      │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Evolution controller│
                    │ diagnose → propose  │
                    │ benchmark → promote │
                    └─────────────────────┘
```

## Control plane and mutable plane

The following control-plane elements must not be modified automatically in v0.1:

- filesystem and network permissions;
- secret redaction and path restrictions;
- evaluator protocol and benchmark holdout rules;
- promotion, rollback, and human-approval rules;
- maximum token, time, disk, and process budgets.

The initial mutable harness may contain:

- `system_prompt.md` and task policies;
- planner and tool-selection policies;
- skills and their metadata;
- memory retrieval and write policies;
- low-risk, sandboxed helper tools.

## Run lifecycle

```text
created → running → succeeded/failed → evaluated → archived
```

An evolution lifecycle is separate:

```text
proposed → sandbox-tested → benchmarked → staged
         → human-approved → promoted
         └──────────────────────────────→ rejected/rollback
```

The production version is never overwritten while a task is running. A candidate receives its own workspace, configuration snapshot, dependency manifest, and benchmark report.

## Evidence and versioning

Each run should record structured events rather than hidden chain-of-thought:

- task input and permitted paths;
- model and configuration identifiers;
- tool name, validated arguments, result, exit status, and duration;
- compact decision summary supplied by the model;
- produced artifacts and content hashes;
- deterministic test results;
- token usage, latency, errors, and safety events.

Each evolution record must also include the parent version, prompt/policy hashes, memory snapshot, tool versions, benchmark version, evaluator version, and environment information. Git alone is not enough to reproduce a run.

## Initial implementation boundary

The first useful task family is local repository work: inspect files, propose a patch, run tests, and explain the result. The first tools should be read-only by default. Write and shell execution require an explicit workspace boundary and a confirmation policy.

The first implementation should be a small Python service with SQLite for run metadata and a plain filesystem for artifacts. Add vector retrieval only after a retrieval benchmark shows that it improves results.
