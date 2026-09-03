# Workshop 论文结构大纲：Causal Auditing of Multi-Agent Scaffolds

本文档是写作结构和证据清单，不是论文正文。当前版本只覆盖 AppWorld、E1 和 E2；
E3 lesson transfer 留到后续大会议版本。

## 论文整体主线

```text
问题：复杂 multi-agent scaffold 的收益来自哪里？
  ↓
方法：在固定预算和固定上下文下，对组件与 Agent→Agent 边做因果干预
  ↓
E1：比较 single-agent、复杂架构和 adaptive routing 的系统级表现
  ↓
E2：识别 Planner、Verifier、Replay 和关键通信边的边际贡献
  ↓
结论：解释哪些 scaffold 结构值得保留，以及它们的适用条件和代价
```

论文不主张 planner 是新的规划算法，也不主张 multi-agent 在所有任务上都优于
single-agent。论文主张的是：**multi-agent scaffold 应该被当作可以进行因果审计的
模块化系统，而不是只能通过整体平均分评价的黑盒。**

---

## 1. Introduction

### 1.1 背景

- Stateful tool-use 任务要求 Agent 读取状态、调用工具并执行有约束的写操作；
- multi-agent scaffold 通常增加 Planner、Executor、Verifier、Replay 等角色；
- 增加角色可能提升任务质量，也可能带来额外 token、延迟、工具调用和失败路径。

### 1.2 问题缺口

- 只比较最终成功率，无法知道哪个组件真正有用；
- 组件之间存在通信和上下文依赖，普通 ablation 可能混入分布变化；
- “复杂任务需要更多 Agent”的直觉不能替代任务级、固定预算的证据。

### 1.3 研究问题

1. 复杂 scaffold 相对于 single-agent 在哪些 AppWorld 任务上有收益？
2. 这些收益来自哪些角色和 Agent→Agent 通信边？
3. 这些组件的收益是否会被额外成本、安全风险或预算消耗抵消？

### 1.4 方法概览

用一张总览图展示：

```text
task → router / fixed policy → scaffold DAG → typed artifacts → evaluator
                                      ↘ edge intervention / replay
```

### 1.5 贡献列表

贡献最多写三条：

- 提出面向 stateful tool-use scaffold 的因果审计框架；
- 提出固定上下文的通信边干预和 downstream replay 协议；
- 在 AppWorld 上同时给出系统级比较和组件/通信边级因果证据，并报告质量、成本和安全。

不要把 Adaptive routing、JSON contract 或 lesson transfer 写成独立主贡献。

### 1.6 本节需要的证据

- 一张动机示例图：整体分数相同但内部组件贡献不同；
- 一张贡献与实验对应表；
- 不放最终结果细节，只给出研究问题和方法预览。

---

## 2. Related Work

### 2.1 Multi-agent systems and scaffolds

- multi-agent role decomposition；
- planner-executor-verifier 结构；
- 单 Agent 与多 Agent 的性能/成本权衡。

### 2.2 Tool-use and stateful environments

- tool-use agent；
- API 调用和环境状态变化；
- AppWorld 等可验证的 tool-use benchmark。

### 2.3 Agent evaluation and efficiency

- 任务成功率和官方 reward；
- token、延迟、tool calls、预算和安全指标；
- 固定预算下的质量比较。

### 2.4 Causal analysis and ablation in agent systems

- component ablation 的常规做法；
- causal intervention、mechanistic analysis 或 edge-level analysis；
- 本文与普通“去掉模块后重新跑一遍”的区别：固定上游 artifact、typed-null masking、
  downstream replay。

### 2.5 本文定位

| 维度 | 现有常见做法 | 本文 |
|---|---|---|
| 分析对象 | 整体 Agent 系统 | 角色和通信边 |
| 干预方式 | 删除组件后重新运行 | 固定上下文的 typed-null intervention |
| 主要结果 | 最终成功率 | 因果 effect + 成本/安全变化 |
| 环境 | 静态问答或单步任务较多 | Stateful tool-use AppWorld |

本节不要过度声称“首次”，应准确区分已有 causal agent analysis 与本文的具体组合。

---

## 3. Problem Setting and Scaffold

### 3.1 任务定义

定义每个任务包含：用户目标 `x`、初始环境状态 `s0`、工具集合 `T`、Agent 动作序列
`a1:T`、最终环境状态和官方 evaluator reward `Q`。

### 3.2 Scaffold 表示

