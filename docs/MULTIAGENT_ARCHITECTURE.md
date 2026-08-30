# Task-adaptive multi-agent architecture

## Purpose

The first multi-agent layer turns one task into an inspectable execution graph. It does not rewrite Python code or grant new permissions automatically.

```text
task
  ↓
task morphology
  ↓
role/dependency plan
  ↓
role agents execute with explicit upstream context
  ↓
lesson exchange
  ↓
contribution evaluator
  ↓
reviewable next-architecture proposal
```

## Components

| Component | Location | Responsibility |
|---|---|---|
| Morphology classifier | `multiagent/morphology.py` | Classifies task kind, complexity, decomposition, dependencies, verification and tool intensity |
| Architecture planner | `multiagent/planner.py` | Selects bounded roles and explicit dependencies |
| Orchestrator | `multiagent/orchestrator.py` | Runs roles in dependency order and assembles the final answer |
| Lesson store | `multiagent/lessons.py` | Persists lessons as `.metamorph/multiagent_lessons.jsonl` |
| Contribution evaluator | `multiagent/evaluator.py` | Measures marginal contribution, correction, distinctiveness, redundancy and information usefulness |
| Adjustment policy | `multiagent/evaluator.py` | Proposes keep, merge, remove or add operations; requires human approval |

## Current role templates

- Coding: analyst → implementer → tester → synthesizer
- Research: researcher → critic → synthesizer
- Planning: decomposer → executor → reviewer → synthesizer
- Other verifiable tasks: analyst → verifier → synthesizer
- Simple tasks: executor → synthesizer

The planner records the task morphology and recent lessons with every plan. The next version can replace the deterministic planner with an LLM planner, but should keep the same `ArchitecturePlan` contract and benchmark it against this baseline.

## Contribution signals

The deterministic evaluator is a baseline, not a causal claim. It uses observable proxies:

- marginal contribution: successful output, distinctiveness and correction signal;
- error correction: explicit verification, inconsistency, risk or error signals;
- distinctiveness: distance from peer outputs;
- redundancy: maximum lexical overlap with another output;
- information usefulness: overlap between dependency context and downstream answer.

The evaluator Agent adds a structured second opinion. Invalid evaluator JSON does not break the run; the deterministic report remains available.

## Evidence and safety

Each multi-agent run records architecture, role outputs, contribution evaluation, lesson exchange and adjustment proposal in the run event log. Lessons are durable, but adjustment proposals are marked `requires_human_approval`. Automatic code mutation, shell access, permission changes and tool installation remain outside this first version.

## Next research steps

1. Replace lexical proxies with controlled interventions: remove one role, mask one message, merge two roles, and rerun the same task seeds.
2. Add task-level success and cost metrics so contribution is not inferred from text overlap alone.
3. Compare single-agent, fixed multi-agent and morphology-adaptive baselines.
4. Add an approval command that promotes only evidence-backed architecture candidates.
5. Use lessons to propose, but not silently force, the next architecture.
