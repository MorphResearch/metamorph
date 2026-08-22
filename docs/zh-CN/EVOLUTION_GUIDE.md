# Metamorph 演进与修改指南

## 推荐的演进顺序

### 1. Baseline Runtime

先实现一个窄任务领域：检查代码仓库、修改允许的文件、运行测试并报告结果。在加入 memory 或自动修改之前，先建立确定性测试。

### 2. 只读 Memory

带有来源信息地记录 episodic runs。只有当 A/B benchmark 证明检索能提高任务成功率，并且成本和负迁移可接受时，才加入自动检索。

### 3. Skills 和策略演进

每次 candidate 只允许修改一个 prompt、policy 或 skill，并限制 diff 大小。使用开发任务、回归任务和隐藏任务进行评估。正式晋级必须经过人工批准。

### 4. Tool Evolution

先从纯函数和解析器开始。每个自动生成的工具都需要有 schema、单元测试、对抗测试、静态检查、权限元数据和沙箱测试。生产环境绝不自动启用具有文件系统、网络或进程权限的工具。

### 5. Improvement Router

根据重复失败的证据选择应该修改的目标：

```text
事实错误       → memory 或 retrieval
流程错误       → skill 或 planner
能力缺失       → tool proposal
优先级错误     → policy 或 planner
裁判不可靠     → evaluator，而不是 agent prompt
```

### 6. Multi-Agent

单 Agent 闭环可测量之后，再加入 worker 和独立 verifier。证据和 candidate 协议稳定后，再加入 evolver。明确限制 Agent 数量、轮数、token 和共享状态写入。

### 7. Meta-Evolution

保留外层安全锚点，并使 evaluator 协议、晋级策略和回滚路径不可变。Meta-Evolution 可以修改诊断或 mutation 策略，但不应被允许修改自己的安全边界。

## 每次修改都要回答五个问题

1. 哪些重复失败或机会触发了这次修改？
2. 最小且最可能有效的干预组件是什么？
3. 哪个确定性测试可以检测改进？
4. 哪种回归或安全失败会拒绝 candidate？
5. 如何恢复之前的版本和配置？

## 建议的实验记录

```yaml
evolution_id: EVO-0001
parent_version: v0
target: prompt | skill | memory_policy | tool | planner
evidence_runs: [run_001, run_004]
baseline_metrics: {}
candidate_metrics: {}
regressions: []
safety_checks: []
decision: reject | staged | promote
approved_by: human | policy
```

第一阶段不要声称“Agent 变聪明了”。更准确、也更可验证的说法是：

> 在相同模型、预算、evaluator 和安全策略下，这个 candidate 提高了指定任务 benchmark 的表现。
