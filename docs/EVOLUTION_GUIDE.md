# How to improve or modify Metamorph

## Safe order of growth

### 1. Baseline runtime

Implement one narrow task family first: inspect a repository, edit an allowed file, run tests, and report the result. Add deterministic tests before adding memory or automatic mutation.

### 2. Read-only memory

Record episodic runs with provenance. Add retrieval only if an A/B benchmark shows better task success without unacceptable cost or negative transfer.

### 3. Skills and policy evolution

Allow candidates to modify one prompt, policy, or skill at a time. Put a diff-size limit on mutations. Evaluate against development, regression, and hidden tasks. Require human approval for promotion.

### 4. Tool evolution

Start with pure functions and parsers. Every generated tool needs a schema, unit tests, adversarial tests, static checks, permission metadata, and sandbox execution. Never auto-enable a tool with filesystem, network, or process privileges in production.

### 5. Improvement routing

Use repeated failure evidence to choose a target:

```text
wrong fact → memory or retrieval
wrong procedure → skill or planner
missing capability → tool proposal
bad prioritization → policy or planner
unreliable judge → evaluator, not agent prompt
```

### 6. Multi-agent

Only after the single-agent loop is measurable, add a worker and an independent verifier. Add an evolver after the evidence and candidate protocol are stable. Put explicit limits on agent count, turns, tokens, and shared-state writes.

### 7. Meta-evolution

Keep the outer safety anchor, evaluator protocol, promotion policy, and rollback path immutable. Meta-evolution may propose changes to diagnosis or mutation strategies, but it should not be allowed to rewrite its own safety boundary.

## Every change should answer five questions

1. What repeated failure or opportunity motivated the change?
2. Which component is the smallest plausible intervention target?
3. What deterministic test can detect improvement?
4. What regression or safety failure would reject it?
5. How can the previous version and configuration be restored?

## Suggested experiment record

```yaml
evolution_id: EVO-0001
parent_version: v0
target: prompt | skill | memory_policy | tool | planner
evidence_runs: [run_001, run_004]
baseline_metrics: {}
candidate_metrics: {}
regressions: []
safety_checks: []
decision: reject | staged | promote
approved_by: human | policy
```

The first claim to make is not “the agent is intelligent.” It is narrower and testable: “this candidate improves the selected task benchmark under the same model, budget, evaluator, and safety policy.”
