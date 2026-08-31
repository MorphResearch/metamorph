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
role agents execute by dependency layers; independent roles run in parallel
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
| Contribution evaluator | `multiagent/evaluator.py` | Measures lexical signals plus task success, token cost, latency, tool calls and ablation deltas |
| Adjustment policy | `multiagent/evaluator.py` | Proposes keep, merge, remove or add operations; requires human approval |

## Current role templates

- Coding: analyst → implementer → tester → synthesizer
- Research: researcher → critic → synthesizer
- Planning: decomposer → executor → reviewer → synthesizer
- Other verifiable tasks: analyst → verifier → synthesizer
- Simple tasks: executor → synthesizer

The planner records the task morphology and recent lessons with every plan. The orchestrator executes the plan as a bounded DAG: all roles whose dependencies are complete form one parallel layer. Multi-agent runs also receive the conversation history. The next version can replace the deterministic planner with an LLM planner, but should keep the same `ArchitecturePlan` contract and benchmark it against this baseline.

## Contribution signals

The deterministic evaluator is a baseline, not a causal claim. It uses observable signals:

- marginal contribution: successful output, distinctiveness and correction signal;
- error correction: explicit verification, inconsistency, risk or error signals;
- distinctiveness: distance from peer outputs;
- redundancy: maximum lexical overlap with another output;
- information usefulness: overlap between dependency context and downstream answer.
- task success rate: benchmark scorer output when configured, otherwise an explicit execution-success fallback;
- token cost, wall-clock latency and tool-call count from the normalized provider adapter;
- ablation performance delta: rerun the same plan with one Agent removed and compare the task score.

The evaluator Agent adds a structured second opinion. Invalid evaluator JSON does not break the run; the deterministic report remains available.

## Evidence and safety

Each multi-agent run records architecture, role outputs, contribution evaluation, lesson exchange and adjustment proposal in the run event log. Lessons are durable, but adjustment proposals are marked `requires_human_approval`. Automatic code mutation, shell access, permission changes and tool installation remain outside this first version.

## Next research steps

1. Replace the fallback scorer with a deterministic task benchmark and fixed seeds.
2. Extend controlled interventions with message masking and role merging.
3. Compare single-agent, fixed multi-agent and morphology-adaptive baselines.
4. Add an approval command that promotes only evidence-backed architecture candidates.
5. Use lessons to propose, but not silently force, the next architecture.
