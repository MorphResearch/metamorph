# AppWorld Workshop 实验准备

当前目录只保存实验配置和任务选择规则，**不会自动启动模型或 benchmark**。正式运行
前需要由 AppWorld runner 读取这些配置，并在运行前物化不可变的 `task_manifest.json`。

当前 workshop 只运行：

- `E1`：S0、Complex-only、Adaptive、Oracle 系统级比较；
- `E2`：Full-S3、组件消融和通信边 masking。

E3 lesson transfer 暂不运行。

## 配置文件

| 文件 | 用途 |
|---|---|
| `configs/e1_system.json` | E1 四条件系统级实验 |
| `configs/e2_causal.json` | E2 组件和通信边因果实验 |
| `task_selection.json` | pilot、主实验和扩展任务集规则 |

## 运行前必须完成

1. 接入 AppWorld runner，并确认它只使用 `benchmarks/appworld` 的官方 evaluator；
2. 从配置生成并冻结 `task_manifest.json`，保存具体 task IDs 和选择 hash；
3. 为 AppWorld test 任务准备独立的 Oracle 标签文件；
4. 用 train/dev 完成 smoke/pilot，冻结 model、prompt、budget、seed 和代码 commit；
5. 检查单个任务的官方 reward、token、latency、tool-call 和 safety 字段是否都落盘。

## 晚上启动顺序

晚上 18:00 以后先执行准备和 smoke，不直接启动全量：

```text
prepare E1 manifest → runner smoke → prepare E2 manifest → runner smoke
→ 检查日志和预算 → 再启动正式 E1 → 最后启动 E2
```

如果 smoke 发现 evaluator、权限、状态重置或 replay 不符合配置，应暂停正式运行，
不能用不一致的结果进入论文统计。
