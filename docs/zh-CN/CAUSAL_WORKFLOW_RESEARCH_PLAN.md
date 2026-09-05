# 可审计 Workflow Profile：论文与实验计划

## 论文主线

有状态 Agent workflow 的常见评估把整个系统当作黑盒：完整系统的端到端分数与重新运行的 ablation 无法区分组件、通信信息和环境轨迹重采样各自造成的差异。尤其在重复出现的任务族中，系统会在新会话中反复支付规划、核验和协调的成本，却不能安全复用已经验证过的 workflow 知识。

本项目提出 **Auditable Workflow Profiles**。系统将 workflow 表示为可执行、可记录、可 checkpoint 与可受控重放的图；在相同初始状态或固定上游 checkpoint 下对组件和通信边干预；再将得到的结构化、非敏感的质量—成本证据沉淀为 profile，供后续同类新任务选择足够而非最大的 workflow。profile 不保存先前用户任务内容、工具返回或环境状态。

本文只主张受控实验条件下的组件总效应与给定 checkpoint 的下游受控效应，不主张发现所有 Agent 系统的一般因果规律。

## 系统

固定节点为 Planner、Executor、Verifier、Repair；候选 workflow 为：

```text
E       = Executor
P+E     = Planner → Executor
E+V+R   = Executor → Verifier → [discrepancy-only Repair]
Full    = Planner → Executor → Verifier → [discrepancy-only Repair]
```

所有条件共享相同模型、工具、初始世界、安全 batch/code executor、预算和官方 evaluator。每次运行保存 initial/checkpoint/final state hash、typed artifact hash、真实 API action ledger、模型参数、token、真实 latency、预算终止原因与 strict success。

## 研究问题

- **RQ1（E1）**：不同任务结构下，哪种 workflow 有净质量—成本收益？
- **RQ2（E2）**：Planner、Verifier、Repair 和 `Planner→Executor`、`Executor→Verifier` 信息边的受控干预效应是什么？
- **RQ3（E3）**：能否将 E1/E2 的证据编译为跨会话复用的 workflow profile，在重复任务流中以接近 Full 的质量降低累计成本和延迟？

## 分阶段执行

| 阶段 | 数据与规模 | 条件 | 目的与退出门槛 |
|---|---|---|---|
| P0 / E0 | 12 个 train/dev | Full、两条 typed-null 边、passthrough replay control | trace/checkpoint/超时/负控制验收；无 source checkpoint 污染，所有异常持久化 |
| P1 / E1 | 20 个 train/dev × 4 workflows | E、P+E、E+V+R、Full | 筛查结构族与质量—成本边界；冻结 P2 分层抽样和 task-family rubric |
| P2 / E2 | 12 个 train/dev × 7 条件 × 2 seeds | Full、三组件干预、两条边 mask、replay control | 确认机制信号可解释且非 replay 伪影 |
| P3 / E1 | 50 个冻结 test × 4 workflows × 3 seeds | E、P+E、E+V+R、Full | 主质量—成本与结构异质性结果 |
| P3 / E2 | 24 个冻结 test × 7 条件 × 3 seeds | 同 P2 | 正式受控干预结果 |
| P3 / E3 | 预注册 family streams | Always-E、Always-Full、per-task router、profile | 测累计 token/latency、成功率、失效检测和恢复 |

P0/P1/P2 的数据只能用于工程、结构 rubric 和选择规则开发；不得混入 P3 主统计。P3 前应冻结 task manifest、profile 规则、模型/提示词/预算、统计脚本和失败处理规则。

## E2 estimand 与统计

组件总效应按同一任务和 seed 的配对差值估计。边效应从相同上游 checkpoint 开始，仅替换目标 artifact 并重跑受影响下游；它命名为“给定 checkpoint 的受控下游效应”。passthrough replay 是负控制：它重放下游但不替换 artifact，用于检验 replay 实现不会系统性污染结果。

主要指标为 AppWorld official strict success；次要指标为 total tokens、真实 latency、工具/API 调用、写操作、postcondition 证据和错误类别。报告任务聚类的 paired bootstrap 95% CI；二元成功率同时报告配对置换检验或 McNemar 结果。网络/供应商故障单列为基础设施失败，不当作架构效应。

## E3 profile 协议

profile 的输入只能是合法的任务结构特征（跨 app、实体数、条件/约束数、写操作数、可验证 postcondition 数、批量特征）。它保存推荐 workflow、效果/成本区间、适用范围、模型/工具版本和失效条件。新任务若不在 profile 的适用范围或置信度不足，回退至 Full 并进入重新审计队列。

E3 的任务流顺序、探索预算、更新阈值、family 定义和 fallback 规则必须在测试前固定。测试流中早期任务允许按协议更新 profile，后续任务才评估部署；不得根据整个 test 流的结果回写规则。

## 论文大纲

1. Introduction：端到端分数与普通 ablation 的机制缺口，以及重复任务中的重复协调成本。
2. Problem Formulation：有状态 workflow graph、artifact、checkpoint、组件效应和边受控效应。
3. Auditable Workflow System：固定节点、typed contract、ledger、checkpoint、replay 与安全执行。
4. Workflow Profiles：任务结构签名、选择器、失效检测和跨会话的最小化复用边界。
5. Experimental Protocol：P0–P3、数据隔离、指标、统计和失败分类。
6. Results：RQ1 质量—成本边界；RQ2 机制归因；RQ3 重复任务累计收益。
7. Case Studies & Limitations：正效应、无效/负效应、replay control、distribution shift 与外部效度。
8. Conclusion：以可审计证据选择足够的协作结构，而非默认堆叠更多 Agent。
