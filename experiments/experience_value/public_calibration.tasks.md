# Public Database Exploration development calibration

Scope: exactly six development-only episodes, in this fixed order:
`1-F0`, `1-U0`, `2-U0`, `2-F0`, `3-F0`, `3-U0`.

The runner loads the actual public pre-migration task text for the indicated
task ID. It does not provide table names, columns, reference SQL, answers, or
researcher diagnosis. Each episode has a fresh conversation and empty `/memory`
and `/work`; no snapshot is passed to another episode.

## Shared task/interface policy

Use only the listed file tools and the public task's read-only `query_sql`
tool. SQL feedback and SQL errors are visible. The native public task permits
at most 15 exploratory SQL queries. File `list_dir`, `read_file`, and
`write_file` operations share a separate maximum of 8 operations and cannot
increase, reset, or consume the native SQL allowance. You may voluntarily save
inert notes under `/memory` before your final answer; saving is not required.

Return your final task answer as ordinary text. Do not propose an unexecuted
tool call in text. There is no shell, Python, code execution, import, eval,
network, web, or direct database-file tool.

The runner submits only that final text to the native public `ANSWER` action.
Terminal evaluator feedback, reference answers, reference SQL, and scores are
not sent back to the model, not written to `/memory`, and not appended as a new
model turn.

## F0 and U0 difference only

F0 receives the existing fixed workflow guidance: inspect task/materials,
implement, check/revise, then decide whether to retain an artifact. U0 receives
the existing autonomous workflow guidance and may choose its own order. Both
receive the same public task prompt, model/configuration, tool schema, budgets,
and initial empty workspace.

This is calibration infrastructure, not an F/U comparison. Do not infer a
learning effect, select the better condition, or reuse any produced artifact in
formal practice/probe sequences.
