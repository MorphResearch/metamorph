# AppWorld Oracle 标签

此目录用于保存 E1 Oracle 条件使用的人工复杂度标签。当前没有生成任何标签。

标签文件必须是人工在正式 test 运行前独立完成的 JSON，并记录：

- 标注者；
- 标注日期；
- 标签定义版本；
- 每个 task ID 的 `simple` 或 `complex`；
- 对不确定任务的理由或复核记录。

标签只能依据任务文本和允许观察的任务结构制作，不能依据模型运行结果、官方 reward
或 test ground-truth solution 制作。
