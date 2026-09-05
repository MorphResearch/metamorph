# AppWorld 实验配置

本文件的旧版以 `S0 / Complex-only / Adaptive / Expert` 为主比较，并包含 JSON contract 和预算 gate 的消融；该设计已退役，不能与当前实验合并统计。

当前论文主线、P0–P3 顺序、统计与 E3 profile 协议见 [CAUSAL_WORKFLOW_RESEARCH_PLAN.md](CAUSAL_WORKFLOW_RESEARCH_PLAN.md)。可执行 runner 语义见 [AppWorld runner contract](../../experiments/appworld/runner_contract.md)。

当前固定实验矩阵：

```text
E / P+E / E+V+R / Full
Full / No-Planner / No-Verifier / No-Repair /
Mask-P-to-E / Mask-E-to-V / Replay-Control-E-to-V
```

所有配置都显式声明 `model.request_timeout_seconds = 120`，以确保供应商请求阻塞会保存为可审计的失败 arm，而不会使 task latency gate 失效。
