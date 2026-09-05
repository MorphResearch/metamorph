# AppWorld Auditable Workflow Runner Contract

## Frozen inputs

每个 run 绑定配置、不可变 task manifest、AppWorld commit、模型/提示词/contract/code-executor hash、预算、seed 和新 output root。P3 正式运行要求两个 worktree 干净、多个 seed、完整失败保留，且不得覆盖已有结果。P0–P2 不是主结果，允许在 train/dev 开发。

## E1 workflow 语义

E1 只比较预注册的固定 workflow：

```text
E       = executor（planner typed-null，无 verifier/repair）
P+E     = planner(read-only) → executor
E+V+R   = executor → verifier(read-only) → [NOT_VERIFIED] repair → final verifier
Full    = planner(read-only) → executor → verifier(read-only) → [NOT_VERIFIED] repair → final verifier
```

每个 `task × workflow × seed` 使用全新世界。tool selection 是所有 workflow 的共同前置阶段，不是被比较的 workflow 组件。router、Expert 标签、在线 lesson、No-JSON-Contract 和 No-Budget-Gate 不属于此协议。

## E2 组件与边干预

组件总效应从独立、相同初始世界比较 Full、No-Planner、No-Verifier、No-Repair。每次只关闭一个组件；No-Planner 以 typed-null 替代 planner artifact，No-Verifier 同时关闭 verifier 与 repair，No-Repair 保留 verifier 但禁止其触发 repair。

边干预必须依赖同一 task/seed 的 Full checkpoint：

1. `Planner→Executor` 从 `pre_executor` checkpoint 恢复，仅重跑 executor 及其下游；
2. `Executor→Verifier` 从 `post_executor` checkpoint 恢复，仅重跑 verifier/repair 下游；
3. `typed_null` 用 schema-compatible null artifact 替换目标边；
4. `passthrough` 重放同样的下游与原 artifact，是 replay 负控制，不是信息边效应；
5. checkpoint 被复制至全新世界，source hash 在前后必须完全一致；否则标记 `replay_contamination=true`，该 arm 不支持机制结论。

这估计的是给定上游 checkpoint 的受控下游效应，不宣称自然直接效应。

## 预算、超时和安全执行

所有模型阶段与每个真实 API 调用共享一个 per-task ledger。请求级 timeout 是配置的必填字段，且不得超过 task latency budget；真实 provider 请求在 macOS-safe 的 spawn 子进程中执行，父进程到时终止子进程。provider timeout/connection error 必须持久化为失败 result，不能留下悬挂进程。

Planner/Verifier 只有 GET/login 权限；Executor/Repair 可写。`metamorph__execute_code` 仅允许当前阶段白名单 API、局部变量、`if` 和 `for`，禁止 import、文件/网络、动态调用、定义、`while` 和私有属性。一个 code batch 可包含多次 API 调用，但每次实际调用均单独计入 trace/API/write 预算。

## 结果和失败处理

主指标是官方 strict success（0/1）；requirement pass fraction 仅诊断。每个 arm 的 `result.json` 至少保存：状态、官方评分、预算、latency、选中工具、artifact/hash、checkpoints、replay/contamination、错误类型。失败、超时、权限拒绝、contract 错误和基础设施错误都必须保留；后者需单列，不混作 workflow 因果效应。
