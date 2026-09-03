# AppWorld Workshop 实验配置（v0.2）

本文档冻结 workshop 论文阶段的 AppWorld 实验组织。当前版本只保留 E1 和 E2
作为正式实验；E3 lesson 迁移暂不纳入 workshop 主结果，留作后续大会议扩展。
论文的主要贡献是 **因果感知的 multi-agent scaffold 审计**；Adaptive routing、
planner、verifier、JSON contract 和预算控制都是支撑组件。

## 1. 研究问题

### 主问题

多 Agent scaffold 中的角色和 Agent→Agent 通信边是否在 stateful tool-use 任务中
带来可测量的因果收益？

### 次问题

在固定预算下，复杂架构相对于 single-agent 的收益来自哪些角色和通信边，是否
能够被可重复地识别？

### 不主张的结论

本文不主张 planner 本身是一种新的规划算法，也不主张“任务越复杂，Agent 越多
越好”。论文只研究：哪些协作结构在什么条件下值得付出额外成本。

## 2. AppWorld 数据配置

当前本地数据清单：

| Split | 任务数 | 本文用途 |
|---|---:|---|
| `train` | 90 | pilot、生成 router 特征和冻结候选复杂度规则；lesson 暂留后续版本 |
| `dev` | 57 | 调整并冻结 router 阈值、检查运行稳定性和确定最终实验配置 |
| `test_normal` | 168 | 正式普通难度评估 |
| `test_challenge` | 417 | 正式长链路、高约束压力评估 |

AppWorld 的 `normal/challenge` 是官方数据 split，不等同于每个任务的
`ground_truth/metadata.json` 中的 `difficulty`。difficulty 只用于事后分层分析，
不作为主实验中 Adaptive 的输入，也不直接充当 test oracle。

正式运行时记录：

- AppWorld commit：`a072b7a86e7c1d5b1d7175659d750ebb9b79f10a`；
- task ID、task generator/scenario ID 和官方 split；
- 每个任务的官方 reward 和 individual evaluation details；
- task 的结构特征，但不记录或使用测试任务的 ground-truth solution 来路由。

## 3. 统一运行条件

四个主条件和所有消融必须使用相同的：

- AppWorld commit 和数据版本；
- foundation model、model version 和 temperature；
- system prompt 和 tool schema；
- task IDs、随机 seeds 和执行顺序；
- `max_steps`、`max_errors`、token、tool-call、latency 预算；
- evaluator 和安全策略。

### Workshop 初始预算

以下是 pilot 后需要冻结的初始候选值，不是最终结果：

```text
temperature = 0
max_steps = 20
max_errors = 5
max_total_tokens = 30,000 / task
max_tool_calls = 12 / task
max_latency_seconds = 180 / task
allow_write = true
```

Adaptive 的 router token 和 latency 计入同一个 per-task 总预算。Oracle 的人工标签
在运行前离线生成，不计入在线 token，但要在论文中说明它是不可部署的理论上限。

预算违规、unsafe action、错误写入和提前终止不能从统计中删除，必须作为失败或
独立治理指标记录。

## 4. 实验 E1：系统级四条件比较

### 目的

验证在普通和 challenge 任务混合时，任务自适应架构是否比两个固定策略更有效。

### 条件

| Condition | 行为 | Lesson |
|---|---|---|
| `S0` | 始终 single-agent | 关闭 |
| `Complex-only` | 始终复杂路径，默认 S3 | 关闭 |
| `Adaptive` | router 选择 S0 或 S3 | 关闭 |
| `Oracle` | 使用预先冻结的人工 simple/complex 标签 | 关闭 |

E1 关闭 lesson 是为了单独测量 routing 和 scaffold 的基础效果，避免 lesson 顺序
把四种条件混在一起。lesson 的效果由 E3 独立测量。

### 数据

- pilot：从 train/dev 中选择固定任务，检查运行稳定性和方差；
- final：`test_normal` 和 `test_challenge` 使用相同的预先冻结任务集合；
- 计算允许时运行完整 test split；否则在任何模型运行前固定分层子集，建议至少
  `50 normal + 50 challenge`，并按 task generator/scenario 分层。

### 主要结果

```text
Q = AppWorld official reward
```

报告：

- normal reward；
- challenge reward；
- overall reward；
- task completion rate；
- budget-constrained completion rate。

### 路由和成本结果

- Adaptive route accuracy；
- complex-task under-routing rate；
- simple-task unnecessary escalation rate；
- Adaptive 与 Oracle 的 route agreement；
- total/input/output tokens；
- latency；
- tool calls 和 write actions；
- budget exhaustion、tool error 和 safety violation。

## 5. 实验 E2：因果组件与通信边审计

### 目的

