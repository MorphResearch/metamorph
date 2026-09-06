# 一周投稿前清单（最小证据包）

这是一篇短论文/系统与评测 workshop 级别的可完成范围；一周无法诚实保证顶会级的大规模、多模型、多 benchmark 结论。优先顺序是可复现和因果有效性，而不是矩阵大小。

## 必须完成（没有则不要写强结论）

- [ ] DAG schema 与 G0–G3 定义冻结；旧 `fixed_s3` 不再作为实验条件。
- [ ] P0 无模型测试全绿：四 DAG、每节点 checkpoint、hash、不污染 replay、passthrough 负控制。
- [ ] 真实 wall-clock 不使用 AppWorld 冻结时间；token/API/预算记录完整。
- [ ] 12-task P1 dev 筛查完成，或有书面 smoke 停止记录；据此冻结预算、提示、task-family 规则。
- [ ] 18-task P3 AppWorld held-out 表（G0–G3）完成；任务、代码 commit、配置 hash 在开始前冻结。
- [ ] 至少 6 个代表任务的 P2 节点/边/拓扑局部审计，以及有效 replay 的负控制。
- [ ] 冻结 profile policy 在 P3 test 与 always-G0、always-G3 比较。
- [ ] 原始 JSON run records、汇总脚本、失败/排除表、3 张核心图可复跑。
- [ ] Methods、Results、Limitations、Reproducibility appendix 写完；不把 P1 当 test。

## 有时间才做（不得阻塞主线）

- [ ] P3 全部条件增加第 2 seed。
- [ ] MultiAgentBench capability P0 通过后的单 task-family E1。
- [ ] 更大的 30–36 task test、第二模型、消融更多节点、额外 benchmark。

## 本周不做

- [ ] 在线 bandit/RL、自动发现任意 DAG、GNN/扩散结构搜索。
- [ ] 全 DAG Shapley 归因、人类主观评测、超过一个外部 benchmark。
- [ ] 为追求显著性而在 P3 后调任务、调分层、改 DAG 或改成本权重。

## 每日节奏与 go/no-go

| 日程 | 交付物 | 决策门 |
| --- | --- | --- |
| Day 1 | DAG compiler/executor + P0 fake-world tests | 无污染、节点 checkpoint 全通过才继续 |
| Day 2 | 1 个真实任务 × G0–G3 smoke | 单臂有合法 trace 且成本可控才开 P1 |
| Day 3 | P1 dev 12 × 4 + 冻结 profile | 不扩到 P3 前先冻结配置/清单 |
| Day 4 | P2 6 个代表任务的 replay | 仅保留有效 checkpoint pairing |
| Day 5–6 | P3 18 × 4 + profile comparison | 预留失败重跑，不追加新研究线 |
| Day 7 | 分析、图表、论文与复现检查 | 缺项如实降级为 pilot |

## 正式写作前必须拿到的文件

1. `manifest.json`：commit、config/task hash、模型、预算、seed。
2. 每臂 `result.json`：严格成功、成本、trace、artifact hash。
3. P0 acceptance report：四 DAG 与 replay validity 的逐项证据。
4. 一张分层 E1 表、一张 E2 配对效应图、一张 profile utility 图。
5. `EXCLUSIONS.md`：网络、预算、污染、运行时错误和所有被排除 run 的原因。
