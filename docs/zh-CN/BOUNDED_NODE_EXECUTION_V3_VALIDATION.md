# `bounded_node_execution_v3` 验证记录：STOP / 不进入 P1

代码与冻结配置提交：`a7ba87d25fa81ab90c61d18d9c198afa2ce786d2`。
输出根：`experiments/appworld/runs/context_projection_validation_v3_20260907`。这是独立的四臂 validation，不覆盖或混入 v1/v2/P1/P3。

v3 唯一新增的协议控制为：每节点最多 8 个 tool rounds、最多 24 个模型请求的工具调用；到达上限后，controller 使用已有 evidence 强制转入原有的 tools-disabled、JSON-schema artifact finalization。未改 context projection、DAG、repair、schema、模型、价格或 λ。

| task | condition | protocol_valid | strict_success | total tokens | tool calls | 主要终态 |
| --- | --- | --- | --- | ---: | ---: | --- |
| `fddb6b6_3` | G0 | true | false | 93,832 | 23 | `dag_act` 在第 8 个 round 被强制 finalization，artifact 完整 |
| `fddb6b6_3` | G2 | false | false | 109,443 | 9 | `dag_check` 达到累计 max-errors；上游存在 finalization contract errors |
| `92fe421_3` | G0 | false | false | 93,498 | 8 | tool selector 与 `dag_act` strict finalization invalid contract |
| `92fe421_3` | G2 | false | false | 91,242 | 15 | tool selector 与两个 inspect strict finalization invalid contract |

## 结论

v3 验证了诊断：node-local tool-loop termination 是真实成本控制点。与 v2（约 94k–148k tokens、4/4 protocol-invalid）相比，v3 避免了大部分 token budget exhaustion，且使一条原先失败的 G0 arm 变为 `protocol_valid=true`。

但 v3 没有通过冻结 Gate：仅 1/4 protocol-valid，且另外 3 条 arm 的共同主因是 tools-disabled strict artifact finalization 的 JSON/schema 不合规（多处 `Expecting value` 或 `Unterminated string`）。这正满足 v3 前预设的止损线：不再继续给 controller 增加 v4/v5 修补。

## 后续边界

不启动 P1，不把 v1/v2/v3 validation 用于主统计或 profile。若要继续 AppWorld，下一次必须是单独重新冻结的 model/provider 选择（全部 P1/P2/P3 在新模型下从零开始）；否则应缩减研究范围或换 benchmark。当前 DeepSeek endpoint 与严格 tool/artifact finalization 协议的兼容性不足，不能作为这篇论文的正式实验基础。
