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
compile DAG contracts / permissions / acyclicity
  ↓
role agents execute by dependency layers; independent roles run in parallel
  ↓
typed-null causal edge audit and downstream replay
  ↓
budgeted repair-or-stop decision
  ↓
contribution evaluator
  ↓
causally evidenced Candidate → Active → Disabled lesson ledger
```

## Components

| Component | Location | Responsibility |
|---|---|---|
| Morphology classifier | `multiagent/morphology.py` | Classifies task kind, complexity, decomposition, dependencies, verification and tool intensity |
| Architecture planner | `multiagent/planner.py` | Selects bounded roles and explicit dependencies |
| Orchestrator | `multiagent/orchestrator.py` | Runs roles in dependency order and assembles the final answer |
| DAG compiler / artifacts | `multiagent/contracts.py` | Validates DAGs and creates typed role artifacts / typed-null interventions |
| Budget utility | `multiagent/utility.py` | Tracks quality, token cost, critical-path latency, tools, safety and regression risk |
| Lesson store | `multiagent/lessons.py` | Appends versioned causal evidence and promotes only validated lessons |
| Contribution evaluator | `multiagent/evaluator.py` | Measures lexical signals plus task success, token cost, latency, tool calls and ablation deltas |
| Adjustment policy | `multiagent/evaluator.py` | Proposes keep, merge, remove or add operations; requires human approval |

## Current role templates

- Coding: analyst → implementer → tester → synthesizer
- Research: researcher → critic → synthesizer
- Planning: decomposer → executor → reviewer → synthesizer
- Other verifiable tasks: analyst → verifier → synthesizer
- Simple tasks: executor → synthesizer

The planner records the task morphology and compatible Active lessons with every plan. The DAG compiler has final authority: it rejects duplicate IDs, unresolved dependencies, invalid output contracts, and cycles. The orchestrator executes the plan as a bounded DAG: all roles whose dependencies are complete form one parallel layer. Multi-agent runs also receive the conversation history. The next version can replace the deterministic planner with an LLM planner, but should keep the same `ArchitecturePlan` contract and benchmark it against this baseline.

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

The causal auditor provides the primary local intervention: it holds the task, model, available tool outputs, and unaffected artifacts fixed; replaces one `Agent → Agent` dependency with a schema-preserving typed null artifact; and replays only the downstream subgraph. The resulting quality/cost/latency delta is recorded as causal evidence. A local DAG repair is accepted only when its lower-bound net utility is positive and its projected resource use remains within budget.

The evaluator Agent adds a structured second opinion. Invalid evaluator JSON does not break the run; the deterministic report remains available.

## Evidence and safety

Each multi-agent run records architecture, compilation, typed artifacts, causal audits, budget decisions, contribution evaluation, and lesson admissions in the run event log. Ordinary output summaries never become durable lessons. A lesson is admitted only with fixed-context intervention evidence; it starts as Candidate, becomes Active only after repeated independent evidence, and is Disabled by drift or repeated negative evidence. Automatic code mutation, shell access, permission changes and tool installation remain outside this version.

## Next research steps

1. Replace the fallback scorer with deterministic task benchmarks and fixed seeds.
2. Estimate uncertainty with repeated replays, rather than the current configurable penalty.
3. Compare single-agent, fixed multi-agent and causally governed adaptive baselines.
4. Add controlled task-family splits for drift-aware lesson transfer and negative-transfer measurement.
5. Extend safe local edits beyond dependency removal while preserving compiler and permission gates.
