# Metamorph

Metamorph is a research-oriented, self-improving agent harness. It starts with a frozen foundation model and improves the surrounding system—tools, skills, memory policies, prompts, and control logic—through an evaluated, versioned, and reversible loop.

```text
task → execute in sandbox → record evidence → evaluate → diagnose
     → propose candidate → benchmark → approve/promote or reject/rollback
```

## Current status

This repository currently contains the v0.1 architecture and operating decisions. The runtime, sandbox, evaluator, and API are intentionally specified before implementation so that later self-modification remains observable and safe.

## Start here

- [Local resources, model choice, and deployment](docs/RUNNING_LOCALLY.md)
- [System architecture](docs/ARCHITECTURE.md)
- [Frontend/API boundary](docs/API.md)
- [How to extend the system](docs/EVOLUTION_GUIDE.md)
- [Today’s engineering log](docs/LOG-2026-08-22.md)

## Design principles

1. The execution agent and the evolution controller are separate processes or roles.
2. The current version is never edited in place by an agent.
3. Every candidate must pass deterministic tests, regression tests, and safety checks before promotion.
4. The safety policy, evaluator protocol, and rollback mechanism are protected control-plane code.
5. Multi-agent orchestration comes after the single-agent loop is measurable.
