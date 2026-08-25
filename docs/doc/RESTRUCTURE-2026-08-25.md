# Metamorph 架构重构记录 — 2026-08-25

## 概述

参考 **scilink-agent**（LangGraph 医学科研 Agent）的分层架构和阿里云 Python 开发规范，
将项目从扁平单文件结构重构为生产级分层架构，同时彻底清除冗余代码。

## 目标

| 维度 | 重构前 | 重构后 |
|------|--------|--------|
| 顶层文件 | 12+ 个散落文件 | 仅 `main.py` + `pyproject.toml` + `.env.example` + `README.md` |
| 分层 | 无（全部塞在 `metamorph/` 包） | 9 个独立层，职责清晰 |
| API 路由 | 单个 `routes.py` 400+ 行 | 版本化 `api/v1/` + `router.py` + `workers.py` + `middleware.py` |
| Agent 循环 | `run_agent` 单函数 100+ 行 | `streaming.py`（chunk 解析）+ `loop.py`（编排）+ `agent.py`（入口） |
| 冗余文件 | 兼容 shim、临时脚本、重复入口 | 零冗余 |

## 最终目录结构

```
metamorph/
├── main.py                        # CLI 入口 (serve / run)
├── pyproject.toml                 # 包元数据 + 入口点
├── .env.example                   # 环境变量模板（根目录，不再放 configs/）
├── README.md
│
├── api/                           # HTTP 层
│   ├── __init__.py                # 仅导出 __version__
│   ├── __version__.py             # 版本号单一来源
│   ├── router.py                  # ThreadingHTTPServer + 路由分发
│   ├── workers.py                 # TaskWorker: 线程生命周期 + 任务提交
│   ├── middleware.py              # json_response / static_file / safe_workspace_id
│   ├── frontend/                  # 静态前端 (index.html, app.js, styles.css)
│   └── v1/                        # 版本化路由
│       ├── __init__.py
│       ├── info.py                # GET /v1/info
│       ├── runs.py                # GET /v1/runs, /v1/runs/{id}, /v1/runs/{id}/events
│       └── tasks.py               # POST /v1/tasks
│
├── config/
│   ├── __init__.py
│   └── settings.py                # Settings dataclass + from_environment()
│
├── graphs/
│   ├── __init__.py
│   ├── agent.py                   # run_agent: 高层入口，组合 streaming + loop
│   ├── loop.py                    # run_loop: agent→tools→agent 主循环
│   └── streaming.py               # iter_stream: chunk 解析、reasoning 提取
│
├── llm/
│   ├── __init__.py
│   ├── client.py                  # build_client: OpenAI/Anthropic SDK 构造
│   ├── providers.py               # PROVIDER_DEFAULTS: 单一配置源
│   └── thinking.py                # thinking_params_for: 模型 thinking 配置
│
├── memory/
│   ├── __init__.py
│   ├── user_memory.py             # 数据访问层: JSONL read/write/overwrite
│   └── formatter.py               # format_memories: 中文标签格式化为 system prompt
│
├── prompts/
│   ├── __init__.py
│   └── system_prompt.py           # SYSTEM_PROMPT 常量
│
├── state/
│   ├── __init__.py
│   ├── events.py                  # EventLogger: events.jsonl 写入/读取
│   └── store.py                   # RunStore: SQLite run 生命周期管理
│
├── tools/
│   ├── __init__.py
│   ├── base.py                    # TOOL_REGISTRY / dispatch / tool_schemas
│   ├── document.py                # read_document
│   ├── web.py                     # web_fetch / web_search
│   ├── utils.py                   # process_tool_result: 截断/格式化
│   ├── memory.py                  # update_user_memory 工具注册 (薄 wrapper)
│   └── __all_tools__.py           # ALL_TOOLS 注册总览 + TOOL_META
│
├── tests/
│   └── test_agent.py              # 7 tests (全部通过)
│
├── configs/                       # 已删除（env 移至根目录 .env.example）
├── cli/                           # 已删除（main.py 移至根目录）
├── scheduler/                     # 未创建（无实际代码，避免空目录）
│
└── docs/
    ├── doc/                       # 工程日志 + 重构记录
    │   ├── LOG-2026-08-22.md
    │   ├── LOG-2026-08-22.zh-CN.md
    │   └── RESTRUCTURE-2026-08-25.md  ← 本文档
    ├── ARCHITECTURE.md / zh-CN/
    ├── API.md / zh-CN/
    ├── MODEL_PROVIDERS.md / zh-CN/
    ├── EVOLUTION_GUIDE.md / zh-CN/
    └── RUNNING_LOCALLY.md / zh-CN/
```