```text
Planner → Executor → Verifier → Causal Replay
     └──────────────→ Verifier（若图中存在 planner 直接证据）
```

对每个节点说明输入、输出、工具权限、失败处理、预算消耗和日志字段。

### 3.3 结构化 artifact contract

定义 Planner→Executor 的 JSON contract，至少包含 task interpretation、ordered
actions、expected state changes、verification criteria、risk/write requirements 和
budget hint。非法 JSON、字段缺失和 schema 不匹配必须计入结果。

### 3.4 四个系统条件

| 条件 | 配置 | 用途 |
|---|---|---|
| S0 | 始终 single-agent | 外部基线 |
| Complex-only | 始终 Full-S3 | 固定复杂架构 |
| Adaptive | router 选择 S0 或 Full-S3 | 系统级自适应策略 |
| Oracle | 离线人工标签选择 S0 或 Full-S3 | 理论路由上限 |

E1 关闭 lesson；E2 固定 Full-S3，不使用 Adaptive router。

### 3.5 预算和权限模型

统一定义 `max_steps`、`max_total_tokens`、`max_tool_calls`、`max_latency_seconds`、
`max_errors`、`allow_write`、tool whitelist、evaluator 和安全策略。Router token 和
latency 必须计入 Adaptive 的同一任务预算。

---

## 4. Causal Audit Method

### 4.1 因果对象和 estimand

对组件或通信边 `e` 定义：

```text
Effect_e = Q(full) − Q(masked_e)
```

质量指标 `Q` 使用 AppWorld official reward；成本和安全作为独立结果报告。

### 4.2 组件级干预

固定 Full-S3，分别构造 No-Planner、No-Verifier、No-Replay、No-JSON-Contract 和
No-Budget-Gate。每次只改变一个组件，其他 prompt、模型、seed、任务、预算和 evaluator
保持不变。

### 4.3 通信边干预

至少选择 `planner → executor`、`executor → verifier`，以及实现中存在的
`planner → verifier`。每次只屏蔽一条边，使用与 schema 类型一致的 null artifact。

### 4.4 Fixed-context downstream replay

1. 在相同初始状态下运行并保存上游 artifact；
2. 对一条通信边执行 typed-null masking；
3. 保留未受影响的 artifact；
4. 只重放受影响的 downstream subgraph；
5. 使用官方 evaluator 评分；
6. 记录状态污染、失败和预算变化。

### 4.5 混淆因素控制

同一 task ID 配对；相同模型、temperature、prompt、tool schema、seed 和初始环境；
任务顺序预先冻结；禁止使用 test ground-truth difficulty 作为 Adaptive 输入；失败和
预算耗尽不能静默删除。

### 4.6 统计输出

每个 effect 报告均值、中位数、paired bootstrap 95% CI、normal/challenge 分层结果，
以及 token、latency、tool calls、safety 的变化。

---

## 5. Experimental Setup

### 5.1 Benchmark 和数据划分

使用 AppWorld：train 用于 pilot、router 特征和规则冻结；dev 用于阈值调整、运行稳定
性检查和配置冻结；test_normal 和 test_challenge 用于正式评估。正式 test 运行前固定
task IDs，不能根据测试结果修改任务集合、路由规则或 scaffold。

### 5.2 运行条件

统一记录 AppWorld commit、代码 commit、模型版本、prompt/schema hash、temperature、
seed、预算、evaluator 版本和执行顺序。

### 5.3 E1 配置

四个条件在同一批任务上运行，lesson 关闭。主要比较：

```text
Adaptive − S0
Adaptive − Complex-only
Oracle − Adaptive
Full-S3 − S0
```

### 5.4 E2 配置

固定 Full-S3，运行组件消融和通信边 masking。E2 不引入 Adaptive，避免路由误差与
组件因果效应混合。

### 5.5 指标

主要质量指标：AppWorld official reward、task completion rate、budget-constrained
completion。成本和治理指标：input/output/total tokens、latency、tool calls、write
actions、tool errors、budget exhaustion、safety incidents、JSON contract violation。

### 5.6 可复现性和运行产物

每个运行保存 manifest、task manifest、result、trace、seed、condition 和 evaluator
版本。失败样本保存失败类别和最后状态，不能只保留聚合表。

---

## 6. E1 系统级结果

### 6.1 结果目的

回答：在混合难度的 AppWorld 任务中，single-agent、固定复杂架构和自适应路由的整体
质量与成本如何变化？

### 6.2 主结果表

