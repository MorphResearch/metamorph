# 本地实验产物盘点（自动生成）

运行 `python3 scripts/audit_experiment_history.py` 更新。仅清点本机现存证据，不调用模型。
所有数量均按结果文件计数，包含调试、失败、重复尝试；不可解释为独立样本或合并成功率。
unknown 表示源字段缺失；没有补零或追认旧协议有效性。关键词次数仅作定位，不等于错误事件数。

纳入 949 个文件，216 个 result.json，0 项格式异常。

| 输出根 / 组 | 结果文件 | completed | 协议有效 true / false / unknown | 官方成功文件数 |
|---|---:|---:|---|---:|
| context_projection_validation_v1_20260907 | 4 | 4 | 0 / 4 / 0 | 0 |
| context_projection_validation_v2_20260907 | 4 | 0 | 0 / 4 / 0 | 0 |
| context_projection_validation_v2_20260907_network_retry1 | 4 | 4 | 0 / 4 / 0 | 0 |
| context_projection_validation_v3_20260907 | 4 | 4 | 1 / 3 / 0 | 0 |
| dag_p1_formal_orchestrated_20260906 | 3 | 2 | 1 / 2 / 0 | 1 |
| dag_p1_formal_orchestrated_v2_20260906 | 7 | 7 | 4 / 3 / 0 | 4 |
| dag_p1_formal_orchestrated_v3_20260907 | 1 | 1 | 0 / 1 / 0 | 0 |
| dag_p1_smoke_20260906 | 2 | 2 | 0 / 0 / 2 | 2 |
| dag_p1_smoke_20260906_v2 | 1 | 1 | 0 / 0 / 1 | 1 |
| dag_p1_smoke_20260906_v3 | 1 | 1 | 0 / 0 / 1 | 0 |
| dag_p1_smoke_bg_20260906 | 1 | 1 | 0 / 0 / 1 | 1 |
| dag_p1_smoke_v5_20260906 | 1 | 1 | 0 / 0 / 1 | 1 |
| dag_p1_smoke_v6_20260906 | 1 | 0 | 0 / 1 / 0 | 0 |
| dag_p1_smoke_v6_retry1_20260906 | 1 | 0 | 0 / 1 / 0 | 0 |
| dag_p1_smoke_v7_network_20260906 | 1 | 1 | 0 / 1 / 0 | 0 |
| dag_p1_smoke_v7b_network_20260906 | 2 | 2 | 1 / 1 / 0 | 1 |
| e1_minimal_v4pro | 1 | 0 | 0 / 0 / 1 | 0 |
| e1_minimal_v4pro_run | 1 | 0 | 0 / 0 / 1 | 0 |
| e1_minimal_v4pro_run2 | 1 | 1 | 0 / 0 / 1 | 0 |
| e1_pilot_v2_v4pro | 1 | 1 | 0 / 0 / 1 | 1 |
| e1_pilot_v2_v4pro_gate2 | 12 | 5 | 0 / 0 / 12 | 4 |
| e2_pilot_v2_v4pro_2train | 5 | 5 | 0 / 0 / 5 | 2 |
| local_runtime | 2 | 2 | 0 / 0 / 2 | 0 |
| p0_audit_v5 | 1 | 0 | 0 / 0 / 1 | 0 |
| p0_audit_v6 | 4 | 1 | 0 / 0 / 4 | 1 |
| p0_audit_v7 | 4 | 1 | 0 / 0 / 4 | 1 |
| p0_audit_v8 | 2 | 2 | 0 / 0 / 2 | 2 |
| p0_baselines_v1 | 12 | 0 | 0 / 0 / 12 | 0 |
| p0_baselines_v2 | 2 | 2 | 0 / 0 / 2 | 1 |
| p0_baselines_v3 | 1 | 1 | 0 / 0 / 1 | 1 |
| p0_baselines_v4 | 1 | 1 | 0 / 0 / 1 | 1 |
| p0_baselines_v5 | 1 | 1 | 0 / 0 / 1 | 0 |
| workbench_matrix/Adaptive | 1 | 0 | 0 / 0 / 1 | 0 |
| workbench_matrix/Oracle | 1 | 0 | 0 / 0 / 1 | 0 |
| workbench_matrix/S0 | 26 | 12 | 0 / 0 / 26 | 11 |
| workbench_matrix/S1 | 23 | 4 | 0 / 0 / 23 | 4 |
| workbench_matrix/S2 | 23 | 6 | 0 / 0 / 23 | 6 |
| workbench_matrix/S3 | 23 | 5 | 0 / 0 / 23 | 5 |
| workbench_matrix/S4 | 23 | 5 | 0 / 0 / 23 | 5 |
| workbench_smoke | 7 | 2 | 0 / 0 / 7 | 1 |

## AppWorld 没有单臂 result.json 的目录

这些目录可能仅含 manifest、中断痕迹或独立 provider 微测试，不能计作完成的 benchmark arm。

- `glm53_provider_compatibility_20260907_retry2`（现存文件 0 个）
- `glm53_provider_compatibility_20260907_retry3`（现存文件 2 个）
- `p0_audit_v1`（现存文件 3 个）
- `p0_audit_v2`（现存文件 4 个）
- `p0_audit_v3`（现存文件 4 个）
- `p0_audit_v4`（现存文件 4 个）

## 文件格式异常

无。

## 覆盖范围

- `docs/doc`
- `experiments/appworld`
- `.metamorph/runs`
- `benchmarks/workbench/metamorph_runs`
- `benchmarks/workbench/metamorph_matrix_runs`
- `benchmarks/browsecomp-plus/runs`
- `benchmarks/tau2-bench/data/simulations`
- docs 顶层及 docs/zh-CN 顶层 Markdown；server*.log。
- 二进制 checkpoint 等仅记录字节数与 SHA-256；JSON/JSONL 全文解析，文本日志全文扫描。
- 不扫描第三方源代码/自带测试日志、虚拟环境、下载数据集、缓存或 Git 内部日志。
- 不导出原始对话、工具返回或凭据；本清单不是完整实验数据备份。
