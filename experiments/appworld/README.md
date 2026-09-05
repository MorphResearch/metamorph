# AppWorld：可审计 Workflow Profile 实验

本目录实现论文的 P0–P3 实验协议。主问题不是“复杂 multi-agent 是否总是更强”，而是：在固定初始世界与预算下，哪些 workflow 组件和信息边带来净收益，以及这些证据能否在重复任务中复用。

完整研究计划见 [CAUSAL_WORKFLOW_RESEARCH_PLAN.md](../../docs/zh-CN/CAUSAL_WORKFLOW_RESEARCH_PLAN.md)。

## 固定 workflow

```text
E       = Executor
P+E     = Planner → Executor
E+V+R   = Executor → Verifier → [NOT_VERIFIED 时才 Repair]
Full    = Planner → Executor → Verifier → [NOT_VERIFIED 时才 Repair]
```

Planner/Verifier 只读；Executor/Repair 可写。所有真实 API 调用、包括受限 code batch 内的调用，均写入 trace 并计入同一预算。官方主指标为 AppWorld individual evaluator 的 strict success。

## 配置与清单

| 阶段 | 配置 | 清单 |
|---|---|---|
| P0 工程验收 | `configs/p0_audit.json` | `manifests/p0_audit.json` |
| P1 小规模 E1 | `configs/e1_pilot.json` | `manifests/p1_screen.json` |
| P2 机制验证 | `configs/e2_pilot.json` | `manifests/p2_mechanism.json` |
| P3 E1 主实验 | `configs/e1_system.json` | `manifests/p3_e1.json` |
| P3 E2 主实验 | `configs/e2_causal.json` | `manifests/p3_e2.json` |

P0 的 `Replay-Control-E-to-V` 以原 executor artifact 重放 verifier；它是 replay 负控制，不是性能条件。`Mask-P-to-E` 和 `Mask-E-to-V` 使用 schema-compatible typed-null artifact。

## 当前执行顺序

先执行所有无需 API 的检查：

```bash
benchmarks/appworld/.venv/bin/python -m unittest discover -s tests -v

benchmarks/appworld/.venv/bin/python scripts/run_appworld_experiment.py \
  --config experiments/appworld/configs/p0_audit.json \
  --task-manifest experiments/appworld/manifests/p0_audit.json \
  --output-root /tmp/metamorph-p0-preflight --preflight-only
```

通过后才开始 P0 的真实模型运行。请求级超时固定为 120 秒；超时会持久化为失败 arm，而不是无限挂起。P0 完成后检查 checkpoint hash、`replay_contamination=false`、trace 完整性和失败分类，再依次解锁 P1、P2 与 P3。历史的 S0/Adaptive/Expert 与 No-JSON-Contract/No-Budget-Gate 结果仅作探索记录，不能与本协议下的新矩阵合并统计。

正式 P3 仍要求干净的 Metamorph/AppWorld worktree、冻结 manifest、多个 seed 与完整失败保留。不要覆盖既有 output root；中断恢复使用 `--resume`。
