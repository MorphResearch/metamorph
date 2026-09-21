# Day-1 design decisions

| Date | Decision | Reason and evidence | Not frozen / confirmation needed |
|---|---|---|---|
| 2026-09-21 | `F = prompt_prescribed_v0` in the same single-agent loop | E0 needs to validate experience transport before adding a planner/reviewer/router. The prompt is stored and hashed. | This is a development default, not a program-enforced formal protocol. |
| 2026-09-21 | Use a synthetic metered SQLite `local_fixture` when no verified CL-Bench Database Exploration integration is present | It validates real query results, query failures, limits, snapshots, and receiver injection without claiming a benchmark result. | Public environment version, commit, IDs, and scorer remain unconfirmed. |
| 2026-09-21 | Disable arbitrary agent code execution | Repository inspection found workspace confinement but no verifiable OS/container sandbox appropriate for untrusted agent code. | `code_execution_isolation=BLOCKED`; do not replace it with host execution. |
| 2026-09-21 | Live requests default to blocked | No explicit model, price basis, currency cap, request limits, or authorization were supplied for this E0 request. | Researcher must explicitly confirm all live-smoke fields. |

