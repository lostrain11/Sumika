# Sumika 模型策略契约 `model-policy/v1`

本文件定义模型选择的长期行为要求，不把任何厂商、Harness 或当前 UI 组件当作不可替换的
基础。模型目录、路由决策和额度观测必须能在 DSH、ZCode 或未来 Harness 之间复用。

## 当前有效决策（2026-09-08）

需求汇总见[总表](catalog.md)，消息证据见[原话出处](original-excerpts.md)。`MODEL-012` 至 `MODEL-020`、`TASK-002`、`BENEFIT-001` 至 `BENEFIT-003`、`PLUGIN-002`承接一体化计划及后续授权。

- `MODEL-018`取代`MODEL-007`的笼统默认：用户已允许已保存渠道中的普通有余额付费调用，按当前任务预算执行；未覆盖的范围、用户固定选择和新增影响才需要确认。不授权充值，也不授权高频维护付费。
- `MODEL-015`和`BENEFIT-002`取代`MODEL-009`：保留刷新/登录安全边界，允许已授权明确免费领取与签到自动执行；新站发现不自动注册或启用。
- 网页操作统一到 `BROWSER-003`；辅助咨询默认2–3来源，见 `BROWSER-004`。原BrowserSkill和门户仍为当前实现证据，尚未统一迁移。
- 主模型质量优先，执行和角色模型各自满足任务门槛后比成本；固定小题不能证明所有任务等质。跨渠道真实价格、额度、质量与运行时应用强度分别绑定。

## 需求 ID 索引

| ID | 主题 |
| --- | --- |
| `MODEL-001` | 免费额度优先，但必须先通过质量和安全门槛 |
| `MODEL-002` | ZCode、智谱、Ollama 的目录与边界 |
| `MODEL-003` | ZCode app-server 和登录态 |
| `MODEL-004` | 智谱官方额度和凭据 |
| `MODEL-005` | 难度、风险、质量门槛和成本排序 |
| `MODEL-006` | 禁止静默升级到付费模型 |
| `MODEL-007` | 历史默认；被 `MODEL-018` 取代 |
| `MODEL-008` | Ollama 本地健康检查与协议冒烟 |
| `MODEL-009` | 历史检查与手动领取约束；被 `MODEL-015`、`BENEFIT-002` 取代 |
| `MODEL-010` | 可比的模型与插件评测 |
| `MODEL-011` | Provider 与中转站的双口径定价证据 |
| `MODEL-012` | 模型候选身份同时包含Provider Profile、Route、Model、Transport、Harness和推理强度。 |
| `MODEL-013` | 质量以版本化多源榜单先验、官方能力、固定任务及真实使用证据逐步校准。 |
| `MODEL-014` | 主模型质量优先，执行者在满足任务质量门槛后按成本选择，角色模型独立按合格且便宜稳定选择。 |
| `MODEL-015` | 用确定性脚本分别刷新资源包、价格和目录，维护最新证据并保留过期历史。 |
| `MODEL-016` | 资源包作为账户级共享池记账，保留适用范围、余量、真实到期、来源、可信度和在途预留。 |
| `MODEL-017` | 成本按规划、执行、验证、咨询、重试和升级估算；预算阈值默认两倍且超出5元，用户可调整。 |
| `MODEL-018` | 普通任务可在已授权渠道的可用余额与预算内使用付费模型；同名跨渠道按任务质量和实际报价比较。 |
| `MODEL-019` | 模型能力页展示刷新状态、免费证据、额度到期、主模型和角色模型及选择依据，并提供手动刷新、固定模型和预算设置。 |
| `MODEL-020` | model-picker只提供目录、价格和评测建议，Sumika保留最终授权、额度、付费与执行决策。 |

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

模型条目还可以声明 `reasoning_efforts` 和 `default_reasoning_effort`。显式请求的推理强度
只有在条目明确声明支持时才可路由；未声明能力和不支持的强度分别返回明确的未知/不可用原因。
强度可能影响能力、延迟、推理 token 和价格，但不能预设所有 Provider 都按同一规则计费，
因此价格仍须由独立定价证据确认。

### `RoutingRequest`

至少包含：`task_kind`、`difficulty`、`risk`、`context_size`、`required_capabilities`、
`latency_target`、`privacy_constraints`、`budget_policy`、`confirmation_mode`、可选的
`reasoning_effort` 和可选的
`character_id`/`agent_preset_id`。

任务难度和风险可以先由确定性规则评估，再逐步引入独立分类器；分类器本身不能为了省钱而
静默调用高价模型。

### `RoutingDecision`

至少包含：`selected_route`、`alternatives`、`quality_gate`、`reason_codes`、
`estimated_cost`、`quota_impact`、`confidence`、`requires_confirmation`、`policy_version`
和有效期。还必须区分 `requested_reasoning_effort` 与 `applied_reasoning_effort`；路由决策
阶段的后者保持 `unknown`，只有 Runtime 的模型选择回执确认后才能填充。没有满足质量门槛
或推理强度门槛的候选时，结果必须是需要用户处理的明确失败。

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

### 定期观测与资源包共享池

资源包额度和价格/模型目录是两条独立的确定性刷新链路。默认资源包每日观测一次，价格与
目录每 12 小时观测一次；路由前发现观测过期时可执行受控刷新。观测任务不调用模型，不自动
登录、购买、充值或读取 Cookie/API Key。失败时保留历史快照并标记 stale/needs-review，不以
旧值伪造当前免费状态。

资源包按 `provider_profile_id + pack_id` 保存，并记录 `applies_to`、剩余量、单位、
`observed_at` 和真实 `expires_at`。同一资源包适用多个模型时是共享池，不能按模型分别重复
计算；同类资源包按真实到期时间优先消耗。在途预留由执行层单独计算，不改变网页观测余额。