## 删除的文件清单

| 文件 | 原因 |
|------|------|
| `metamorph/` 包（12 个文件） | 全部功能迁入分层目录 |
| `main.py`（旧） | 被新版 `main.py` 替代 |
| `api/routes.py` | 兼容 shim (`from .router import serve`)，零实际代码 |
| `api/service.py` | 零引用 shim (`TaskWorker as RunService`) |
| `.run_real.py` | 含本地 secret 的遗留脚本 |
| `_api_search.txt` | 307KB 临时调试文件 |
| `cli/__init__.py` | 零外部引用的空包标记 |
| `cli/__main__.py` | `python -m cli` 别名，`main.py` 已覆盖 |
| `configs/` 目录 | env 移至根目录 `.env.example` |

## 关键架构决策

### 1. Agent 循环三层拆分

```
streaming.py          → chunk 解析、reasoning_content 提取、tool_calls 累积
loop.py               → agent→tools→agent 编排、事件发射、上下文管理
agent.py              → 高层入口，组合前两者 + 记忆注入
```

参考 scilink-agent 的 `graphs/builder.py` + `graphs/main_graph.py` 模式。

### 2. 独立 Memory 层

```
memory/user_memory.py     → JSONL 数据访问 (append/overwrite/read)
memory/formatter.py       → 中文标签格式化 (用户画像/反馈偏好/项目背景/参考资料)
tools/memory.py           → 薄 wrapper，仅暴露 update_user_memory 工具注册
```

与工具注册解耦，formatter 可被 graph 层直接调用。

### 3. Provider 配置单一来源

`llm/providers.py` 的 `PROVIDER_DEFAULTS` dict 是全局唯一配置源：

```python
PROVIDER_DEFAULTS = {
    "sensenova": { "model": "deepseek-v4-flash", "base_url": "...", "api_key_env": "SENSENOVA_API_KEY" },
    "deepseek":  { "model": "deepseek-v4-pro",   ... },
    "openai":    { "model": "gpt-5.6-terra",     ... },
    "minimax":   { ... },
    "glm":       { ... },
    "claude":    { ... },
}
```

`config/settings.py` 和 `cli/main.py` 均从此 dict 读取默认值，避免多处硬编码。

### 4. 版本化 API 路由

```
api/v1/info.py    → GET /v1/info        (server metadata)
api/v1/runs.py    → GET /v1/runs        (list runs)
                  → GET /v1/runs/{id}   (get run status)
                  → GET /v1/runs/{id}/events (streaming events)
api/v1/tasks.py   → POST /v1/tasks      (submit task)
```

`router.py` 用 `ThreadingHTTPServer` + `BaseHTTPRequestHandler`，零第三方依赖。

### 5. Flat Layout + Namespace Packages

`pyproject.toml` 使用 setuptools `packages.find` 自动发现包：

```toml
[tool.setuptools.packages.find]
include = ["llm*", "graphs*", "state*", "tools*", "prompts*", "api*", "api.v1*",
           "config*", "memory*"]
```

`main.py` 是顶层模块（不在任何包内），通过 `[project.scripts] metamorph = "main:main"` 注册 console script。

## 依赖变化

| 依赖 | 操作 | 原因 |
|------|------|------|
| `fastapi` | 移除 | 使用 stdlib `http.server`，不需要第三方框架 |
| `uvicorn` | 移除 | 同上 |
| `pydantic>=2.0.0` | 保留 | Settings dataclass 验证 |

## 启动方式

```bash
# 设置环境变量
$env:SENSENOVA_API_KEY="sk-xxx"

# 启动 HTTP 服务
python main.py serve --provider sensenova --model sensenova-6.8-flash-lite --port 8787

# 直接运行任务
python main.py run "帮我查一下今天上海的天气" --provider sensenova
```

## 测试验证

```
7 passed
28/28 modules import OK
```

---

*后续所有架构改动记录追加到 `docs/doc/` 目录下，命名规范：`CHANGE-YYYY-MM-DD.md`*
