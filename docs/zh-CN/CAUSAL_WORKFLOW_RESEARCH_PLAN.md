# 可审计 DAG Workflow Profiles：冻结研究计划（2026-09）

## 一句话问题与结论边界

给定同一任务和同一初始世界状态，Planner 应选择哪一种**任务内 workflow DAG**，才能以最低成本达到可靠成功？当某个 DAG 表现更好时，收益究竟来自哪个节点、信息边或拓扑，而不是来自不同的起始状态或不同的控制器？

本文不把 `Planner → executor → final verifier` 当作消融对象。这是固定控制平面。被比较和审计的是控制平面内部编译出的任务 DAG。

目标是提供可复放的结构证据，并将开发集得到的因果 profile 冻结为下一次同类任务的成本敏感 DAG 选择策略。它不是“任意多智能体一定优于单智能体”的主张。

## 研究假设

- H1（结构条件性）：简单任务中 G0 的成功率不差且成本最低；中等任务中小型串行 DAG 更稳；复杂跨应用任务中带独立检查、汇合或修复的 DAG 可能有净收益。
- H2（可审计性）：在 checkpoint replay 下，删除节点、屏蔽一条信息边、或改变只读分支的调度拓扑，会产生可复放、且不污染基线状态的下游效应。
- H3（可复用性）：仅用 dev 数据冻结的 task-family → DAG profile，在未见 test 任务上达到接近最优 DAG 的成功/成本折中，并优于固定使用 G0 或 G3。

若 H1 未成立，负结论同样有效：对该 benchmark、模型和预算，复杂 DAG 的协调成本没有抵消收益。不得把该结果外推为所有多智能体系统无效。

## 固定控制平面与被审计 DAG

```
task + initial state
        │
        ▼
Planner / DAG compiler ─────► choose G0…G3
        │
        ▼
DAG executor ───────────────► node traces + checkpoints + hashes
        │                                  │
        ▼                                  ▼
final evaluator                      intervention engine
                                           │
                                           ▼
                                    causal profile → next-task selector
```

四个预注册 DAG 族（同一模型、同一工具政策、同一总预算）：

| ID | 图 | 预期用途 |
| --- | --- | --- |
| G0 | `act` | 最低协调成本的单节点基线 |
| G1 | `inspect → act → check` | 小型串行、显式检查 |
| G2 | `inspect_a ∥ inspect_b → join → act → check` | 独立只读信息的并行/汇合 |
| G3 | `inspect → act → check → (repair → final_check)` | 有失败条件的可恢复执行 |

每个节点有类型化输入/输出、工具权限、节点后 checkpoint、artifact hash 与预算记录。`check → repair` 仅在 `NOT_VERIFIED` 时执行；跳过也必须写入 trace。

## 干预定义

每个干预从基线节点前沿的 checkpoint 恢复。恢复前后均计算目录 hash；任何基线 hash 改变即标为污染并排除该条比较。

- **节点干预**：跳过一个节点（例如 G2 的 `inspect_b` 或 G3 的 `check`），只运行合法下游节点。
- **边干预**：保留源节点造成的世界状态，但向目标节点提供 type-correct null artifact；配对的 passthrough replay 是负控制。
- **拓扑干预**：只对没有写冲突的 G2 只读分支，将并行/汇合调度改为等价串行调度；节点集合、输入和预算政策不变。

这些是局部受控效应，不宣称对未测试节点或任意 DAG 的全局 Shapley 归因。

## 一周最小、可投稿的证据包

主证据来自 AppWorld；MultiAgentBench 只做外部结构选择验证，**不**在其上声称 checkpoint 因果审计，除非其运行时通过同等快照能力验收。

### P0：工程验收（无模型调用）

目标：四个 DAG 可编译、可执行；每个已执行节点均有 checkpoint；节点/边/拓扑 replay 不污染基线；负控制与基线一致。

产物：单元测试、固定 fake-world trace、P0 acceptance report。旧 `fixed_s3` 运行仅保留为历史诊断，不参与统计。

### P1：开发集筛查（DeepSeek）

12 个 dev 任务（简单/中等/复杂各 4）× G0–G3 × 1 seed。先以 4 个任务的 smoke matrix 检查单臂成本；若单臂成本或失败率不可接受，先修 runtime 而非扩矩阵。

输出：冻结 task-family 标签规则、预算、prompt/tool policy，及每类进入 P2/P3 的 DAG 候选。P1 不报告为 test 结果。

### P2：机制验证（DeepSeek，AppWorld）

6 个 dev 代表任务（每层 2）上仅测预注册对比：

1. G2：`inspect_b` 节点跳过；
2. G2：`inspect_b → join` typed-null，及 passthrough 负控制；
3. G2：并行/汇合与等价串行只读调度；
4. G3：`check`/repair 路径的节点干预。

每个可行对比 2 次 replay；如果 provider 在 temperature 0 下不支持 seed，报告为两次独立请求而非伪称随机重复。P2 只估计这些局部效应。

### P3：冻结后的正式结果（DeepSeek）

冻结 P1 后的配置和 task-family 规则，在 18 个未见 AppWorld test 任务（每层 6）运行 G0–G3。时间/预算允许则每臂 2 seeds；若只够 1 seed，明确标注为 pilot/short-paper evidence，不作显著性强断言。

E3 是**冻结 profile policy**：从 P1/P2 得到 `family → DAG` 映射，在 P3 test 上与 always-G0、always-G3 比较成功率、token、wall-clock 和 cost-adjusted utility。不要在本周实现在线 bandit、RL 或复杂 DAG 生成器。

### 外部补充：MultiAgentBench（严格 timebox）

最多半天完成 capability P0：安装/许可证、任务可复现、同一预算、是否能冻结初始状态。通过后，选一个显式协作 task family 跑 G0–G3 的选择实验；未通过则在论文中如实说明外部验证未纳入本稿，不拖慢 AppWorld 主结果。

## 指标与分析

主要终点：AppWorld strict success。次要终点：官方 reward、输入/输出 token、真实 wall-clock、工具/API 调用、美元成本、重放污染率。

报告 task-paired 差异、按预注册复杂度层分层的 bootstrap 置信区间，以及每个任务的原始运行记录。只在配对 replay 有效、来源 checkpoint hash 不变时纳入 E2。

成本效用在冻结前定义，例如 `success - λ × normalized_cost`；展示多个 λ 的敏感性曲线，避免事后挑选 λ。

## 明确删除/延后

- 删除旧固定 S3 的 E1/E2 主结论与其组件消融。
- 延后任意 DAG 生成、GNN/扩散式结构搜索、在线 bandit、Shapley 穷举、人类实验、第三个大 benchmark。
- 不把未通过 P0 的运行、网络故障或模型预算耗尽计入科研主表。

## 通过门槛与停止规则

只有 P0 全部通过才允许 P1。P1 smoke 若 G0–G3 任一无法产生 trace/checkpoint 或大多数臂在未行动前耗尽预算，停止扩矩阵，修复 DAG runtime。P3 前冻结代码 commit、配置 hash、任务清单和分析脚本；之后不按结果替换任务或修改 DAG 定义。
