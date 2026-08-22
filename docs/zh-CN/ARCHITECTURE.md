# Metamorph v0.1 系统架构

## 目标

Metamorph 的第一阶段不计划重新训练语言模型，而是围绕一个冻结的基础模型建立可控的进化闭环。可以修改的部分是 Agent harness，包括 prompt、规划策略、memory 检索、skills、tools 和编排逻辑。

## 系统组件

```text
                    ┌─────────────────────┐
                    │   Web 前端 / CLI     │
                    └──────────┬──────────┘
                               │ HTTPS / localhost API
                    ┌──────────▼──────────┐
                    │   Task API           │
                    │   认证 + 运行状态    │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────▼──────────────────────┐
        │              Agent 执行 Runtime                │
        │ 模型适配器 · Planner · Context Builder        │
        └───────────────┬───────────────┬──────────────┘
                        │               │
                 ┌──────▼─────┐  ┌────▼────────┐
                 │ Memory     │  │ Tool 层     │
                 │ 读取/门控   │  │ 权限白名单   │
                 └──────┬─────┘  └────┬────────┘
                        │               │
                        └──────┬────────┘
                               ▼
                    ┌─────────────────────┐
                    │ 执行沙箱            │
                    │ 受限 Workspace      │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Evidence Store      │
                    │ 运行/产物/日志       │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Evaluator           │
                    │ 测试 + 策略检查      │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Evolution Controller│
                    │ 诊断 → 提议          │
                    │ 基准测试 → 晋级      │
                    └─────────────────────┘
```

## 控制面与可变面

以下控制面内容在 v0.1 中不能由 Agent 自动修改：

- 文件系统和网络权限；
- 密钥脱敏和路径限制；
- Evaluator 协议和 benchmark 的 holdout 规则；
- 晋级、回滚和人工审批规则；
- token、时间、磁盘和进程的最大预算。

初始阶段允许自动生成候选修改的 harness 内容包括：

- `system_prompt.md` 和任务策略；
- Planner 和工具选择策略；
- skills 及其元数据；
- memory 检索和写入策略；
- 低风险、运行于沙箱中的辅助工具。

## 一次运行的生命周期

```text
created → running → succeeded/failed → evaluated → archived
创建       运行       成功/失败          评估          归档
```

一次进化的生命周期是独立的：

```text
proposed → sandbox-tested → benchmarked → staged
提议         沙箱测试          基准测试       预发布
         → human-approved → promoted
              人工批准        正式启用
         └────────────────→ rejected/rollback
                              拒绝/回滚
```

任务执行期间绝不能直接覆盖当前生产版本。每个 candidate 都应该拥有自己的 workspace、配置快照、依赖清单和 benchmark 报告。

## Evidence 与版本记录

每次运行应该记录结构化事件，而不是保存隐藏的完整思维链：

- 任务输入和允许访问的路径；
- 模型和配置标识；
- 工具名称、经过验证的参数、结果、退出状态和耗时；
- 模型给出的简短决策摘要；
- 生成的产物及其内容 hash；
- 确定性测试结果；
- token 用量、延迟、错误和安全事件。

每次 evolution 还必须记录父版本、prompt/policy hash、memory 快照、tool 版本、benchmark 版本、evaluator 版本和运行环境。Git 本身不足以完整复现一次运行。

## 初始实现边界

第一类任务建议限定为本地代码仓库工作：检查文件、提出 patch、运行测试并解释结果。第一批工具默认应为只读工具。写文件和执行 shell 必须受到 workspace 边界和确认策略限制。

第一版可以使用小型 Python 服务、SQLite 记录运行元数据，并用普通文件系统保存产物。只有当检索 benchmark 证明有收益后，再加入向量检索。

## 当前已实现的 v0.1 边界

当前代码已经实现了图中的执行侧：标准库本地 HTTP API、SQLite 运行状态、JSONL 证据日志、路径受限文件系统沙箱、`list_files`/`read_file` 工具、明确受控的 `write_file` 工具、Mock 模型，以及可选的 OpenAI Responses API 适配器。Evolution Controller 目前还没有启用。
