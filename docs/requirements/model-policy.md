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
| `MODEL-011` | Provider 与中转站的双口径定价证据 |

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

### `PricingSnapshot`、`CostEstimate` 与 `ChargeReceipt`

定价按 `provider_profile_id + model_id + billing_group` 隔离。`PricingSnapshot` 记录站内币种、
输入/输出/缓存和上下文阶梯价格、来源、版本、有效期与可信度；`CostEstimate` 分别给出站内
扣费和用户实际现金折算区间；`ChargeReceipt` 保存请求级 usage、可归属扣费和证据等级。
官方价格不得套用到中转 Route；充值折扣只能由用户录入实际支付/到账换算率，不能扫描订单、
账单或支付记录推断。无法解析的动态计费表达式保持 `unknown`，不得执行服务端代码。

### 能力目录投影

模型策略目录通过 `capability-catalog/v1` 向 Modules 和 Developer 提供只读的实现投影。它
可以同时列出 Provider profile、Harness model 和网页聊天候选，但不改变 `RoutingDecision`
的选择结果，也不把网页会话当成 API endpoint。每一项必须携带可验证的来源类型、处理位置、
认证/额度/健康状态和是否可选；网页聊天固定为 `needs-auth` 与人工登录边界。目录过滤 Fake、
Stub、Placeholder 和敏感元数据，来源探测失败只影响对应条目并保留受限错误类型。

### 网页聊天候选

网页聊天档案通过 `BrowserRuntime` 投影为 `source_kind=web-chat`、
`transport=browser-dom` 的候选。内置站点和自定义站点都先标记为 `needs-auth`、
`quota=unknown`、`requires_user_login=true`，不能因为浏览器已打开或页面出现发送
按钮就进入路由。只有档案完成隔离 Profile 人工登录、页面检查、`chat.send` 一次性
授权和健康确认后，才会出现对应的可路由档案；即便如此，路由仍须遵守推荐后确认和
预算策略，网页端额度未知时不能被当作免费额度。

网页 Provider 只发送用户明确提交的当前消息，并从页面中提取新的 assistant/model/bot
回复。页面快照在 Core 边界限深、限长并过滤凭据字段；没有新回复、快照损坏或回复
疑似包含密钥时，适配器返回受限失败，不伪造回答、不导出原始快照。站点选择器是
声明式配置，适配器不执行导入的 JavaScript，也不读取 Cookie 或网页端 Token。

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

当前已对安装的 ZCode `app-server --stdio` 做过只读协议探测：它使用无 `jsonrpc` 字段的
行分隔消息，首个健康探针为 `session/list`；工作区级目录使用 `workspace/readState`，会话
使用 `session/create`、`session/send`、`session/read`、`session/messages`、`session/stop`、
`session/setModel`、`session/setMode` 和 `session/subagents`。创建会话前的
`session/requestRuntimePreferences` 由 adapter 以安全默认值应答。旧标准 JSON-RPC peer 仍可
通过 `SUMIKA_ZCODE_PROTOCOL=jsonrpc` 或 `auto` 的只读探测兼容。该探测只证明协议和进程可达，
不证明模型配置、账号额度或生产会话可用；缺少模型配置时保持“未就绪”。

Windows Electron 安装可在用户显式设置 `SUMIKA_ZCODE_AUTODISCOVER=1` 和安装目录后，由
适配器解析旁边的公开 `resources/glm/zcode.cjs` 并交给 Node 启动；这只解决启动入口，
不读取 ZCode 私有设置或登录凭据。当前本机只读验证得到 2 个模型，额度能力未公开，仍为
`unknown`。

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

## 动态路由决策追踪

`route-decision-trace/v1` 为每次 replan 生成独立 trace，并在事件边界、候选过滤、排序、选择、
确认、派发、去重、重试、取消、超时和终态持续追加记录。每个候选单独记录能力、质量、额度、
成本、健康、排序维度，以及证据引用哈希、类型、可信度和新鲜度；终态记录可用 usage、双口径
费用回执、延迟、错误码、`retryable` 和 `possibly_sent`。`replan` 返回 `trace_id`，确认后的
`dispatch` 应带回该 ID，确保等待确认不会切断同一决策链。

trace 只保存 allowlist 标量和本次 Core 启动 salt 下的关联哈希，不保存问题、回复、上下文、
代码、diff、DOM、工具参数/结果、路径或凭据。它可以支持离线诊断和后续固定评测，但不能自行
改变生产路由、质量等级、预算、Provider 启停或授权。完整要求见 `OBS-002`。

## 与未来 Harness 的兼容

Provider、模型目录、额度监控、路由策略和评测记录属于 Sumika 的通用边界；DSH/ZCode 只
实现 Session、事件、工具和审批的 adapter。更换 Harness 时不迁移角色、Avatar、浏览器
策略、Workspace 安全或凭据格式；只替换运行时事件翻译和启动器。

## 当前实现

当前代码已经提供 `model-policy/v1` 的基础、确定性路由闭环：

- `ModelPolicyService` 从 Provider profiles、Runtime 的公开全局/Session 模型目录和网页聊天
  候选构建有界 catalog；`model.policy.catalog`、`model.policy.route`、
  `model.policy.preflight`、`model.policy.apply` 和 `model.policy.quota` 是 Core 入口；
- `ModelRouter` 按安全/隐私、能力、质量、用户偏好、额度/成本和延迟的固定顺序过滤与排序；
  `difficulty=auto` 目前使用 `infer_difficulty()` 的保守规则，不是机器学习分类器；
- Agent 新建 Session 和发送 Execute/Plan 目标都可以显式携带 `routing` 或 `auto_route=true`。
  无候选、未确认或健康检查失败时，Core 在创建 Session、绑定 Provider 或 Workspace checkpoint
  之前返回明确结果；默认仍是“推荐后确认”，既有未携带 routing 的 Session 行为保持不变；
- 声明式 Provider 用量查询只执行白名单 HTTP 请求和字段提取，JavaScript 脚本不会执行；结果
  按 15 分钟 TTL 缓存并保存脱敏快照。ZCode adapter 只在 app-server 宣布公开 quota/usage
  capability 时读取额度，否则保持 `unknown`；当前固定测试 fixture 验证了目录、状态推导和
  缓存，不能代表用户本机 ZCode 已公开额度；
- ZCode 的全局模型目录只通过公开 app-server 方法读取，不创建试探 Session、不读取配置文件或
  登录凭据。网页聊天候选默认需要人工登录和一次性授权，且不可静默路由或宣称未知额度为免费。
- 固定任务集和离线评测器已提供 `sumika.model-evaluation/v1` 记录、可比 cohort、Wilson 95%
  区间以及成功率/工具/质量/重试/延迟/成本统计；诊断建议不会改变生产路由，默认每个任务
  至少需要 3 次重复样本；
- `RoutePricingService` 已实现 Direct Official、New API、PinAI 和 Manual 定价来源，一档案多个
  模型共享凭据但形成独立 Route；站内扣费和现金折算分别展示；
- `route-decision-trace/v1` 已接入运行时中立 Supervisor，并通过 Core RPC、HTTP 和
  `tools/aggregate_agent_day.py` 提供有界日聚合。

尚未完成的部分是跨真实账户的额度适配器、长期样本持久化/质量判定器、学习型难度分类器和
后台自动刷新。它们完成前，不能把一次成功请求或离线诊断建议当作“自动选择已全面可用”，
也不能自动切换到付费模型；真实 Provider、ZCode 登录态和额度仍需用户主动配置并以最新
preflight 结果为准。
