# 论文大纲：Auditing and Reusing Workflow-DAG Structure for Tool Agents

## 题目候选

**Checkpointed Causal Auditing for Cost-Sensitive Workflow-DAG Selection**

中文工作题目：**面向工具 Agent 的可复放 DAG 结构因果审计与成本敏感复用**。

## 摘要应讲的故事

现有 agent workflow 常把“多角色/多智能体是否更好”当成整体比较，混淆了起始状态、执行轨迹、通信与结构本身。我们固定控制平面，让 planner 为任务选择一个小型、类型化 workflow DAG；在 stateful 环境中记录节点 artifact、checkpoint 和 hash。借助不污染基线的 checkpoint replay，我们估计节点、信息边和只读分支拓扑的局部受控下游效应。开发集的证据被冻结为成本敏感 profile，并在未见任务上选择 DAG。结果预期显示结构收益具有任务条件性，而非复杂图普遍优于单 agent。

摘要只在数据支持后填入三类数字：P0 replay validity、AppWorld 分层成功/成本、冻结 profile 的 held-out utility。

## 1. Introduction

1. 工具 agent 的 workflow 选择影响成功、延迟和成本；现有整体 MAS 比较难解释“为什么”。
2. 状态ful任务使事后删除一个组件不再是有效反事实：世界状态已经变化。
3. 缺口：缺乏对 workflow 内部结构的、可复放且基线不污染的局部因果证据；也缺乏将证据转成下一任务选择的简单机制。
4. 贡献：类型化 DAG compiler/executor、checkpoint replay intervention engine、冻结 causal profile policy、AppWorld 主证据与 time-boxed 外部验证。

## 2. Problem Definition

固定控制平面 `planner → DAG executor → final evaluator`。定义任务内 DAG、节点 artifact、边、初始状态、成本和严格成功。写出节点/边/拓扑受控效应的估计对象与 checkpoint 来源；明确识别条件（确定性的恢复、固定上游、未污染 hash、配对负控制）。

## 3. System

### 3.1 DAG compiler

预注册 G0–G3，验证无环、类型、工具权限和条件分支；不把本周系统包装成任意 DAG 生成器。

### 3.2 DAG executor and observability

每节点后持久化 artifact/hash/checkpoint/budget/真实 wall-clock；代码 executor 保持安全 batch policy。

### 3.3 Intervention engine

节点 skip、typed-null edge mask、只读 parallel-to-serial topology，及 passthrough replay。说明污染检测和失效样本处理。

### 3.4 Frozen profile policy

仅从 dev 选择 `task family → Gk`；test 不再更新。以成本效用选择与 always-G0/G3 作比较。

## 4. Experimental Protocol

按 P0–P3 写入冻结任务清单、预算、模型（DeepSeek）、种子、分层规则、主要/次要指标和停止规则。主 benchmark 为 AppWorld；MultiAgentBench 仅在 capability gate 通过时写为外部补充。

## 5. Results

1. P0：编译、checkpoint、hash、replay negative-control 通过率。
2. E1：每个复杂度层 G0–G3 的 strict success、token、wall-clock、cost。
3. E2：预注册节点/边/拓扑的配对下游效应与 replay validity。
4. E3：冻结 profile 在 held-out test 的 utility 与固定 DAG 基线。
5. External（若通过 timebox）：MultiAgentBench 的结构选择结果；否则删去主表。

## 6. Discussion and Limitations

局部而非完整因果图归因；小 DAG library；模型/提示/预算依赖；AppWorld 复杂度标签的构造效度；单 seed 的不确定性；外部 benchmark 不具备快照时不能声称同类因果审计。

## 附录/复现包

冻结配置与 manifest、DAG schema、每个 run 的 trace/artifact/checkpoint hash、排除原因、分析脚本、旧 fixed-S3 诊断与主结果的隔离说明。
