# 论文架构：可审计的 Agent Workflow 因果归因

## 一句话主张

复杂 agent workflow 并非普遍更优。通过对有状态 workflow 的可复放受控干预，可以识别在何种任务结构下应保留哪些组件和信息边，并将这些证据复用为跨会话的低成本 workflow profile。

## Research gap

现有 agent 系统通常只报告完整 workflow 的端到端成功率，或通过从头重跑的 ablation 比较架构。对于会改变环境状态、且下游会读取上游 artifact 的任务，这无法分辨：组件本身的贡献、通信信息的价值、模型重采样和轨迹变化造成的差异，也无法把一次昂贵的架构试错转化为后续同类任务可用的策略知识。

## 方法

```text
Task structure signature
          │
          ▼
Auditable workflow runtime
  ├── E       = Executor
  ├── P+E     = Planner → Executor
  ├── E+V+R   = Executor → Verifier → Repair
  └── Full    = Planner → Executor → Verifier → Repair
          │
          ▼
Action ledger + typed artifacts + checkpoints + controlled replay
          │
          ▼
Auditable workflow profile for later same-family tasks
```

Planner 和 Verifier 只读；Repair 只接收 verifier 的 discrepancy 和必要状态。每个阶段持久化 artifact/hash、真实 API action、token、真实 latency、预算、初始/中间/final state hash 和官方 strict success。

## 因果边界

组件实验测量同一任务和 seed 下的配对总干预效应。边实验从同一上游 checkpoint 启动，替换一条 typed artifact 后仅重跑下游，估计“给定 checkpoint 的受控下游效应”。这不是对开放世界的自然直接效应，也不等同于一般因果发现。

## 实验链

| 研究问题 | 实验 | 结论 |
|---|---|---|
| RQ1：什么 workflow 值得？ | E1：E、P+E、E+V+R、Full 的配对质量—成本比较 | 任务结构条件下的 Pareto 边界 |
| RQ2：为什么值得？ | E2：组件移除、边 typed-null、passthrough replay control | 模块与信息边的受控效应和机制证据 |
| RQ3：如何持续节省？ | E3：冻结 family stream 上的 workflow profile | 接近 Full 质量下的累计成本/延迟下降 |

P0–P3 的执行规模、冻结边界、统计方法和失败处理见 [CAUSAL_WORKFLOW_RESEARCH_PLAN.md](CAUSAL_WORKFLOW_RESEARCH_PLAN.md)。

## 预期贡献

1. 一种面向有状态 tool-use workflow 的可审计执行与 replay 表示。
2. 一套区分组件总效应、信息边受控效应与 replay 负控制的实验协议。
3. 基于归因证据的 workflow profile：仅复用任务结构与聚合效果，不携带先前会话的敏感状态。
4. AppWorld 上关于复杂协作收益边界、机制和重复任务成本摊销的实证结果。

## 不应主张

- Planner–Executor–Verifier 对所有任务或所有模型更优；
- 单一 benchmark 的结果可泛化至所有真实 agent；
- profile 能永久有效或可跨工具/模型版本无条件迁移；
- 控制性 checkpoint 干预等同于开放环境中的全部因果关系。
