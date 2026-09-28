# Tool-only live-smoke preparation

Status: **AUTHORIZED FOR EXACTLY THREE EPISODES — zero real provider requests had been made when the authorization was recorded.**

The original unsigned proposal remains intact at [live_smoke_config.pending.json](experiments/experience_value/live_smoke_config.pending.json) (SHA-256 `6a40a9c88077019c8f9b8052d6fd4ad403de7d6008161cf261a72eb68eb4b8ae`). The signed replacement is [live_smoke_config.authorized_20260921.json](experiments/experience_value/live_smoke_config.authorized_20260921.json) (SHA-256 `ff3cadeb389e213d97e65c242a3530710ed843a1e46696c20fdaaa809278e25e`). It is deliberately narrow: a new session may only call `read_file`, `write_file`, and the metered, read-only `query_sql` tool. It has no Python, bash, shell, `eval`, import, arbitrary-code, or web tool. A file named `*.py` is merely bytes in `/memory` or `/work`; no E0 path evaluates or imports it.

## Signed configuration

| Field | Proposal requiring confirmation |
|---|---|
| Provider / endpoint | DeepSeek, `https://api.deepseek.com` |
| Exact API model | `deepseek-v4-pro` |
| Credential handling | Existing `DEEPSEEK_API_KEY`, read only by SDK authentication after signoff; never placed in messages, records, snapshots, or tool files |
| Request limits | Explicit thinking enabled, `reasoning_effort=low`, no temperature, 20,480 input characters; reservation for 5,120 input plus 512 output tokens; 30 s timeout; SDK and application retries 0 |
| Episode limits | 3 fixed episodes; at most 6 provider requests and 6 total tool calls each; at most 18 provider requests total |
| Cost cap | USD 0.20 hard cap. Worst-case reservation uses official peak cache-miss input (USD 1.32/M) and peak output (USD 3.96/M): USD 0.00878592/request, USD 0.15814656 for 18 requests. |

The local provider registry already names the same provider, endpoint, model ID,
and credential-variable name. The `.venv` contains the OpenAI-compatible SDK
(`openai 3.6.0`). These are candidates, not authorization. The official
DeepSeek documentation currently lists this endpoint/model, tool-call support,
and the peak/off-peak price schedule; prices can change and must be rechecked
at signoff. [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing/) · [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)

## Frozen order and tasks

1. **U1 source practice** — `local_fixture_u1_practice_region_cluster`, empty
   `/memory`, fresh SQLite fixture. The agent may inspect the regions table and
   answer the task. It may decide whether to save a concise file; no artifact is
   required and nobody will add one for it.
2. **E* + MEMORY probe** — fresh conversation and fresh fixture with the
   frozen source snapshot copied into a new `/memory`; task
   `local_fixture_estimate_coastal_mean`: determine the mean observation value
   for the coastal cluster through the normal tools.
3. **E* + EMPTY probe** — the identical probe task, receiver configuration,
   fixture seed, limits, and order convention, but an empty `/memory`.

All three are `engineering_smoke` and
`included_in_primary_analysis=false`. The source session ends before either
probe. Each probe receives its own copy; neither writes back to the frozen
source or the other probe. No fourth episode, selective rerun, or artifact
repair is permitted. A missing artifact, no observed read, or a correct EMPTY
answer is an outcome, not a reason to change the order.

One `CostLedger` is created before episode 1 and passed through all three
episodes, so its six-request and USD 0.05 cap are global rather than reset per
episode.

## Adapter evidence completed without network access

`experiments/experience_value/live.py` now calls the existing
`graphs.loop.run_loop` with the existing `OpenAICompatibleAdapter`; only the
tool schema and dispatch are E0-local. The fake-transport test confirms:

- the first provider request has exactly a new system and user message—no old
  task marker, auto-summary, or continuation ID;
- a tool call and its `tool_call_id`-matched tool result return through the
  normal loop before the final answer;
- SDK options bind `max_retries=0` and the 20-second timeout for every attempt;
- model messages do not contain the credential-variable name, and credentials
  are not placed in records or workspace files;
- each attempt reserves worst-case cost first; missing usage marks billing
  unknown and blocks the next network attempt rather than releasing money.

The fake transport proves the integration path, not connectivity, account
access, provider behavior, or a model-learning result. The adapter is therefore
**READY_FOR_SIGNOFF_ONLY**, not live-run ready.

## Authorization boundary

The authorization applies only to this signed configuration and the fixed three
episodes—not E1/E2's 78-episode batch. A failed request, unreported usage,
snapshot contamination, or attempted scope expansion stops the remainder.
