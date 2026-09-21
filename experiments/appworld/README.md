# AppWorld：可审计 DAG workflow 实验

> 状态更新（2026-09-15）：以下顺序是历史协议流程，当前停在 Gate-1/协议可靠性验证，不能据此直接启动 P1。P1 dev 清单已冻结，但真实 G3 repair 证据仍缺失，bounded-node v3 与后续 GLM 微测试均未通过进入门槛。完整时间线和证据见 [实验总览](../../docs/zh-CN/EXPERIMENT_HISTORY.md) 与 [v3 停止记录](../../docs/zh-CN/BOUNDED_NODE_EXECUTION_V3_VALIDATION.md)。

研究对象是 task-internal DAG，而不是固定控制平面的角色存在与否。控制平面固定为 `planner / DAG compiler → DAG executor → final evaluator`；实验比较的四个预注册图是 G0–G3。

完整协议见 [研究计划](../../docs/zh-CN/CAUSAL_WORKFLOW_RESEARCH_PLAN.md)，一周交付门槛见 [投稿前清单](../../docs/zh-CN/ONE_WEEK_PUBLICATION_CHECKLIST.md)。

```text
G0: act
G1: inspect → act → check
G2: inspect_a ∥ inspect_b → join → act → check
G3: inspect → act → check → [NOT_VERIFIED: repair → final_check]
```

## 当前唯一可执行顺序

1. P0：运行无模型测试；四图可编译、每个节点后 checkpoint、node/edge/topology intervention 不污染基线、passthrough 负控制通过。
2. P1 smoke：用 `configs/dag_p1_smoke.json` 在冻结 dev 清单的少量任务上跑 G0–G3，确认真实 trace 和成本。
3. P1/P2/P3：只有 smoke 可行后才冻结 12-task dev、6-task mechanism、18-task held-out test 清单。

```bash
benchmarks/appworld/.venv/bin/python -m unittest discover -s tests -v

# 只检查配置/manifest；不发送模型请求。
benchmarks/appworld/.venv/bin/python scripts/run_appworld_experiment.py \
  --config experiments/appworld/configs/dag_p1_smoke.json \
  --task-manifest <frozen-dev-manifest.json> \
  --output-root /tmp/metamorph-dag-p1-preflight --preflight-only
```

旧 `e1_*`、`e2_*` 与 `p0_audit.json` 记录的是固定 S3 角色消融；仅保留作工程历史，不能与 DAG 主实验合并或继续运行。

每个真实运行必须保存 task/config/commit hash、节点 trace/artifact hash、checkpoint hash、真实 wall-clock、token/API/工具预算与失败原因。严禁覆盖已有 output root；中断使用 `--resume`。
