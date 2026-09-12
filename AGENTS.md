# Sumika Next 开发入口

本项目使用 DSH 原生 Web、Agent、工具、Skills 和 MCP。新增核心逻辑保持 Harness 中立；优先复用上游能力。

开始任务、压缩上下文后或换模型接手时：

1. 阅读 `docs/project/handoff.json`、`progress.json`、`plan.json`。
2. 需求原文在 `requirements.json`，完整已批准计划在 `approved-plan.md`；摘要不增加授权。
3. 核对 Git 和实际实现、测试证据。未验证内容不能作为完成事实。

原生 Plan 用于规划和用户确认；原生子 Agent 用于独立任务和审查。暂停使用取消后交接，恢复先检查历史和实际 diff，不自动重放未知操作。重试前查看上次操作是否已生效。

阶段成果记录实现内容、验证命令与结果、剩余问题、限制及下一步。更新现有项目记录并运行：

```powershell
python -B -m sumika_next.cli check
python -B -m sumika_next.cli handoff
```

DSH `/compact` 后仍从上述文件核验目标，不依赖摘要保存授权。原始需求、代码、diff、成果正文与模型附言保持边界。P4 通过独立连续性扩展接入自动捕获；启用后使用 continuity_query / continuity_record 及 sumika-continuity Skill。

验证说明见 `runtime/dsh/README.md`、`docs/project/phase-02-acceptance.md`。`.sumika-next/` 是本地运行数据，不上传凭据或原始模型请求。旧源码可能仍留在忽略目录中，新实现不以其为架构基础。
