# 一周可投稿的最小实验计划

## 目标与定位

目标不是证明多智能体总是更好，而是证明下述三个可检验命题：

1. 对 stateful tool task，workflow DAG 的成功/成本收益依赖任务结构；
2. checkpoint replay 可以对少量预注册的节点、信息边、拓扑对比给出不污染基线的局部效应证据；
3. 用 dev 数据冻结的 `task family → DAG` 规则，能在 held-out task 上优于固定的昂贵 DAG。

这是系统/评测 workshop 或 short-paper 的现实定位。不要承诺全局因果图、任意 DAG 生成或普适多智能体优势。

## 必投版本：只保留 AppWorld

AppWorld 是唯一主 benchmark。它提供可保存/恢复状态的环境，因此能支撑论文真正的技术贡献：可复放的结构干预。MultiAgentBench 仅在主结果完成后、半天以内 capability gate 通过时作为附录外部结果；它不是投稿阻塞项。

## 固定对象与前置冻结

控制平面固定为 `planner/DAG compiler → DAG executor → final evaluator`。实验对象只有四个 task-internal DAG：

| ID | DAG | 角色 |
|---|---|---|
| G0 | `act` | 最低成本基线 |
| G1 | `inspect → act → check` | 小型串行结构 |
| G2 | `inspect_a ∥ inspect_b → join → act → check` | 只读 fork/join |
| G3 | `inspect → act → check → repair → final_check`（条件执行） | 检查/修复结构 |

在正式 test 前冻结：代码 commit、模型 DeepSeek v4-pro、temperature、prompt/tool policy、总 token/API/错误/时间预算、任务清单、公开指令驱动的复杂度标签、主要指标、成本效用权重和分析脚本。

## 最小但足够有说服力的证据包

### Gate 0：工程有效性（已完成；不计科研结果）

P0 无模型测试必须证明：四图合法；每个 completed node 有 checkpoint/hash；node skip、typed-null edge mask、只读 topology serialization 可运行；来源 checkpoint hash 不变；passthrough control 不改变基线 artifact。

当前状态：通过。见 `experiments/appworld/P0_DAG_ACCEPTANCE.md`。

### Gate 1：单任务 smoke（只做诊断）

同一简单 dev task 上跑 G0–G3。每个 arm 必须有 `result.json`、节点 trace/checkpoint、真实 monotonic latency、完整 token usage。若没有，先修工程；该阶段不能进入任何表或图。

### E1：结构选择主结果（必须）

**P1 dev 筛查：**12 个任务（简单/中等/复杂各 4）× G0–G3 × 1 seed。用途仅为选择 profile，不报告为 held-out 主结果。

**P3 held-out：**18 个未见 test 任务（每层 6）× G0–G3 × 1 seed。主要终点为 AppWorld strict success；次要为真实 wall-clock、input/output token、工具/API 调用和 USD 成本。以 task-paired 差异和 cluster bootstrap CI 报告，不把同一 task 的四个 arm 当独立样本。

一周内不强制 2 seeds；若资源允许，优先给 P3 的复杂层增加第 2 seed。单 seed 必须写为局限，而非声称统计稳定性。

### E2：因果审计主结果（必须，少而硬）

在 6 个 dev 代表任务（每层 2）只做下面四个预注册比较；每个有效 replay 重复两次：

1. **节点：**G2 跳过 `inspect_b`；
2. **边：**G2 mask `inspect_b → join`，同时运行 passthrough replay；
3. **拓扑：**G2 并行只读 fork/join 改为等价串行调度；
4. **恢复：**G3 跳过 `check`/repair 路径（只在条件分支实际触发的任务上解释）。

只有在基线来源 hash 未变、恢复成功、下游 trace 完整的 pair 才纳入效应图。每项报告 raw task-level data；无效/污染/基础设施失败单列，不丢弃。

### E3：复用结论（必须但实现简单）

由 P1/P2 dev 结果写成一个**固定、可读的** profile：例如 `simple → G0`、`medium → G1`、`complex → G2 或 G3`。在 P3 held-out task 上比较该 profile 与 always-G0、always-G3。

主要图为 success–cost Pareto/utility；不要实现在线 bandit、RL 或动态 DAG discovery。

## 统计与写作规则

- 主指标只用 strict success；reward 只作诊断。
- 成本先报告原始 token/time/USD；utility 的 λ 在看 test 前冻结，并展示至少 3 个 λ 的敏感性。
- E2 声称的是从特定 checkpoint 出发的局部受控下游效应，不是自然直接效应或完整因果发现。
- 不因 P3 结果改 DAG、任务、分层或 λ；任何 P3 后重跑都保留原 run，并给出原因。

## 明确删除的工作

- 不做第二主 benchmark、第三种模型、human study；
- 不做全节点/全边 Shapley、任意图搜索、GNN/扩散生成器；
- 不做在线 profile learning；
- 不把旧 fixed-S3 或当前 smoke 结果计入正式统计。

## Go / no-go

1. P0 未过：不调用 DeepSeek。
2. Gate 1 任一 DAG 无完整 trace/result：停止矩阵，修 runtime。
3. E1 中 G2/G3 在简单任务明显更贵且不更成功：这是论文的有效负结果，保留，不强行改结构。
4. E2 无法实现真实 checkpoint restore + contamination check：删除“因果审计”主张，改投 workflow profiling/ablation 论文，或暂停投稿。
