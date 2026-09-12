# Sumika 新版项目连续性记录

本目录是新版项目的持久化交接入口，独立于模型上下文和 Harness 实现。

## 文件

- `requirements.json`：需求原文、来源、当前状态。
- `plan.json`：总计划和阶段计划。
- `progress.json`：实现、验证、阻碍和下一步。
- `decisions.json`：已确认决策及变更原因。
- `handoff.json`：交给下一次会话或其他模型的最小上下文。
- `backup-recovery.md`：Git checkpoint 与项目数据备份恢复规则。

所有摘要都不得替代原始需求；未知和未验证内容必须明确标记。
