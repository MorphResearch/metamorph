# AppWorld DAG Runner Contract

## 冻结输入与对象

每个 run 绑定不可变任务清单、配置 hash、Metamorph/AppWorld commit、模型与提示版本、预算和 seed。固定控制平面不参与消融；唯一实验对象为其选择的 task-workflow DAG（G0–G3）。

所有 node artifact 都是类型化 handoff，每个已执行节点之后都调用 `save_state`，记录 state hash、预算快照和 trace。所有计时使用真实 monotonic wall-clock，不能读取 AppWorld 冻结时间。

## DAG 语义

- `inspect` 与 `check` 只提供 GET/login 工具；`act`/`repair` 可写；`join` 无工具。
- G2 的两个 inspect 分支是唯一允许拓扑干预的并行批次，且均为只读；本地执行顺序不改变其依赖语义。
- G3 的 repair/final_check 只在初始 check 为 `NOT_VERIFIED` 时执行，条件跳过也写入 trace。

## P0 必须证明的 replay 不变量

1. compiler 拒绝环、类型不匹配、写节点并行；
2. 每个 completed node 有 artifact hash 与 checkpoint；
3. 节点 skip、边 typed-null mask、G2 serial topology 可调度；
4. source checkpoint 在 replay 前后 hash 相同；
5. passthrough edge replay 是负控制，不能被报告为边效应。

真实 P2 replay 从源节点后的 checkpoint 在全新 world 恢复；保留源节点造成的世界状态，只替换目标可见 artifact。污染、恢复失败、缺失 trace 均持久化并从机制估计中排除。

## 安全与结果

工具和安全 code executor 继续沿用统一 per-task ledger。`result.json` 必须包含官方 strict success、token、真实 wall-clock、工具/API 调用、节点 artifacts/hashes/checkpoints、replay validity 和失败分类。历史 `fixed_s3` 结果不属于此协议。
