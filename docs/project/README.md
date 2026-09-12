# Sumika 新版项目连续性记录

本目录是新版项目的持久化交接入口，独立于模型上下文和 Harness 实现。

## 文件

- `requirements.json`：需求原文、来源、当前状态。
- `plan.json`：总计划和阶段计划。
- `progress.json`：实现、验证、阻碍和下一步。
- `decisions.json`：已确认决策及变更原因。
- `handoff.json`：交给下一次会话或其他模型的最小上下文。
- `receipts/<task_id>.json`：显式任务成果记录（人工声明，含验证与剩余项）。
- `backup-recovery.md`：Git checkpoint 与项目数据备份恢复规则。
- `approved-plan.md`：用户批准的完整八阶段计划原文。
- `phase-01-acceptance.md` 至 `phase-04-acceptance.md`：各阶段实现与实际验收证据。
- `../../extensions/continuity/README.md`：P4 独立扩展、适配器、开关及本地原始记录说明。

所有摘要都不得替代原始需求；未知和未验证内容必须明确标记。

## 更新与交接

从 handoff → progress → plan 开始，按 requirement ID 查原文，按验收文件查证据。
新需求追加 ID 和 sequence，保存原文、来源与原文 SHA256。没有可核实的消息时间/ID 就填 null 并使用对话定位短语；不要编造来源。
变更通过新条目引用 supersedes，旧条目保留并改为 superseded；阶段任务和决定同步更新，新计划版本在 history 记原因，Git 保留旧全文。
模型整理不写进 original，写入 decisions 或任务说明并标明 implementation_default；原始摘要不能增加授权。
在需求、计划、成果、验证或阻碍变化时更新记录，运行 `python -B -m sumika_next.cli check`。
`python -B -m sumika_next.cli handoff` 输出可交给另一模型的目标、进度、约束、下一步和原文索引，不依赖旧源码和聊天缓存。
P4 独立扩展从 DSH 会话自动捕获原文和生命周期事件，注入来源明确的交接；目标、计划变化和成果由专用工具按 Skill 记录，仍需如实区分报告与验证。

## 成果记录（receipt）

```powershell
python -B -m sumika_next.cli receipt --root <项目根> --input <project-relative JSON>
```

`--input` 必须是项目内相对路径，7 个字段的类型严格校验：

```json
{
  "task_id": "P3-receipt-001",
  "session_id": "sumika-...",
  "summary": "一句话成果",
  "changes": ["sumika_next/receipts.py"],
  "verification": [{"command": "python -B -m unittest discover -s tests_next", "result": "passed"}],
  "remaining": ["未完成项"],
  "next": "下一步"
}
```

- `verification` 每项只有 `command` 和 `result`；`result` 只能是 `passed`、`failed`、`not_run`，状态原样保留，不因失败或未运行而丢弃记录。
- `task_id`、`summary`、`next` 不接受空值；`task_id` 只允许 ASCII 字母数字开头、由 `A-Za-z0-9._-` 组成，不支持路径分隔符或穿越。
- `session_id` 必须是字符串，strip 后为空写作 `null`（写读两侧一致，可正常读回）。
- 未知/缺失字段、类型不符、列表空项、非法 `result`、绝对或越界的 `--input`、缺少 `docs/project`、无法按 UTF-8 编码的文本一律拒绝，且不写任何文件（不会残留半成品）；已有 task_id 拒绝覆盖。
- 记录附 `schema_version`、`provenance=operator_report`、当前 Git HEAD（无 Git 为 `null`）和 UTC `recorded_at`；读取时校验 `recorded_at` 必须是带 UTC 偏移的 ISO 时间。
- 它是操作者声明，不构成独立验证，也不改变 `phase_status`；阶段完成仍以 `plan.json` 的 `evidence` 为准，`check` 会对损坏的 receipt 文件或名为 `*.json` 的目录报错；`.json` 以外的普通文件（如 `.gitkeep`、编辑器备份）会被忽略，`A.JSON` 与 `a.json` 在所有平台按同一记录处理。
- `handoff` 追加最近 3 条成果摘要与验证/剩余项，便于压缩上下文或更换模型后接手；没有 `receipts/` 的旧项目输出保持不变。

- `agent-diagnostics-plan.md`：F-001 Agent 专用诊断日志未来计划。
- `continuity-comparison.md`：P4 与 Codex/DSH 原生能力及社区方案的比较与限制。
- `long-term-memory-plan.md`：P6 长期记忆的现成方案接入、可替换边界与实测选型。
- `ui-design-plan.md`：插入 P5 前的 UI 设计阶段与旧版参考。
