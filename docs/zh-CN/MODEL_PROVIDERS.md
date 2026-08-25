# 模型供应商与切换方法

## 适用范围

Metamorph 将模型适配器与 Agent runtime 分离。runtime 只向供应商 adapter 请求一个经过验证的 `Decision`，不需要知道结果来自 OpenAI、DeepSeek、MiniMax、Claude 还是 GLM。

在 v0.1 中，供应商切换是**进程级别**的：启动 CLI 或 API server 前选择一个供应商。每个任务分别路由不同模型属于后续功能，等 benchmark 和成本统计稳定后再加入。

## 当前支持的供应商

| 供应商 | Adapter | 协议 | 默认模型 | Key 变量 | 默认 endpoint |
|---|---|---|---|---|---|
| Mock | `MockModelAdapter` | 本地确定性模式 | `mock-v0` | 无 | 无 |
| OpenAI | `OpenAIResponsesAdapter` | Responses API | `gpt-5.6-terra` | `OPENAI_API_KEY` | SDK 默认地址 |
| DeepSeek | `OpenAICompatibleChatAdapter` | OpenAI-compatible Chat Completions | `deepseek-v4-pro` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` |
| MiniMax | `OpenAICompatibleChatAdapter` | OpenAI-compatible Chat Completions | `MiniMax-M2.7` | `MINIMAX_API_KEY` | `https://api.minimax.io/v1` |
| Claude | `AnthropicMessagesAdapter` | Anthropic Messages | `claude-opus-4-6` | `ANTHROPIC_API_KEY` | SDK 默认地址 |
| GLM / Z.AI | `OpenAICompatibleChatAdapter` | OpenAI-compatible Chat Completions | `glm-5.1` | `ZAI_API_KEY` | `https://api.z.ai/api/paas/v4/` |

默认模型只是起始值。不同账户、地区、套餐和模型目录可能不同。如果供应商提供了其他模型 ID，可以通过 `METAMORPH_MODEL` 或 `--model` 覆盖。

官方协议文档：

- [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [DeepSeek OpenAI-compatible API](https://api-docs.deepseek.com/guides/function_calling)
- [MiniMax API 概览](https://platform.minimax.io/docs/api-reference/api-overview)
- [Z.AI OpenAI Python SDK](https://docs.z.ai/guides/develop/openai/python)
- [Claude Python SDK](https://platform.claude.com/docs/en/api/sdks/python)

## 安装依赖

Mock 模式不需要第三方依赖：

```bash
python3 -m metamorph.cli run "inspect this workspace" --provider mock
```

OpenAI-compatible 供应商使用 OpenAI Python SDK：

```bash
pip install -e '.[openai]'
```

这适用于 OpenAI、DeepSeek、MiniMax 和 GLM。Claude 使用 Anthropic SDK：

```bash
pip install -e '.[anthropic]'
```

## 使用 CLI 切换

通过 `--provider` 选择供应商：

```bash
python3 -m metamorph.cli run "inspect this workspace" \
  --provider deepseek \
  --model deepseek-v4-pro \
  --workspace .
```

其他例子：

```bash
python3 -m metamorph.cli run "inspect this workspace" --provider minimax
python3 -m metamorph.cli run "inspect this workspace" --provider claude
python3 -m metamorph.cli run "inspect this workspace" --provider glm
python3 -m metamorph.cli run "inspect this workspace" --provider openai
```

旧版本的 `--model-mode mock` 和 `--model-mode openai` 仍然保留，作为兼容别名。

## 使用环境变量切换

API server 在启动时读取配置：

```bash
export METAMORPH_PROVIDER=glm
export METAMORPH_MODEL=glm-5.1
export ZAI_API_KEY="replace-me"

python3 -m metamorph.cli serve
```

其他例子：

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

当前 API server 的所有任务共用进程启动时选择的供应商。切换供应商需要重启 server。

## Endpoint 和 key 覆盖

如果使用 OpenAI-compatible 网关或区域 endpoint：

```bash
export METAMORPH_PROVIDER=deepseek
export METAMORPH_BASE_URL=https://api.deepseek.com
export METAMORPH_API_KEY_ENV=DEEPSEEK_API_KEY
```

`METAMORPH_BASE_URL` 只用于 OpenAI-compatible adapter；Claude adapter 不使用它。`METAMORPH_API_KEY_ENV` 填的是环境变量的**名称**，不是密钥本身。

不要把真实 API key 放入仓库、提交到 Git 的 `.env`、task payload、trajectory 或前端代码。可以参考 [`.env.example`](../../.env.example) 中不包含真实密钥的模板。

## 这里的“兼容”是什么意思

当前 adapter 要求供应商返回一个包含 JSON decision 对象的文本响应：

```json
{
  "action": "read_file",
  "arguments": {"path": "README.md"},
  "answer": "",
  "summary": "先检查项目 README。"
}
```

runtime 会在执行前验证 action。v0.1 暂时没有使用每个供应商原生的 function calling，这是为了先保持跨供应商 benchmark 简单一致。原生 tool calling、streaming、重试策略、usage 统一和每任务模型路由会在后续 adapter 版本中加入。

## 如何增加新供应商

如果新供应商兼容 OpenAI API，只需要在 `metamorph/model.py` 的 `PROVIDER_DEFAULTS` 中加入 endpoint、key 变量和默认模型。如果它使用不同协议，则实现一个满足以下接口的新 adapter：

```python
class ModelAdapter(Protocol):
    provider: str
    model_name: str

    def decide(self, task, observation, history) -> Decision: ...
```

runtime、sandbox、evaluator、API 和未来的 evolution controller 都不应该增加供应商专用逻辑。