账户额度绑定还需匹配端点和非秘密凭据修订号。更换 Key、端点或账户后，旧资源包不能自动
继承给新连接，不能通过重新创建运行时绕过限制。执行前另行复核模型/推理强度、权限、
健康、当前助手评测及价格版本；旧确认不覆盖改变后的执行绑定。明确未发送的请求可释放
预留，部分回复、提交未知或账单未知不能据此恢复额度。

免费价格只是一条带来源和有效期的价格证据，不等于账号剩余额度。官方 API、官方网页、中转
站和网页聊天分别保存，不能互套价格。新模型先进入 `observed`/`pending-evaluation`，完成
健康检查和至少三次固定评测后才能成为 `routable`。目录消失或模型下线时停止新路由，但保留
历史评测和费用记录。

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
授权和健康确认后，才会出现对应的可路由档案；即便如此，路由仍须遵守当前范围授权和
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

未获得范围授权或由用户固定要求确认的场景，采用推荐后确认；已明确授权的普通任务可在余额和预算内自动选用合格付费候选，不能反复要求相同小额确认。自动执行仍受质量下限、安全和预算约束；免费耗尽不得越过当前任务的付费边界，高频维护始终不升级付费。没有满足契约的候选时明确暂停。

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

### `MODEL-009` 低打扰额度检查（历史）

> 下述旧手动领取限制已由 `MODEL-015`、`BENEFIT-002` 取代。保留供历史对照，不可用来撤回用户后续自动签到授权。

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

### 2026-09-08：高频维护成本与现有付费渠道授权

- 用户要求自动寻找免费/限免模型、福利发现、价格/余额刷新和签到等高频任务尽量不花钱。默认采用确定性脚本、RSS/API/DOM和本地解析；现有这些维护流程不调用模型。以后如增加语义筛选，默认只允许有新鲜免费证据的合格模型或本地执行，免费不可用时延后/跳过，不升级到付费模型。新站注册、登录或网站验证仍按既有范围处理。
- 用户明确允许使用此前已经保存的渠道中的付费模型，只要有可用余额，服务于普通任务并遵守现有任务预算。无需为同一已授权范围的普通小额调用反复询问；这不授权充值，也不把普通任务付费权限套用到高频维护。余额必须对应实际执行账号/资源包；未知余额、未知价格不能伪装为可用或免费。
- 同名模型在不同渠道保留独立执行候选。对齐实际模型版本、推理强度、上下文与工具能力后，分别核验任务质量、健康和额度，再按本任务预计输入/输出/缓存/推理消耗计算该渠道真实费用。中转倍率、现金折算、赠送抵扣、已购资源和期限不能混为同一种余额；已充值不意味着调用免费，也不按谁的余额更多决定路线。
- 当前实现状态：确定性维护已存在；`ModelRouter`与协作执行者共用渠道报价和合格候选成本排序，赠送、已购资源和现金分开计算，主模型仍质量优先。来源或购入价值缺失保留未知，额度不足不静默转现金。现有付费渠道尚未全部绑定正式价格、余额与固定评测；统一算法不等于全部渠道已自动择优，真实证据与现金账单对账仍待补齐。见[统一报价记录](../refactor/unified-route-costs.md)。

当前代码已经提供 `model-policy/v1` 的基础、确定性路由闭环：

- `ModelPolicyService` 从 Provider profiles、Runtime 的公开全局/Session 模型目录和网页聊天
  候选构建有界 catalog；`model.policy.catalog`、`model.policy.route`、
  `model.policy.preflight`、`model.policy.apply` 和 `model.policy.quota` 是 Core 入口；
- `ModelRouter` 先过滤安全/隐私、能力、健康、任务质量与资金可用性，再尊重显式用户选择，按统一有效成本排序；
  `difficulty=auto` 目前使用 `infer_difficulty()` 的保守规则，不是机器学习分类器；
- 路由请求支持显式 `reasoning_effort`；模型必须声明对应能力才会进入候选，策略推荐不声称
  已经应用强度，Core 仅在 Agent Runtime 回执中获得 `applied_reasoning_effort`；DSH、ZCode
  和动态子任务选择路径会转发显式强度；
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
- `model-refresh/v1` 提供原子观察/预留账本、stale 状态与 `model.policy.refresh`/status；
  公开价格先解析静态表，再用已安装 Playwright 的独立无登录浏览器读取固定 DOM。
  资源 DOM/OCR 由宿主绑定明确的官方页 session/tab/profile；无账户关系或未知时区不可抵扣。
  目录缺项标为 `needs-review` 而非凭部分价格表直接宣布下线，不自动替换负责人。
- 实际 Provider 发送前接入共享资源预留；型号精确匹配、账户隔离、最早到期优先，
  失败/取消/提交未知保留预留，耗尽不转现金。尚无账单 watermark 对账，可能保守重复扣减。
- 自动选择在明确候选池和版本化固定评测范围内进行，负责人质量优先、角色合格后成本优先；
  未具备三次成功固定样本或实际推理强度证据的候选不因免费进入自动选择。
  已用负责人变化时先提示重新确认；默认保持原固定模式和日用配置。

尚未完成的部分是跨真实账户的自动资源包采集、长期质量判定器、学习型难度分类器和后台健康
探针。它们完成前，不能把一次成功请求或离线诊断建议当作“自动选择已全面可用”，
也不能越过当前任务授权自动切换到付费模型；真实 Provider、ZCode 登录态和额度仍需用户主动配置并以最新
preflight 结果为准。
