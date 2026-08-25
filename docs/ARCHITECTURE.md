# Metamorph v0.2 Architecture

## Overview

Metamorph is a general-purpose, sandboxed agent harness modeled on
[scilink-agent](../scilink-agent/)'s layered design, adapted for a local
deployment without vertical-domain coupling.

## Layered Architecture

```text
┌─────────────────────────────────────────────────────────┐
│  Entry Layer                                             │
│  main.py  ·  cli/                                        │
├──────────────────────┬──────────────────────────────────┤
│  HTTP API Layer      │  Command-Line Interface           │
│  api/                │  cli/                             │
│    router.py         │    main.py (argparse)             │
│    middleware.py     │                                   │
│    workers.py        │                                   │
│    v1/               │                                   │
│      info.py         │                                   │
│      runs.py         │                                   │
│      tasks.py        │                                   │
├──────────────────────┴──────────────────────────────────┤
│  Agent Execution Layer                                   │
│  graphs/                                                 │
│    agent.py     (high-level entry: run_agent)            │
│    loop.py      (agent → tools → agent orchestration)   │
│    streaming.py (chunk parsing, reasoning extraction)   │
├───────────────┬──────────────────┬──────────────────────┤
│  LLM Layer    │  Memory Layer    │  Tools Layer          │
│  llm/         │  memory/         │  tools/               │
│    client.py  │    user_memory   │    base.py            │
│    providers  │    formatter.py  │    web.py             │
│    thinking   │                  │    document.py        │
├───────────────┴──────────────────┴──────────────────────┤
│  Configuration · State · Prompts                         │
│  config/     state/        prompts/                     │
│    settings  events.py     system_prompt.py             │
│           store.py                                              │
└─────────────────────────────────────────────────────────┘
```

## Layer Responsibilities

| Layer | Package | Responsibility |
|-------|---------|----------------|
| **Entry** | `main.py`, `cli/` | Thin entrypoint + argparse CLI (`run` / `serve`) |
| **HTTP API** | `api/` | Routing, middleware, task worker lifecycle, v1 sub-routes |
| **Agent Graph** | `graphs/` | LLM loop orchestration, streaming chunk parsing |
| **LLM** | `llm/` | Provider defaults, client construction, thinking config |
| **Memory** | `memory/` | Cross-session user memory persistence + prompt formatting |
| **Tools** | `tools/` | Tool registry, pydantic schemas, dispatch, web/doc tools |
| **Config** | `config/` | Settings dataclass from environment variables |
| **State** | `state/` | Event logger (JSONL) + Run store (SQLite) |
| **Prompts** | `prompts/` | System prompt template |

## Key Design Decisions

### 1. Provider Defaults as Single Source of Truth
`llm/providers.py` holds the authoritative `PROVIDER_DEFAULTS` dict.
`config/settings.py` and `llm/client.py` both import from it — no duplication.

### 2. Split Graph Layer
- `streaming.py`: pure chunk parsing (testable in isolation)
- `loop.py`: core agent→tools→agent orchestration
- `agent.py`: thin composition entry point

### 3. Independent Memory Layer
Memory data-access (`memory/user_memory.py`) is decoupled from the
agent tool registration (`tools/memory.py`). Prompt formatting
(`memory/formatter.py`) is a pure function over the data layer.

### 4. Versioned API Routes
`api/v1/{info,runs,tasks}.py` mirrors scilink-agent's `api/v1/` layout.
`api/router.py` dispatches on path prefix; `api/middleware.py` provides
shared helpers (JSON response, static serving, path-traversal guard).

### 5. Thinking Config
`llm/thinking.py` handles model-specific reasoning/thinking parameters
(DeepSeek V4 vs V3), mirroring scilink-agent's `thinking_config.py`.

### 6. Backward Compatibility
- `api/routes.py` re-exports `serve` from `router.py`
- `api/service.py` aliases `TaskWorker` as `RunService`
- All existing import paths continue to work

## Tool Registry

| Tool | Category | Description |
|------|----------|-------------|
| `web_search` | web | DuckDuckGo search (no API key) |
| `web_fetch` | web | Fetch URL body as text |
| `read_document` | document | Read txt/md/json/csv/pdf/docx from workspace |
| `update_user_memory` | memory | CRUD cross-session memories (user/feedback/project/reference) |

## Run Lifecycle

```text
queued → running → completed | failed
```

Each run produces:
- `.metamorph/runs/{run_id}/events.jsonl` — append-only event log
- `.metamorph/runs/{run_id}/result.json` — final result snapshot
- SQLite `runs.db` row — run metadata

## Provider Support

| Provider | Default Model | Base URL | API Key Env |
|----------|--------------|----------|-------------|
| openai | gpt-5.6-terra | — | OPENAI_API_KEY |
| deepseek | deepseek-v4-pro | api.deepseek.com | DEEPSEEK_API_KEY |
| minimax | MiniMax-M2.7 | api.minimax.io/v1 | MINIMAX_API_KEY |
| glm | glm-5.1 | api.z.ai/api/paas/v4/ | ZAI_API_KEY |
| claude | claude-opus-4-6 | — | ANTHROPIC_API_KEY |
| sensenova | deepseek-v4-flash | token.sensenova.cn/v1 | SENSENOVA_API_KEY |
