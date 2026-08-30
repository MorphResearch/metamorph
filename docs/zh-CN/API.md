# 前端与 API 边界

本地系统可以由前端调用 Metamorph。推荐结构如下：

```text
浏览器 UI → FastAPI 后端 → Metamorph Runtime → 模型供应商/工具
                         ├── SQLite：运行状态
                         └── 文件系统：产物和 trajectory
```

前端是客户端，不应该拥有 Agent 状态或模型凭证。

## 初始 API

```text
POST /v1/tasks
  body: {"task": "...", "workspace_id": "default", "mode": "single|multiagent", "conversation_id": "..."}
  返回: {"run_id": "...", "conversation_id": "...", "mode": "...", "status": "queued"}

GET /v1/conversations
  返回聊天历史侧栏需要的会话摘要

GET /v1/conversations/{conversation_id}
  返回一个会话中的全部 runs、消息和持久化结果

GET /v1/runs/{run_id}
  返回状态、摘要、指标和产物链接

GET /v1/runs/{run_id}/events
  返回结构化工具和评估事件；多 Agent 运行时还会返回架构、Agent、lesson 和贡献评估事件
```

当前 UI 已支持连续对话、选择单 Agent 或自适应多 Agent、恢复历史会话和查看事件时间线。之后可以增加 candidate 审批和 Server-Sent Events 实时输出。

## API 规则

- 即使只绑定 localhost，也要对 API 做认证；
- 使用类型化 schema 校验任务和工具参数；
- 浏览器只传 workspace 标识符，绝不接受任意文件系统路径；
- 不返回原始密钥或不受限制的 shell 输出；
- 删除等破坏性操作必须有独立的确认动作；
- 每次运行都应可幂等处理，并关联一个配置快照；
- 在 evaluator 和回滚路径完成前，关闭 evolution 相关 API。

API 层应保持薄。它负责启动和观察运行，不应该承载 evolution 逻辑本身。