这是论文的核心实验。它不比较哪个 planner 更强，而是测量固定 scaffold 中某个
角色或通信边的边际贡献。

### 基础架构

固定使用 S3：

```text
Planner → Executor → Verifier → isolated replay
```

不在 E2 中使用 Adaptive router，以免把路由误差和组件因果效应混在一起。

### 组件级消融

| 条件 | 关闭内容 |
|---|---|
| `Full-S3` | 无 |
| `No-Planner` | planner |
| `No-Verifier` | verifier |
| `No-Replay` | causal replay |
| `No-JSON-Contract` | 结构化 handoff 校验 |
| `No-Budget-Gate` | 预算 gate，仅作为安全对照，不作为部署策略 |

### 通信边干预

预先选择少量关键边进行 typed-null masking：

```text
planner → executor
executor → verifier
planner → verifier（若图中存在）
```

每次只干预一条边：

1. 固定任务、model、seed、环境初始状态和预算；
2. 保留不受影响的上游 artifact；
3. 用 typed-null artifact 屏蔽一条通信边；
4. 只重放受影响的 downstream subgraph；
5. 不污染官方任务状态；
6. 使用同一个官方 evaluator 重新评分。

### 因果效应

对于边或组件 `e`：

```text
Effect_e = Q_full - Q_masked_e
```

如果考虑成本：

```text
NetEffect_e = U_full - U_masked_e
```

其中 `U` 只作为辅助的成本质量指标，E2 的主要结论仍使用固定预算下的官方
reward。

每个 `Effect_e` 报告：

- mean effect；
- 95% paired bootstrap confidence interval；
- simple/complex 或 normal/challenge 分层 effect；
- token、latency 和 tool-call delta；
- safety 和 budget violation delta。

## 6. E3：后续大会议扩展，不纳入本轮主结果

E3 的目标是验证经过因果验证的 lesson 能否跨任务族、跨应用组合迁移。当前
workshop 不运行 E3，也不在主论文中声称存在 lesson transfer gain。后续扩展时
使用以下流程：

```text
train source tasks → Candidate → dev validation → freeze Active store → test target tasks
```

候选 lesson 不能直接进入 Active store；lesson 也不能增加工具权限、修改
`allow_write`、绕过 JSON contract、预算或 evaluator。后续应比较 No-Lesson、
Summary-Lesson、Causal-Lesson 和 Random-Lesson，并报告负迁移率及安全回归率。

## 7. 统计方法

### 任务级配对

四个主条件必须在同一 task ID 上进行配对比较。不能分别抽取不同任务后比较总体
平均值。

### 置信区间

默认使用 task-level paired bootstrap，报告 95% confidence interval。二元成功率
同时报告任务数量和成功数量。

### 主要比较

```text
Adaptive - S0
Full-S3 - intervention
Full-S3 - S0
```

### 多次运行

正式实验至少使用多个 seed；如果计算有限，优先保证任务数量和配对设计，再增加
seed。所有 seed 必须写入 manifest。

## 8. 运行产物和日志

每个实验保存：

```text
experiments/appworld/<experiment_id>/
├── manifest.json
├── task_manifest.json
├── runs/<condition>/<task_id>/<seed>/result.json
├── traces/<condition>/<task_id>/<seed>/
├── lessons/candidates.jsonl
├── lessons/active.jsonl
├── lessons/disabled.jsonl
└── tables/
```

`manifest.json` 至少包含：

- experiment ID；
- git commit；
- AppWorld commit；
- model 和 provider；
- prompt/schema hash；
- budget；
- task split、task IDs 和执行顺序；
- seed；
- condition；
- lesson store snapshot；
- evaluator version。

## 9. Workshop 论文的最小完成标准

### 必须完成

- E1 四条件 AppWorld 主结果；
- 若资源有限，E1 至少完成 `S0 vs Full-S3`，Adaptive/Oracle 作为补充；
- normal/challenge 分开报告；
- fixed-budget 配对比较；
- E2 至少一个 role ablation 和两条 edge masking；
- 官方 reward、token、latency、tool calls 和 safety 统计；
- 真实 fixed-context downstream replay；
- 完整 manifest 和可复现实验日志。

### 后续大会议扩展

- E3 Causal-Lesson transfer；
- Raw-Trajectory、Summary-Lesson 和 Random-Lesson 对照；
- drift/tool perturbation；
- 更大的 AppWorld test split；
- WorkBench 和 τ²-Bench 作为补充实验。

论文主线保持为：

```text
因果审计 multi-agent scaffold
    → 识别真正有用的角色和通信边
    → 在固定预算下验证收益
    → 将正向证据转化为可治理的 lesson
    → 在 held-out AppWorld 任务上测试迁移
```
