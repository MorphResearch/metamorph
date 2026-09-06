# P0 DAG 工程验收记录

**状态：通过（无模型、确定性 fake-world）**  
**日期：2026-09-06**  
**主协议：`appworld.dag-execution.v1`**

本记录只证明实验基础设施的语义与隔离性；不包含任何 DeepSeek 调用、AppWorld 成功率或论文效应结论。

| 验收项 | 证据 | 状态 |
| --- | --- | --- |
| G0–G3 可编译 | `test_all_registered_graphs_compile_and_checkpoint_each_executed_node` | 通过 |
| 拒绝环、类型/调度违规 | `test_compiler_rejects_cycle_and_invalid_parallel_write` | 通过 |
| 每个 completed node 有 artifact hash + checkpoint | 同上 | 通过 |
| node skip、edge typed-null 不改写基线 checkpoint | `test_node_and_edge_interventions_do_not_mutate_baseline_checkpoint` | 通过 |
| G2 read-only parallel → serial 拓扑干预 | `test_topology_intervention_serializes_only_read_only_fork` | 通过 |
| passthrough 负控制与基线 artifact hash 相同 | `test_passthrough_control_is_recorded_without_masking` | 通过 |
| G3 仅在 NOT_VERIFIED 时执行 repair/final_check | `test_g3_runs_repair_path_only_after_not_verified_check` | 通过 |
| AppWorld controller 走 `run_dag` 并记录节点 checkpoint | `test_dag_runtime_is_the_new_task_workflow_path` | 通过 |
| G2 read-only fork 真实并发、serial control 不并发 | `test_parallel_read_only_batch_overlaps_and_serial_control_does_not` | 通过 |
| `None` artifact 不会伪装为 completed node | `test_null_artifact_is_audited_without_being_marked_completed` | 通过 |
| 环境只加载 minimal ground truth；受限代码不可访问它 | `test_default_world_factory_uses_minimal_ground_truth`、`test_constrained_model_code_cannot_access_ground_truth_object` | 通过 |

复跑命令：

```bash
benchmarks/appworld/.venv/bin/python -m unittest discover -s tests -v
```

## P1 解锁条件

P1 只能运行新的 `DAG_E1`/G0–G3 配置。每个真实 arm 的首次 smoke 必须检查：`protocol_valid=true`、所有 executed phase 的 trace status 为 `completed`、模型调用有 token usage、所有 completed node 具备 checkpoint/hash、真实 wall-clock 非零、没有 `replay_contamination`，且在产生任何有效 action 前不会耗尽预算。环境的 `strict_success` 与协议有效性分开记录；前者不能覆盖后者。任一条件失败时停止矩阵并修复 runtime。

旧 `fixed_s3` P0 及其运行结果不属于本验收，也不能作为本论文的实验数据。
