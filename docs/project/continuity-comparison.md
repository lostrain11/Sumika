# P4 与原生能力、现有扩展的比较

本次核对官方文档、已安装 DSH rc.2 包内文档和下列项目 README。社区项目尚未安装或在 Sumika 中做效果/兼容性比较，不能据此称某个方案最佳。

## 原生已经提供什么

Codex 的 [会话恢复](https://developers.openai.com/codex/cli/features)、[本地 Memories](https://developers.openai.com/codex/customization/memories)、[AGENTS.md](https://developers.openai.com/codex/guides/agents-md)、[Skills](https://developers.openai.com/codex/skills) 和 [Hooks](https://developers.openai.com/codex/hooks) 已覆盖大量基础能力。Memories 能从符合条件的历史聊天生成本地记忆，后台更新；官方仍建议把必须遵守的规则放在 AGENTS.md 或版本化文档。Hooks 明确支持持久记忆和自定义日志场景，包括压缩前后事件。

DSH rc.2 的 dsh-session-persistence-jsonl 提供持久化会话、格式迁移和崩溃恢复；dsh-compaction-basic / compact 命令提供自动及手动压缩，原内容仍保留在会话日志。原生插件、Skills、Hook 桥提供接线机制。因此“保存历史、压缩、恢复、插入上下文”不是 P4 新发明的功能。

## P4 实际增加的部分

- 以项目为单位、脱离 Harness profile 的记录库和查询契约；更换 Harness 可以继续读取同一份数据。目前只有 DSH 适配器完成实测，其他适配器尚未实现。
- 保存直接用户来源的原文，并将其与模型归纳、插件上下文分开；提供稳定来源 ID 和重放去重。保存原文不等于把每句话认定为有效需求或批准。
- 用固定字段记录目标、前后计划、变更原因、影响任务、验证声明、剩余项和下一步，并关联会话与 Git HEAD。
- 把这套项目记录实际接入 DSH 的提示、压缩、恢复和专用工具，具有项目显式启用和功能开关。

这些是针对本项目的工程整合和数据约定，不是领先原生产品的通用记忆技术。目标、计划和成果的语义记录仍依赖模型按 Skill 调用工具；不会自动理解所有需求变化，也不会独立证明模型报告真实。现有验收使用真实 DSH 与本地确定性模型端点，验证接线与恢复传递，未测真实云端模型的长期自动归纳质量。

## 类似项目

| 项目 | README 展示的相似能力 | 与本项目取舍 |
| --- | --- | --- |
| [planning-with-files](https://github.com/OthmanAdi/planning-with-files) | task_plan.md、findings.md、progress.md 持久化；生命周期 Hook 注入与恢复；支持多种 Agent/原生插件 | 与 P4 目标最接近，应优先比较能否复用其 Skill/接线。尚未证明可直接安装到当前 DSH，或与本项目来源/声明边界完全一致。 |
| [Beads](https://github.com/steveyegge/beads) | 持久结构化任务、依赖图、JSON 输出、工作流上下文和项目记忆 | 更适合任务依赖和协作管理；引入前评估是否会重复现有计划/状态系统。 |
| [claude-mem](https://github.com/thedotmack/claude-mem) | 生命周期采集、SQLite 会话/观察/摘要、记忆搜索与跨会话上下文 | 更接近自动观察和记忆检索。当前 README 涉及托管 observer、账户和提供方选择，应核对费用、数据流和本地模式，不视为零成本即插即用。 |

上轮 P4 选型只核对了 DSH 官方 Hook 桥，未充分比较这些社区项目；因此当时“不适合官方桥”的结论不等于“没有合适开源方案”。后续扩展 P4 前应先做这些候选与现有实现的比较，能复用则优先复用；本次不擅自替换已经工作的存储格式或安装新依赖。
