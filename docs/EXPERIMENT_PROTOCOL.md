# Metamorph 论文实验协议（v0.1，历史版本）

> 本文档保留作历史记录，内容已经过期。当前 workshop 以
> [AppWorld Workshop 实验配置](docs/zh-CN/APPWORLD_EXPERIMENT_CONFIG.md) 和
> [Workshop 论文整体架构](docs/zh-CN/PAPER_ARCHITECTURE.md) 为准：正式实验只保留
> E1 系统级比较和 E2 因果组件/通信边审计；E3 lesson transfer 延后到大会议版本。

本文档冻结 workshop 论文阶段的统一实验条件，避免不同 benchmark、不同运行器
和不同预算口径之间不可比较。

## 研究范围

- 主科学 benchmark：τ²-Bench（使用官方当前版本，不使用旧版 tau-bench 任务）。
- 主工程 benchmark：WorkBench。
- 辅助 benchmark：BrowseComp-Plus。
- 暂不加入 WorkArena++、GAIA 或 SWE-bench；它们留到后续投稿和扩展实验。

## 要比较的系统

| 条件 | 路由 | 复杂控制器 | 目的 |
|---|---|---|---|---|
| S0 | 始终 single-agent | 无 | 单 Agent 基线 |
| Complex-only | 始终复杂路径 | 默认 S3 | 衡量固定复杂控制器的成本与收益 |
| Adaptive | planner/router 自动选择 | 默认 S3 | 验证按任务复杂度路由 |
| Oracle | 人工复杂度标签选择 | 默认 S3 | 路由性能上限 |

S1–S4 保留为复杂控制器内部的 legacy ablation，不作为新的主比较条件。默认复杂路径为
S3（自适应 planner + causal replay），S4 的 lesson 不进入主路由实验，避免跨任务顺序
造成混淆。

Oracle 标签必须在运行前由人工根据任务描述、工具依赖、分支、写入风险和恢复需求标注，
不能从 benchmark outcome 或运行轨迹反推。

所有条件必须使用相同模型版本、工具集合、任务集合、最大输出 token、最大总
token、最大工具调用次数和最大墙钟时间。唯一变化应是 scaffold policy。

## 必须记录的指标

### 任务结果

- WorkBench / τ²-Bench：官方最终状态或 reward。
- BrowseComp-Plus：官方答案评分、supporting-document 命中率和引用正确率。
- `blocked`、`invalid handoff`、`tool error` 和 `unsafe action` 单独统计，不能归入成功。
- simple / complex 分桶成功率和每个任务的实际 route。
- Adaptive 的路由准确率、复杂任务漏判率和不必要升级率。

### 资源与治理

- 总 token、prompt token、completion token。
- 墙钟延迟、DAG critical-path latency。
- 工具调用数、写操作数、失败工具数。
- causal edge effect、utility delta、utility lower bound。
- lesson 的 Candidate/Active/Disabled 状态、迁移成功率和负迁移率。

## 因果实验

每个任务先运行 baseline，再固定上游 artifact，对一条 Agent→Agent 边进行
typed-null 干预，只重放受影响的下游子图。边的删除、保留或 lesson admission
必须使用同一任务、同一模型和同一预算口径。

正式实验至少包含：

1. role ablation；
2. edge masking；
3. no-budget control；
4. no-lesson control；
5. held-out task/template transfer；
6. drift 或 tool/evidence perturbation。

## 运行组织

1. 先用每个 benchmark 20–50 个任务做 pilot，检查失败类型和方差。
2. 根据 pilot 方差确定正式样本量，不以单个成功案例作为结论。
3. 每个条件使用相同 task IDs 和重复次数；保留完整 trace，不只保存最终答案。
4. 运行配置、模型标识、benchmark commit、工具 schema hash 和代码 commit 写入
   run manifest。
5. 正式结果只从独立的 held-out 任务计算，lesson 训练任务不能重复计入测试集。
6. 四个主条件共享同一个复杂控制器、模型、工具权限和总预算；Adaptive 的 router
   调用也计入同一预算。

## Workshop 阶段的最小完成标准

- WorkBench 覆盖至少 3 个 domain，而非只运行一个 calendar task。
- τ²-Bench 至少覆盖 retail、airline 和一个最新可用 domain。
- BrowseComp-Plus 至少完成固定语料、官方 scorer 和 citation/supporting evidence 统计。
- 四个主条件均有结果，至少报告总体及分桶成功率、token、延迟和安全/阻断率。
- Oracle 与 Adaptive 的路由标签和决策均保留在 run manifest 中。
- 每个主要结论都有对应 ablation 和 held-out transfer 结果。
