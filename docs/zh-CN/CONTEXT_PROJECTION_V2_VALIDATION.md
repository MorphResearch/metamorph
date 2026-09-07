# `context_projection_v2` 验证记录：FAILED

v2 的代码冻结提交为 `6c5b911642ad421d28700d35771905010c0c0143`。验证任务、条件、模型、定价、λ、budget reservation 均与 v1 冻结设置相同，只更换了节点内 transcript continuation 处理。

首次输出根 `experiments/appworld/runs/context_projection_validation_v2_20260907` 的 4 个 arm 均在首个 provider 请求因受限执行环境的 `APIConnectionError` 失败。这些是 infrastructure-invalid 证据，保留但不计入 v2 协议判定。

唯一有效网络重试输出根：`experiments/appworld/runs/context_projection_validation_v2_20260907_network_retry1`。不覆盖 v1 或首次 v2 输出。

| task | condition | protocol_valid | total tokens | tool calls | 主要无效原因 |
| --- | --- | --- | ---: | ---: | --- |
| `fddb6b6_3` | G0 | false | 140,789 | 62 | `dag_act` 预算耗尽，artifact 为 null |
| `fddb6b6_3` | G2 | false | 142,371 | 30 | `dag_act`、`dag_check` 预算耗尽，artifact 为 null |
| `92fe421_3` | G0 | false | 147,909 | 20 | `dag_act` 预算耗尽，tool selector 与 act 未完成 |
| `92fe421_3` | G2 | false | 94,323 | 26 | check 预算耗尽；selector / inspect artifact 未完成 |

## 机制审计

v2 修复了 v1 所定义的结构性 transcript bug：所有有工具的 phase trace 中，`tool` 消息的 `tool_call_id` 都能在同一节点完整 transcript 的 preceding assistant `tool_calls` 中找到；原始工具输出、模型可见截断版本及 truncation metadata 都已保存。G2 trace 也保留了 `inspect_a`、`inspect_b` 同一 schedule batch，随后 join、act、check 的 DAG 顺序。

但这不足以通过 cost-controlled core protocol Gate。4/4 arm 仍为 `protocol_valid=false`，没有 strict success，且总 token 没有相对 v1 降低。剩余失败表现为模型在节点内继续高频工具循环、预算耗尽，以及若干 tool-free artifact finalization 的 invalid contract；它们不是 v1 的 orphaned tool-call continuation，也不是 infrastructure failure。

## 决定

`context_projection_v2` 不进入 P1，也不触发 core protocol freeze。按预注册边界，不再对 context projection、DAG、repair、模型、价格或 λ 做第三轮工程修改，也不启动 P1。所有 v1/v2 validation outputs 永远排除在 P1、P2、P3、profile 和主结果统计之外。下一步需要明确重新决定：接受当前 core 的失败状态并改写研究计划，或授权一个新的、单独版本化的协议变更；不能把这两轮 validation 当作正式实验数据。
