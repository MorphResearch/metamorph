# 前端与 API 边界

可以。系统完成后，前端可以调用 Metamorph。推荐结构如下：

```text
浏览器 UI → FastAPI 后端 → Metamorph Runtime → 模型供应商/工具
                         ├── SQLite：运行状态
                         └── 文件系统：产物和 trajectory
```

前端是客户端，不应该拥有 Agent 状态或模型凭证。

## 初始 API

```text
POST /v1/tasks
  body: {"task": "...", "workspace_id": "...", "mode": "safe"}
  返回: {"run_id": "...", "status": "queued"}

GET /v1/runs/{run_id}
  返回状态、摘要、指标和产物链接

GET /v1/runs/{run_id}/events
  返回结构化工具事件和评估事件

POST /v1/runs/{run_id}/approve
  批准待处理的写操作、晋级操作或其他受控动作

POST /v1/candidates/{candidate_id}/promote
  在策略检查和人工批准后晋级一个 candidate
```

第一版 UI 只需要：任务输入框、运行状态页面、事件时间线、产物列表和 candidate 审批页面。之后可以用 Server-Sent Events 或 WebSockets 增加实时输出。

## API 规则

- 即使只绑定 localhost，也要对 API 做认证；
- 使用类型化 schema 校验任务和工具参数；
- 绝不接受浏览器直接传入的任意文件路径；
- 不返回原始密钥或不受限制的 shell 输出；
- 删除等破坏性操作必须有独立的确认动作；
- 每次运行都应可幂等处理，并关联一个配置快照；
- 在 evaluator 和回滚路径完成前，关闭 evolution 相关 API。

API 层应保持薄。它负责启动和观察运行，不应该承载 evolution 逻辑本身。
