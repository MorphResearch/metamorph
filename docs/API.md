# Frontend and API boundary

The local system can be called from a frontend. The recommended shape is:

```text
Browser UI → local HTTP backend → Metamorph runtime → model provider/tools
                         ├── SQLite: run state
                         └── filesystem: artifacts and trajectories
```

The frontend is a client, not the owner of agent state or credentials.

## Initial endpoints

```text
POST /v1/tasks
  body: {"task": "...", "workspace_id": "default", "mode": "single|multiagent", "conversation_id": "..."}
  returns: {"run_id": "...", "conversation_id": "...", "mode": "...", "status": "queued"}

GET /v1/conversations
  returns conversation summaries for the chat history sidebar

GET /v1/conversations/{conversation_id}
  returns all runs, messages, and persisted results in one conversation

GET /v1/runs/{run_id}
  returns status, summary, metrics, and artifact links

GET /v1/runs/{run_id}/events
  returns structured tool/evaluation events; multiagent runs include architecture,
  agent, lesson, and contribution events
```

The current UI supports continuous conversations, selecting single or multiagent mode, restoring history, and inspecting the run event timeline. The API uses polling for event observation; native transport streaming and candidate approval endpoints remain future work.

## API rules

- authenticate the API even when it is initially bound to localhost;
- validate task and tool arguments with typed schemas;
- accept a workspace identifier, not an arbitrary filesystem path, from the browser;
- do not return raw secrets or unrestricted shell output;
- require a separate approval action for destructive operations;
- make each run idempotent and traceable to one configuration snapshot;
- keep evolution endpoints disabled until the evaluator and rollback path exist.

When `METAMORPH_API_TOKEN` is set, every `/v1/` request requires
`Authorization: Bearer <token>`. Static frontend assets remain public so the
local UI can load before making authenticated API requests.

The API layer should remain thin. It starts and observes runs; it should not contain the evolution logic itself.
