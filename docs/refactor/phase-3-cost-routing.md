# Phase 3：Codex 性价比调度基线

本阶段使用已安装的 `cost-routing` Skill 服务当前 Codex，不改变主 Agent
的模型或推理设置，也不把模板中的 executor 当作真实可用能力。

## 已交付

- `L0` 确定性检查、`L1/L2` 边界明确的执行任务、`L3` 规划/契约/审查的职责边界；
- 任务包、依赖 DAG、允许/禁止文件、验收命令和升级条件；
- `none` 到 `ultra` 的推理强度作为计划维度；请求值、宿主实际应用值和账本实际值分开；
- PowerShell 确定性估算器输出最低/通常/最高相对单位，不冒充中转站或官方真实账单；
- 分级重试、测试失败升级、公共接口/凭据/付费/安全变化强制回主 Agent；
- 可选脱敏账本格式，不记录密钥、Cookie、正文、屏幕/摄像头内容和完整路径。

## 真实边界

Skill 不能凭模板自动创建 Agent，也不能证明某个 Codex 模型在某个推理强度下
属于某个真实能力等级。只有宿主暴露可选执行器、且维护了非模板的能力/价格/授权
证据时，主 Agent 才能做委派；否则直接执行，并把 `L0-L3` 当作任务风险标签。

推理强度会影响调用成本、耗时和质量，但不能假设所有 Provider 按强度加价。
缺少 usage、价格或实际应用强度时保持 `unknown`；输出中已含 reasoning token
时不重复计费。

## 验收

```powershell
& "$env:USERPROFILE\.codex\skills\cost-routing\scripts\estimate_task_cost.ps1" `
  -Stage implementation -TaskType adapter -Risk medium -ReasoningEffort low `
  -Files 4 -Subsystems 2 -ExternalBoundaryChange -IncludeUpgrade
```

估算器只输出相对单位；确定性检查不计模型调用。阶段 3 的主 Agent 责任仍是
拆分、集成、最终审查和对用户报告实际可见的模型设置/费用。
