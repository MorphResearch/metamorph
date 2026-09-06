# 下一对话执行清单

## 当前状态（2026-09-06）

- 分支：`master`，工作树在交接时应保持干净。
- 已推送 DAG runtime 与 P0：`1b51ac3`；清理结果修复：`767fdf4`；认证/预算 smoke 修复：`6b82e44`。
- P0 已通过：`experiments/appworld/P0_DAG_ACCEPTANCE.md`。
- 新主协议：`docs/zh-CN/PUBLISHABLE_MINIMUM_EXPERIMENT_PLAN.md`。
- 当前正在后台运行（不要启动重复 arm）：DeepSeek v4-pro，`G0 × 6bdbc26_1 × seed 300`，输出根：
  `experiments/appworld/runs/dag_p1_smoke_v5_20260906/`。
- 该 v5 运行是 Gate-1 smoke；此前 v4 G0 成功但撞到旧错误预算，只是工程诊断，不能计入任何统计。

## 第一步：检查当前 G0，不要猜测

```bash
pgrep -fl 'run_appworld_experiment.py|appworld_dag_p1_smoke_v5'

benchmarks/appworld/.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('experiments/appworld/runs/dag_p1_smoke_v5_20260906/runs/G0/6bdbc26_1/300/result.json')
print(json.loads(p.read_text()) if p.exists() else 'still running / no result yet')
PY
```

验收：`result.json` 存在；`dag_execution.nodes.act.status == completed`；有 `initial/node-act/final` checkpoints；`latency_seconds > 0`；无来源污染。

## Gate-1：只在当前 G0 通过后运行 G1–G3

同一输出根、同一 task/seed，每次只运行一个 condition：

```bash
benchmarks/appworld/.venv/bin/python -W ignore scripts/run_appworld_experiment.py \
  --config experiments/appworld/configs/dag_p1_smoke.json \
  --task-manifest experiments/appworld/manifests/p1_dag_smoke.json \
  --output-root experiments/appworld/runs/dag_p1_smoke_v5_20260906 \
  --task-id 6bdbc26_1 --condition G1
```

依次换为 G2、G3。长运行必须使用持续 PTY/后台终端，不能依赖 60 秒前台窗口。完成后检查 4 个 `result.json`；若任一 arm 无完整 trace/checkpoint，停止，不扩展任务。

## P1 前需创建和冻结的内容

- [ ] 新建 `p1_dag_dev` manifest：12 个**此前未运行** dev/train 任务，简单/中等/复杂各 4；只从公开 task instruction 标注；写 selection hash。
- [ ] 新建 P1 config：从 smoke 成功的预算/prompt/tool policy 固化；G0–G3，1 seed。
- [ ] commit 配置与 manifest；写入 git commit/hash，不改动后再运行。
- [ ] 运行 `12 × 4`，保留所有失败；生成任务层结果表。
- [ ] 从 P1 定义一次且仅一次 `family → DAG` profile，写入 JSON 和文档。

## P2 前的关键工程缺口（必须解决）

当前 `adapters/appworld_dag.py` 已有纯 DAG intervention 语义，`AppWorldController.run_dag()` 已有节点 checkpoint；但正式 E2 还需要将**真实 AppWorld checkpoint restore**接入 DAG edge/node/topology replay runner。

- [ ] 从 baseline 的 source-node checkpoint 复制到新 world；记录 source hash。
- [ ] 只重跑合法下游节点；edge mask 传类型正确的 null artifact，保留 source state effect。
- [ ] 实现 passthrough replay；结果与基线差异只作为 runtime/control 诊断。
- [ ] replay 前后重新 hash baseline source，写 `replay_contamination`。
- [ ] 用 fake world + 一个真实 AppWorld smoke 测试这个路径后，才建 P2 config。

## P2、P3 和写作 checklist

- [ ] P2：6 dev 代表任务，四个预注册局部对比；每个有效 replay 2 次。
- [ ] P3：创建 18 个未见 test 任务（每层 6）的 frozen manifest；运行 G0–G3 × 1 seed。
- [ ] E3：在 P3 上执行冻结 profile，对比 always-G0/always-G3。
- [ ] 汇总脚本输出：分层 E1 表、E2 paired effect 图、E3 cost-success 图、失败/污染排除表。
- [ ] 写 Methods 时明确：控制平面不消融；E2 是局部 checkpointed effect；单 seed 局限。
- [ ] MultiAgentBench 只在主结果全部完成且剩余半天时做 capability gate。

## 每次运行后的检查

- [ ] `result.json`、node trace、artifact hash、checkpoint hash 均存在。
- [ ] token usage 不缺失；真实 latency 非零。
- [ ] strict success、工具/API 调用、错误数、预算耗尽原因都被记录。
- [ ] 运行目录不覆盖；失败也保留。
- [ ] 每个配置/manifest 变动后先 git commit，再开始下一阶段。
