# Frontend and API boundary

Yes, the finished system can be called from a frontend. The recommended shape is:

```text
Browser UI → FastAPI backend → Metamorph runtime → model provider/tools
                         ├── SQLite: run state
                         └── filesystem: artifacts and trajectories
```

The frontend is a client, not the owner of agent state or credentials.

## Initial endpoints

```text
POST /v1/tasks
  body: {"task": "...", "workspace_id": "...", "mode": "safe"}
  returns: {"run_id": "...", "status": "queued"}

GET /v1/runs/{run_id}
  returns status, summary, metrics, and artifact links

GET /v1/runs/{run_id}/events
  returns structured tool/evaluation events

POST /v1/runs/{run_id}/approve
  approves a pending write, promotion, or other gated action

POST /v1/candidates/{candidate_id}/promote
  promotes an evaluated candidate after policy checks and human approval
```

For the first UI, a simple task form, run status page, event timeline, artifact list, and candidate approval page are enough. Streaming can be added later with Server-Sent Events or WebSockets.

## API rules

- authenticate the API even when it is initially bound to localhost;
- validate task and tool arguments with typed schemas;
- never accept arbitrary filesystem paths from the browser;
- do not return raw secrets or unrestricted shell output;
- require a separate approval action for destructive operations;
- make each run idempotent and traceable to one configuration snapshot;
- keep evolution endpoints disabled until the evaluator and rollback path exist.

The API layer should remain thin. It starts and observes runs; it should not contain the evolution logic itself.
