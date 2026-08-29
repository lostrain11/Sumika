# Sumika 模型策略契约 `model-policy/v1`

本文件定义模型选择的长期行为要求，不把任何厂商、Harness 或当前 UI 组件当作不可替换的
基础。模型目录、路由决策和额度观测必须能在 DSH、ZCode 或未来 Harness 之间复用。

## 需求 ID 索引

| ID | 主题 |
| --- | --- |
| `MODEL-001` | 免费额度优先，但必须先通过质量和安全门槛 |
| `MODEL-002` | ZCode、智谱、Ollama 的目录与边界 |
| `MODEL-003` | ZCode app-server 和登录态 |
| `MODEL-004` | 智谱官方额度和凭据 |
| `MODEL-005` | 难度、风险、质量门槛和成本排序 |
| `MODEL-006` | 禁止静默升级到付费模型 |
| `MODEL-007` | 推荐后确认和全自动策略 |
| `MODEL-008` | Ollama 本地健康检查与协议冒烟 |
| `MODEL-009` | 低打扰额度检查 |
| `MODEL-010` | 可比的模型与插件评测 |

## 目标

在满足安全、隐私和最低质量要求的前提下，优先使用用户已经授权的免费或低成本资源，减少
高价模型的无谓消耗；选择结果必须可解释、可复盘，不能静默改变用户的付费或数据处理边界。

## 稳定概念接口

### `ModelCatalogEntry`

至少包含：`provider_profile_id`、`model_id`、`harness_id`、`capabilities`、`quality_tier`、
`cost_class`、`processing_location`、`auth_state`、`quota_state`、`health_state`、
`observed_at` 和版本信息。

`quality_tier` 只表示 Sumika 评测等级，不把厂商宣传当作质量证据；`cost_class` 可为
`local`、`free-limited`、`paid-low`、`paid-high` 或 `unknown`。

### `RoutingRequest`

至少包含：`task_kind`、`difficulty`、`risk`、`context_size`、`required_capabilities`、
`latency_target`、`privacy_constraints`、`budget_policy`、`confirmation_mode` 和可选的
`character_id`/`agent_preset_id`。

任务难度和风险可以先由确定性规则评估，再逐步引入独立分类器；分类器本身不能为了省钱而
静默调用高价模型。

### `RoutingDecision`

至少包含：`selected_route`、`alternatives`、`quality_gate`、`reason_codes`、
`estimated_cost`、`quota_impact`、`confidence`、`requires_confirmation`、`policy_version`
和有效期。没有满足质量门槛的候选时，结果必须是需要用户处理的明确失败。

### `QuotaSnapshot` 与 `EvaluationSample`

`QuotaSnapshot` 记录额度来源、检查时间、有效期、剩余额度区间、可信度和是否需要人工认证，
不保存账号秘密。`EvaluationSample` 只记录任务类别、版本、成功/失败、工具完成、重试、
延迟、成本、额度消耗和有限质量标签，不记录请求正文或输出正文。

## 决策优先级

路由器必须按以下顺序过滤和排序：

1. 安全、凭据、权限和处理位置约束；
2. 所需能力和最低质量门槛；
3. 用户明确指定、会话策略和确认模式；
4. 免费额度、预算和预计成本；
5. 延迟、健康状态和近期评测结果。

默认模式为“推荐后确认”。用户可以为明确的 AgentPreset 或会话开启全自动，但全自动仍
受硬预算、质量下限和安全策略约束。免费额度耗尽时不静默切换到付费模型；若没有同等合规
候选，应暂停并提示用户。

## 首批真实来源

### ZCode

ZCode 是独立的 `AgentRuntime` 来源，通过受支持的 `app-server --stdio` 和自身登录态使用
Session、Plan/Execute、工具和事件。Sumika 不读取 ZCode 配置提取 Token，不把未验证的内部
接口当作 OpenAI-compatible endpoint。额度状态若不能由协议可靠提供，必须显示 `unknown`，
不能标为“免费可用”。

### 智谱

智谱使用现有 OpenAI-compatible Provider 档案和 Credential Manager。免费额度只能来自官方
用量接口或用户在官方页面完成的人工确认，不能把活动宣传或旧截图写成永久额度。密钥失效、
过期或额度未知时，路由器必须要求重新认证或用户选择其他候选。

### Ollama

Ollama 是本地 Provider 和测试后端。`GET /v1/models` 只做连通性/目录检查，不生成内容；
短 `chat/completions` 仅用于本地协议冒烟。隔离测试中 `qwen3:1.7b` 适合快速检查，
`qwen3:4b` 适合较完整的工具和上下文验证；两者默认不进入日用高风险路由。

### 高价模型

高价模型只有在存在已授权、健康且符合隐私策略的真实端点，并且免费/低成本候选无法满足
质量门槛时，才可进入推荐。若端点不存在，不得把模型名称显示成可用 Provider。

## 额度监控

### `MODEL-009` 低打扰额度检查

启动时只在超过检查间隔、系统空闲、没有游戏/高负载且没有运行 Agent 时检查；Developer 页
允许手动刷新。监控优先使用公开、版本化的官方来源；登录、OTP、CAPTCHA、领取活动、
付款和权限修改永远暂停并请求用户。

额度结果至少区分：`available`、`low`、`exhausted`、`expired`、`needs-auth`、`blocked`、
`unknown`。未知结果不得参与“免费优先”的强结论。

## 评测基准

### `MODEL-010` 可比的模型与插件评测

固定非敏感任务集至少覆盖：只读问答、单文件修改、多文件重构、工具调用、Plan Review、
MCP、浏览器审批和恢复。比较时固定模型/插件版本、任务难度和上下文规模，观察：

- 任务完成和工具调用成功率；
- 用户修正、重试、取消和错误恢复率；
- 冷启动/热缓存的 p50/p95 延迟；
- 输入/输出单位、估算成本和额度消耗；
- 质量门槛是否达成及样本置信度。

单纯更快不代表更优。样本不足、版本不一致、质量不可比或发现敏感信息泄漏时，评测只能
作为诊断，不能自动改变默认路由。

## 与未来 Harness 的兼容

Provider、模型目录、额度监控、路由策略和评测记录属于 Sumika 的通用边界；DSH/ZCode 只
实现 Session、事件、工具和审批的 adapter。更换 Harness 时不迁移角色、Avatar、浏览器
策略、Workspace 安全或凭据格式；只替换运行时事件翻译和启动器。

## 当前实现差距

当前只有 DSH Session 级手动模型选择和脱敏观测，尚无难度分类器、自动推荐、额度目录、
ZCode adapter 或自动评测选择器。实现这些能力前，先完成文档基线和固定夹具，避免把一次
成功请求误判为路由能力。
