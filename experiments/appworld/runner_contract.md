# AppWorld Runner Contract

这是 E1/E2 runner 的接口约定。当前文件只定义输入、输出和安全边界，不执行任务。

## Runner 输入

Runner 必须接受：

- 一个 E1 或 E2 JSON 配置；
- 一个已经冻结的 `task_manifest.json`；
- AppWorld root；
- model/provider 环境变量；
- 一个新的 experiment output root。

Runner 启动时必须把以下信息写入 `manifest.json`：

- 当前 Metamorph git commit；
- AppWorld commit；
- 配置文件 hash；
- task manifest hash；
- model/provider、prompt/schema hash；
- seed、budget、allow_write 和 tool policy；
- evaluator 版本；
- start time 和 runner version。

## E1 执行语义

对每个 `task_id × condition × seed`：

1. 创建全新的 AppWorld 初始环境；
2. 只把用户任务和允许的官方工具暴露给 agent；
3. 执行 S0、Complex-only、Adaptive 或 Oracle；
4. 记录 router、planner、executor、verifier 的 trace；
5. 使用官方 evaluator 计算 reward；
6. 保存所有成本、权限和安全字段。

E1 的四个条件必须使用相同的 task ID、seed、model、预算和 evaluator。lesson 必须
关闭。

## E2 执行语义

对每个 `task_id × intervention × seed`：

1. 在同一初始环境下执行 Full-S3，并保存上游 artifacts、artifact hashes 和状态快照；
2. 对一个组件或一条通信边执行单一干预；
3. 重新创建相同初始环境，禁止从 Full-S3 的官方写状态继续；
4. 恢复不受影响的上游 artifact；
5. 使用 typed-null artifact 屏蔽目标通信边；
6. 只重放受影响的 downstream subgraph；
7. 使用同一个官方 evaluator 评分；
8. 明确记录 replay 是否污染官方状态。

如果 runner 只能做到“删除组件后完整重跑”，必须把该结果标为普通 ablation，不能
标为 fixed-context causal edge intervention。

## 最小 result.json

每个任务必须至少包含：

```json
{
  "benchmark": "AppWorld",
  "experiment_id": "appworld_e1_system_v1",
  "condition": "S0",
  "task_id": "...",
  "split": "test_normal",
  "seed": 300,
  "official_reward": 0.0,
  "task_success": false,
  "termination_reason": "...",
  "token_usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "latency_seconds": 0.0,
  "tool_calls": 0,
  "write_actions": 0,
  "safety_incidents": 0,
  "tool_errors": 0,
  "budget_exhausted": false,
  "json_contract_violations": 0,
  "routing": null,
  "artifacts": [],
  "replay": null,
  "failure_category": null
}
```

`task_success` 必须来自官方 evaluator 或明确的官方 reward 映射，不能由“有非空输出”
推断。

## Runner 禁止事项

- 不能把 test ground-truth solution、evaluation program 或 hidden difficulty 暴露给 agent；
- 不能用 test 结果更新 router、Oracle 标签、prompt、lesson 或 task manifest；
- 不能在 replay 后继续使用被 replay 污染的官方环境；
- 不能超出配置中的 tool whitelist、`allow_write` 或预算；
- 不能删除失败任务或只保存成功 trace。
