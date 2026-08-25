# Metamorph

一个本地运行、可联网检索并具备跨会话记忆的**通用智能体**（General-purpose Agent）。
架构参考 scilink-agent 的分层设计，但业务逻辑保持通用，不绑定任何垂直领域。

## 架构

```text
用户输入 → HTTP API → RunService → agent.executor（agent→tools 循环）
                                  ├─ 思考链提取（reasoning_content）
                                  ├─ 工具调用（联网检索 / 文档读取 / 记忆）
                                  └─ 事件日志（EventLogger，前端思考折叠 + 工具卡片）
```

### 代码分层

| 包 / 模块 | 职责 |
|-----------|------|
| `llm/` | 模型接入层：各 provider 默认配置 + OpenAI 兼容 client 构造 |
| `graphs/` | 智能体核心：agent→tools 循环 + 思考链提取（对应 scilink `graphs/`） |
| `prompts/` | 通用系统提示（对应 scilink `prompts/`） |
| `tools/` | 工具集（对应 scilink `tools/`） |
| ├─ `base.py` | 注册表 + pydantic→OpenAI schema 转换 + dispatch |
| ├─ `web.py` | `web_search` / `web_fetch` |
| ├─ `document.py` | `read_document` |
| └─ `memory.py` | `update_user_memory`（本地 JSONL 跨会话记忆） |
| `state/` | 运行状态：`events.py` 事件日志 + `store.py` SQLite 运行记录（history 持久化） |
| `api/` | HTTP 接口层：`routes.py` 路由 + `service.py` 编排 + `frontend/` 前端 |
| `config/` | 应用配置（`settings.py` 定义 `Settings`） |
| `cli/` | 命令行入口（`serve` / `run`） |

## 快速开始

```bash
pip install -e ".[openai,tools]"      # 核心 + 可选工具依赖

# 设置凭证（仅当前终端会话，不落盘）
export SENSENOVA_API_KEY="sk-xxx"      # Windows PowerShell: $env:SENSENOVA_API_KEY="sk-xxx"

# 启动本地服务
metamorph serve --provider sensenova --port 8787
```

打开 http://127.0.0.1:8787 即可在页面中与 agent 对话，实时看到：
**思考过程（可折叠）+ 工具调用卡片 + 最终回答**。

### 命令行直接运行

```bash
metamorph run "帮我查一下今天上海的天气" --provider sensenova
```

## 支持的模型供应商

`openai` / `deepseek` / `minimax` / `glm` / `claude` / `sensenova`
（默认 `sensenova`，模型 `deepseek-v4-flash`）。

切换供应商无需改动代码：

```bash
python -m metamorph.cli serve --provider deepseek
python -m metamorph.cli serve --provider openai
```

配置示例见 `.env.example`。

## 测试

```bash
pytest
```

## 设计原则

1. 架构对齐 scilink-agent 的分层，但业务逻辑通用，无垂直领域硬编码。
2. 模型接入与 agent 逻辑解耦：新增 provider 只需在 `llm/client.py` 的 `PROVIDER_DEFAULTS` 登记。
3. 工具即插即用：在 `agent/tools/` 下用 `register()` 声明，自动进入 schema 与 UI。
4. 所有运行证据（事件、结果）落盘可回溯；刷新页面可恢复完整思考链与工具轨迹。
