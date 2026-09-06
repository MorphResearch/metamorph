# 下一对话执行清单

## 当前状态（2026-09-06）

- 分支：`master`，工作树在交接时应保持干净。
- 已推送 DAG runtime 与 P0：`1b51ac3`；清理结果修复：`767fdf4`；认证/预算 smoke 修复：`6b82e44`。
- P0 已通过：`experiments/appworld/P0_DAG_ACCEPTANCE.md`。
- 新主协议：`docs/zh-CN/PUBLISHABLE_MINIMUM_EXPERIMENT_PLAN.md`。
- v5 G0 已结束，且不能通过新的 Gate-1：虽然 AppWorld `strict_success=true`，但 `dag_act` 的 trace 是 `invalid_contract`、artifact 为 null。该目录只保留作诊断，不能启动其余 arm，也不能进入统计。
- 当前代码已加入 protocol-valid gate、minimal ground truth、真实 G2 read-only 并行、DAG checkpoint replay 入口、冻结单 seed 的 formal 例外和缺失成本保护。下一次 smoke 必须使用**新的**输出根，并在修改后的代码提交后再运行。
- `c1629b4` 后的 formal G0 已在两个独立输出根尝试：`dag_p1_smoke_v6_20260906` 与 `dag_p1_smoke_v6_retry1_20260906`。两者均在 `tool_selector` 的首次 provider 请求以 `APIConnectionError` 失败（0 token、0 tool action）；保留为基础设施失败，不得视为零成本成功或重试后选择性报告。恢复 provider 连通性后，以新的输出根重新从 G0 开始；不要运行 G1–G3。

## 第一步：确认旧 G0 诊断，不要把它当通过

```bash
pgrep -fl 'run_appworld_experiment.py|appworld_dag_p1_smoke_v5'

benchmarks/appworld/.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('experiments/appworld/runs/dag_p1_smoke_v5_20260906/runs/G0/6bdbc26_1/300/result.json')
print(json.loads(p.read_text()) if p.exists() else 'still running / no result yet')
PY
```

该 run 的结论应为：环境成功但协议无效。原因是 `dag_act.json` 的 `invalid_contract` 和 null artifact；不要用“节点 completed”覆盖 trace 事实。

## Gate-1：提交修复后从新的 smoke 输出根开始

先运行新的 G0。只有它满足 `protocol_valid=true`、`tool_selector`/`dag_act` trace 都为 `completed`、`act` artifact 非空、`initial/node-act/final` checkpoint 存在、token/真实 latency 完整时，才在同一新输出根依次运行 G1–G3：

```bash
benchmarks/appworld/.venv/bin/python -W ignore scripts/run_appworld_experiment.py \
  --config experiments/appworld/configs/dag_p1_smoke.json \
  --task-manifest experiments/appworld/manifests/p1_dag_smoke.json \
  --output-root experiments/appworld/runs/<new_committed_smoke_root> \
  --task-id 6bdbc26_1 --condition G1
```

依次换为 G2、G3。长运行必须使用持续 PTY/后台终端，不能依赖 60 秒前台窗口。完成后检查 4 个 `result.json`；若任一 arm `protocol_valid=false`、无完整 trace/checkpoint，停止，不扩展任务。

## P1 前需创建和冻结的内容

- [ ] 新建 `p1_dag_dev` manifest：12 个**此前未运行** dev/train 任务，简单/中等/复杂各 4；只从公开 task instruction 标注；写 selection hash。
- [ ] 新建 P1 config：从 smoke 成功的预算/prompt/tool policy 固化；G0–G3，1 seed。
- [ ] P1 config 以 `--formal` 运行，并明确写入 `statistical_limitations.single_seed=true`；同时冻结 input/output USD token 价格与三个 λ。
- [ ] commit 配置与 manifest；写入 git commit/hash，不改动后再运行。
- [ ] 运行 `12 × 4`，保留所有失败；生成任务层结果表。
- [ ] 从 P1 定义一次且仅一次 `family → DAG` profile，写入 JSON 和文档。

## P2 前的关键工程缺口（必须解决）

当前 `AppWorldController.run_dag()` 已有真实 checkpoint restore 的 DAG replay runner；P2 配置只可引用 protocol-valid baseline，并会复用 baseline tool surface、核验 source hash、记录 contamination。P2 前仍须先以 fake-world 与一个真实 AppWorld smoke 验收每个预注册干预。

- [ ] 为四项预注册比较写 `DAG_E2` config：source checkpoint、上游 artifact、skip/mask/passthrough/serial intervention 都必须显式列出。
- [ ] 用 fake world + 一个真实 AppWorld smoke 测试每条路径后，才冻结 P2 config。

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
- [ ] `protocol_valid` 与 `protocol_invalid_reasons` 都被记录；协议无效 run 不进入主效应估计，但必须在失败表中报告。
- [ ] 成本未知须标为 unknown，绝不能按零成本处理。
- [ ] 运行目录不覆盖；失败也保留。
- [ ] 每个配置/manifest 变动后先 git commit，再开始下一阶段。
