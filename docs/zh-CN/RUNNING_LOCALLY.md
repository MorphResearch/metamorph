# Metamorph 本地运行指南

## 简短结论

v0.1 不需要租服务器。你的 Mac 可以运行控制面、API、SQLite 数据库、日志、benchmark runner 和受限的任务 worker。基础模型通过 API 调用，因此 Mac 不需要保存大模型权重，也不需要独立显卡。

这台 Mac 也可以运行小型量化本地模型进行实验，但对于长程代码任务和 Agent evolution，质量和速度通常会低于托管模型。

## 已检测的电脑配置

2026-08-22 检测到：

| 项目 | 检测结果 | 影响 |
|---|---|---|
| 设备 | MacBook Pro，`MacBookPro18,3` | Apple Silicon |
| 芯片 | Apple M1 Pro，8 核 | 适合运行 Python 服务和受限 worker |
| 内存 | 16 GB | 不要同时运行多个大型本地模型或大量 worker |
| 存储 | 用户提供为 512 GB 级别磁盘；当前 `/` 约有 69 GiB 可用 | 建议至少保留 50 GB 给环境、日志和数据集 |

“512 内存”通常指 512 GB SSD，而不是 RAM。macOS 检测到的实际 RAM 是 16 GB。

## v0.1 所需资源

### 必需

- Python 3.11 或更新版本；
- `uv` 或 `venv` 等虚拟环境工具；
- Git；
- SQLite；
- 所选模型供应商的 API key；
- 10–20 GB 可用磁盘空间，用于项目、环境和测试产物。

### 可选

- Docker 或其他操作系统级沙箱；
- Ollama 或 MLX 等本地模型运行环境；
- 只有在检索评估证明必要后才加入的向量索引；
- 一个简单的 Web 前端。

## 基础模型建议

对于这个项目，建议先使用托管模型，并让模型适配器与供应商解耦。当前 runtime 支持两类协议：OpenAI 使用 Responses API；DeepSeek、MiniMax、GLM 使用 OpenAI-compatible Chat Completions；Claude 使用 Anthropic Messages API。

| 角色 | 默认选择 | 原因 |
|---|---|---|
| 日常执行 | `gpt-5.6-terra` | 在工具调用和多步骤任务上平衡质量与成本 |
| 困难诊断/进化 | `gpt-5.6-sol` | 只在复杂失败分析和候选设计时使用 |
| 路由、分类、memory gate | `gpt-5.6-luna` | 适合低成本、高频率决策 |

### 供应商配置

| 供应商 | 协议 | 默认模型 | API key 环境变量 | 默认 endpoint |
|---|---|---|---|---|
| OpenAI | Responses API | `gpt-5.6-terra` | `OPENAI_API_KEY` | OpenAI SDK 默认地址 |
| DeepSeek | OpenAI-compatible Chat Completions | `deepseek-v4-pro` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` |
| MiniMax | OpenAI-compatible Chat Completions | `MiniMax-M2.7` | `MINIMAX_API_KEY` | `https://api.minimax.io/v1` |
| Claude | Anthropic Messages | `claude-opus-4-6` | `ANTHROPIC_API_KEY` | Anthropic SDK 默认地址 |
| GLM / Z.AI | OpenAI-compatible Chat Completions | `glm-5.1` | `ZAI_API_KEY` | `https://api.z.ai/api/paas/v4/` |

使用 `--provider` 切换供应商，也可以额外指定 `--model`、`--base-url` 和 `--api-key-env`。模型适配器在边界层选择，runtime 和工具不需要知道当前使用的是哪家供应商。

可以参考 [`configs/providers.example.env`](../../configs/providers.example.env) 中不包含真实密钥的配置模板。API key 应通过 shell 环境变量或 secret manager 注入，不能提交到 Git。

这些模型名称和定位依据当前 OpenAI 官方模型说明。推理、工具调用和多轮工作流建议使用 Responses API；实验开始后应固定具体模型版本，以便进行可比 benchmark。模型可用性、价格和限额取决于账户，并可能发生变化，部署前请查看[官方 Models 文档](https://developers.openai.com/api/docs/models)和[官方模型指导](https://developers.openai.com/api/docs/guides/latest-model)。

模型接口建议保持简单：

```python
class ModelAdapter(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...
```

这样更换模型时是在做实验，而不是重写整个 runtime。

OpenAI-compatible 适配器可通过 `pip install -e '.[openai]'` 安装，Claude 支持通过 `pip install -e '.[anthropic]'` 安装。Mock provider 仍然不需要任何第三方依赖。

## 是否需要服务器

| 场景 | 本地 Mac | 服务器 |
|---|---:|---:|
| 个人开发和研究 | 推荐 | 不需要 |
| 通过 API 使用模型，只有少量并发 | 足够 | 不需要 |
| Mac 关机或睡眠时仍要保持服务在线 | 不够 | 有用 |
| 多用户或大量并发 worker | 不理想 | 推荐 |
| 本地训练或运行大型模型 | 16 GB 不实际 | 需要 GPU 服务器 |
| 小型量化模型实验 | 可以 | 不需要 |

当你需要持续在线、并发、GPU 或远程访问时再租服务器。仅仅为了运行 Python 控制循环，不需要租服务器。

## 最低安全配置

启用写文件或 shell 工具之前，必须做到：

1. 所有路径限制在专用 workspace 内。
2. 密钥放在 workspace 外，并从日志中脱敏。
3. 使用命令白名单和资源限制。
4. 候选工具在隔离环境中运行。
5. 删除、联网、安装依赖和写入任务目录以外的位置，都需要确认。
6. Evaluator、安全策略和回滚机制不能放在自动可修改区域。

不要把模型供应商的 API key 暴露给浏览器。浏览器只调用本地或后端 API，只有后端调用模型供应商。
