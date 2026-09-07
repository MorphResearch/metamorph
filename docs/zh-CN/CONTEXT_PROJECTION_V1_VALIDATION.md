# `context_projection_v1` 验证记录：FAILED

验证输出根：`experiments/appworld/runs/context_projection_validation_v1_20260907`。
该输出根为不可变审计证据；不会覆盖、删除或重跑。

| task | condition | status | protocol_valid | total tokens | 原因 |
| --- | --- | --- | --- | ---: | --- |
| `fddb6b6_3` | G0 | completed | false | 51,813 | `dag_act` artifact 为 null / 未完成 |
| `fddb6b6_3` | G2 | completed | false | 136,364 | inspect、act、check artifact 为 null / 未完成；预算耗尽 |
| `92fe421_3` | G0 | completed | false | 38,457 | tool selector 未完成 |
| `92fe421_3` | G2 | completed | false | 77,194 | tool selector、两个 inspect artifact 未完成 |

## 判定与根因

`context_projection_v1` 不是可用于主实验的协议：它把跨节点历史压缩和当前节点内部的 assistant-tool continuation 一并移除了。因而后续 provider 请求缺失必要的 `assistant(tool_call id=X) -> tool(tool_call_id=X)` 配对，导致重复认证/工具调用、无效 artifact 或预算耗尽。

该结论只否定 v1 的上下文构造，不否定确定性跨节点压缩、预算 reservation、DAG、repair gate、模型、定价或 λ。后续仅以独立 `context_projection_v2` 输出根做工程验证；本 v1 数据永不进入 P1、P2、P3、profile 或效果统计。