行使用 S0、Complex-only、Adaptive、Oracle；列使用 overall/normal/challenge official
reward、completion rate、total tokens、latency、tool calls 和 safety incidents。

### 6.3 路由结果

报告 Adaptive 与 Oracle 的 route agreement、complex-task under-routing、simple-task
unnecessary escalation 及每种路由的预算消耗。

### 6.4 E1 图表

- 主结果表；
- reward-cost Pareto 图；
- normal/challenge paired difference 图；
- Adaptive 与 Oracle 的路由混淆矩阵。

### 6.5 E1 结论边界

E1 只能说明系统级性能和路由现象，不能单独证明某个组件的因果作用；组件解释必须
来自 E2。

---

## 7. E2 因果消融结果

### 7.1 结果目的

回答：Full-S3 的收益究竟来自哪些组件和通信边？

### 7.2 组件消融结果

主表比较 Full-S3、No-Planner、No-Verifier、No-Replay、No-JSON-Contract。每行包含
official reward difference、completion difference、token/latency/tool-call difference、
safety/budget difference 和 paired bootstrap CI。

### 7.3 通信边结果

用 effect plot 展示每条边的 `Effect_e`、95% CI、normal/challenge 分层 effect 和下游
失败类型。

### 7.4 机制案例

选择能代表必要、冗余、成本不划算和条件性贡献的任务案例。每个案例提供完整 trace、
artifact 差异和 evaluator 结果，不能只展示成功样本。

### 7.5 E2 结论边界

结论应写成“在当前 AppWorld、模型、预算和 scaffold 下的条件性因果贡献”，不能泛化
成所有 Agent 系统中的普遍规律。

---

## 8. 成本、安全与稳健性分析

### 8.1 成本分析

分析质量提升对应的 token 增量、latency 分布、tool calls、write actions、budget
exhaustion rate 和 reward-cost Pareto frontier。

### 8.2 安全与权限分析

统计 unsafe action、错误写入、tool whitelist violation、`allow_write` 违规、verifier
漏检和 JSON contract 绕过。安全事件不能从主结果中删除。

### 8.3 稳健性分析

至少包含不同 seed、normal/challenge、不同任务子集、轻微预算变化和失败重试策略。

### 8.4 统计呈现

主结果使用 task-level paired bootstrap 95% CI。二元成功率同时报告成功数和任务总数。
多个组件/边同时检验时，说明多重比较处理，或标记为探索性分析。

---

## 9. Discussion and Limitations

### 9.1 主要发现解释

围绕三个问题讨论：复杂架构何时比 S0 更有价值；哪些组件/边是主要贡献来源；质量收益
是否值得成本与安全代价。

### 9.2 对系统设计的启示

- 默认保留有正向 effect 且成本可接受的组件；
- 删除稳定无效或高成本组件；
- 对只在 challenge 任务有效的组件使用条件启用；
- 将 router 视为系统控制层，而不是论文核心算法。

### 9.3 局限性

- AppWorld 代表特定的 API/tool-use 生态；
- 结论依赖当前 foundation model、prompt、预算和 scaffold 实现；
- Oracle 不可部署，只是理论上限；
- fixed-context replay 的实现质量会影响边级因果估计；
- workshop 版本不验证 lesson 的跨任务迁移；
- 结果不能直接推广到开放式 web research 或 coding benchmark。

### 9.4 未来工作

- E3 validated causal lesson transfer；
- WorkBench 和 τ²-Bench 补充验证；
- tool/API drift；
- 更大规模和跨模型实验；
- 在线因果审计与自动 scaffold pruning。

---

## 10. Conclusion

### 10.1 结论结构

只总结三点：multi-agent scaffold 的整体表现不能替代组件级解释；因果组件/通信边
审计可以量化不同结构的条件性贡献；在固定预算、安全和 evaluator 约束下，系统设计
应保留有证据支持的结构，而不是默认增加 Agent 数量。

### 10.2 不应在结论中声称

- multi-agent 普遍优于 single-agent；
- Adaptive 一定达到或超过 Oracle；
- 当前 AppWorld 结果适用于所有 benchmark；
- lesson transfer 已经在本 workshop 中得到验证。

---

## 当前版本的实验边界

```text
Workshop paper
  └── AppWorld
      ├── E1：S0 / Complex-only / Adaptive / Oracle
      └── E2：组件消融 + 通信边 masking + downstream replay

Future conference extension
  └── E3：validated causal lesson transfer
```
