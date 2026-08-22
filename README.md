# Metamorph

Metamorph is a research-oriented, self-improving agent harness. It starts with a frozen foundation model and improves the surrounding system—tools, skills, memory policies, prompts, and control logic—through an evaluated, versioned, and reversible loop.

```text
task → execute in sandbox → record evidence → evaluate → diagnose
     → propose candidate → benchmark → approve/promote or reject/rollback
```

## Current status

The v0.1 baseline is now runnable: it includes a path-restricted workspace, read-only tools, explicit write approval, Mock plus OpenAI/DeepSeek/MiniMax/Claude/GLM model adapters, structured JSONL evidence, SQLite run state, a local HTTP API, and a deterministic baseline evaluator. Automatic evolution, memory learning, and Multi-Agent orchestration remain later milestones.

Run without any API key:

```bash
python3 -m metamorph.cli run "inspect this workspace" --workspace . --model-mode mock
```

Start the local API:

```bash
python3 -m metamorph.cli serve --model-mode mock
```

Switch providers without changing the runtime:

```bash
python3 -m metamorph.cli run "inspect this workspace" --provider deepseek
python3 -m metamorph.cli run "inspect this workspace" --provider minimax
python3 -m metamorph.cli run "inspect this workspace" --provider claude
python3 -m metamorph.cli run "inspect this workspace" --provider glm
```

The API is initially implemented with Python's standard library so the core can boot on a clean Mac. FastAPI and the OpenAI SDK are optional dependencies for the next integration layer.

## Start here

- [Local resources, model choice, and deployment](docs/RUNNING_LOCALLY.md)
- [System architecture](docs/ARCHITECTURE.md)
- [Frontend/API boundary](docs/API.md)
- [Model providers and switching](docs/MODEL_PROVIDERS.md)
- [How to extend the system](docs/EVOLUTION_GUIDE.md)
- [Today’s engineering log](docs/LOG-2026-08-22.md)

中文版：

- [系统架构（中文）](docs/zh-CN/ARCHITECTURE.md)
- [本地运行、资源与模型选择（中文）](docs/zh-CN/RUNNING_LOCALLY.md)
- [前端/API 边界（中文）](docs/zh-CN/API.md)
- [模型供应商与切换方法（中文）](docs/zh-CN/MODEL_PROVIDERS.md)
- [系统演进指南（中文）](docs/zh-CN/EVOLUTION_GUIDE.md)
- [今日日志（中文）](docs/zh-CN/LOG-2026-08-22.md)

## Design principles

1. The execution agent and the evolution controller are separate processes or roles.
2. The current version is never edited in place by an agent.
3. Every candidate must pass deterministic tests, regression tests, and safety checks before promotion.
4. The safety policy, evaluator protocol, and rollback mechanism are protected control-plane code.
5. Multi-agent orchestration comes after the single-agent loop is measurable.
