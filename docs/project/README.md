# Sumika 新版项目连续性记录

本目录是新版项目的持久化交接入口，独立于模型上下文和 Harness 实现。

## 文件

- `requirements.json`：需求原文、来源、当前状态。
- `plan.json`：总计划和阶段计划。
- `progress.json`：实现、验证、阻碍和下一步。
- `decisions.json`：已确认决策及变更原因。
- `handoff.json`：交给下一次会话或其他模型的最小上下文。
- `backup-recovery.md`：Git checkpoint 与项目数据备份恢复规则。
- `approved-plan.md`：用户批准的完整八阶段计划原文。
- `phase-01-acceptance.md`：本轮实现与实际验收证据。

所有摘要都不得替代原始需求；未知和未验证内容必须明确标记。

## 更新与交接

从 handoff → progress → plan 开始，按 requirement ID 查原文，按验收文件查证据。
新需求追加 ID 和 sequence，保存原文、来源与原文 SHA256。没有可核实的消息时间/ID 就填 null 并使用对话定位短语；不要编造来源。
变更通过新条目引用 supersedes，旧条目保留并改为 superseded；阶段任务和决定同步更新，新计划版本在 history 记原因，Git 保留旧全文。
模型整理不写进 original，写入 decisions 或任务说明并标明 implementation_default；原始摘要不能增加授权。
在需求、计划、成果、验证或阻碍变化时更新记录，运行 `python -B -m sumika_next.cli check`。
`python -B -m sumika_next.cli handoff` 输出可交给另一模型的目标、进度、约束、下一步和原文索引，不依赖旧源码和聊天缓存。
阶段 0/1 使用显式维护；自动从 DSH 会话捕获并注入上下文属于 P4。
