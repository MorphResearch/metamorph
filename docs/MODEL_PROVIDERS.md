# Model providers and switching

## Scope

Metamorph separates the model adapter from the runtime. The runtime only asks a provider adapter for one validated `Decision`; it does not know whether the response came from OpenAI, DeepSeek, MiniMax, Claude, or GLM.

In v0.1, provider selection is **process-level**: choose one provider before starting the CLI or API server. The default is DeepSeek. Per-task model routing is a later feature and will be added after the benchmark and cost accounting layers are stable.

## Supported providers

| Provider | Adapter | Protocol | Default model | Key variable | Default endpoint |
|---|---|---|---|---|---|
| Mock | `MockModelAdapter` | local deterministic | `mock-v0` | none | none |
| OpenAI | `OpenAIResponsesAdapter` | Responses API | `gpt-5.6-terra` | `OPENAI_API_KEY` | SDK default |
| DeepSeek | `OpenAICompatibleChatAdapter` | OpenAI-compatible Chat Completions | `deepseek-v4-pro` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` |
| MiniMax | `OpenAICompatibleChatAdapter` | OpenAI-compatible Chat Completions | `MiniMax-M2.7` | `MINIMAX_API_KEY` | `https://api.minimax.io/v1` |
| Claude | `AnthropicMessagesAdapter` | Anthropic Messages | `claude-opus-4-6` | `ANTHROPIC_API_KEY` | SDK default |
| GLM / Z.AI | `OpenAICompatibleChatAdapter` | OpenAI-compatible Chat Completions | `glm-5.1` | `ZAI_API_KEY` | `https://api.z.ai/api/paas/v4/` |

The default model is only a starting value. Provider accounts, regions, plans, and model catalogs can differ. Override `METAMORPH_MODEL` or pass `--model` when the provider exposes a different model ID.

Official protocol references:

- [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [DeepSeek OpenAI-compatible API](https://api-docs.deepseek.com/guides/function_calling)
- [MiniMax API overview](https://platform.minimax.io/docs/api-reference/api-overview)
- [Z.AI OpenAI Python SDK](https://docs.z.ai/guides/develop/openai/python)
- [Claude Python SDK](https://platform.claude.com/docs/en/api/sdks/python)

## Installation

Mock mode has no third-party dependency:

```bash
python3 main.py run "inspect this workspace" --provider mock
```

OpenAI-compatible providers use the OpenAI Python SDK:

```bash
pip install -e '.[openai]'
```

This covers OpenAI, DeepSeek, MiniMax, and GLM. Claude uses the Anthropic SDK:

```bash
pip install -e '.[anthropic]'
```

## Switching with the CLI

The provider is selected with `--provider`:

```bash
python3 main.py run "inspect this workspace" \
  --provider deepseek \
  --model deepseek-v4-pro \
  --workspace .
```

Examples:

```bash
python3 main.py run "inspect this workspace" --provider minimax
python3 main.py run "inspect this workspace" --provider claude
python3 main.py run "inspect this workspace" --provider glm
python3 main.py run "inspect this workspace" --provider openai
```

`--model-mode mock` and `--model-mode openai` remain as backwards-compatible aliases for older commands.

## Switching with environment variables

The API server reads configuration when it starts:

```bash
export METAMORPH_PROVIDER=glm
export METAMORPH_MODEL=glm-5.1
export ZAI_API_KEY="replace-me"

python3 main.py serve
```

Other examples:

```bash
# DeepSeek
export METAMORPH_PROVIDER=deepseek
export METAMORPH_MODEL=deepseek-v4-pro
export DEEPSEEK_API_KEY="replace-me"

# MiniMax
export METAMORPH_PROVIDER=minimax
export METAMORPH_MODEL=MiniMax-M2.7
export MINIMAX_API_KEY="replace-me"

# Claude
export METAMORPH_PROVIDER=claude
export METAMORPH_MODEL=claude-opus-4-6
export ANTHROPIC_API_KEY="replace-me"
```

The API currently uses one configured provider for all tasks handled by that server process. Restart the process to switch providers.

## Endpoint and key overrides

For an OpenAI-compatible gateway or regional endpoint:

```bash
export METAMORPH_PROVIDER=deepseek
export METAMORPH_BASE_URL=https://api.deepseek.com
export METAMORPH_API_KEY_ENV=DEEPSEEK_API_KEY
```

`METAMORPH_BASE_URL` is used by the OpenAI-compatible adapter. It is not used by the Claude adapter. `METAMORPH_API_KEY_ENV` contains the **name** of an environment variable, not the secret itself.

Never put a real API key in this repository, `.env` files committed to Git, task payloads, trajectories, or frontend code. Use the credential-free template at [`.env.example`](../.env.example).

## What “compatible” means here

The current adapter expects the provider to return a text response containing one JSON decision object:

```json
{
  "action": "read_file",
  "arguments": {"path": "README.md"},
  "answer": "",
  "summary": "Inspect the project README before acting."
}
```

The runtime validates the action before executing it. v0.1 does not yet use each provider's native function-calling format. That is intentional: it keeps the first cross-provider comparison simple. Native tool calling, streaming, retry policy, usage normalization, and per-task model routing are future adapter work.

## Adding another provider

If a new provider is OpenAI-compatible, add its endpoint, key variable, and default model to `PROVIDER_DEFAULTS` in `llm/providers.py`. If it uses a different protocol, implement a new adapter satisfying:

```python
class ModelAdapter(Protocol):
    provider: str
    model_name: str

    def decide(self, task, observation, history) -> Decision: ...
```

The runtime, sandbox, evaluator, API, and future evolution controller should not need provider-specific changes.
