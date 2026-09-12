# Agent Runtime portability

Sumika 的 Agent 子系统采用“稳定会话内核 + 可选 capability”边界。当前生产
adapter 是 DSH，但 Core、UI 和 Tauri 生命周期不以 DSH 的完整功能集合为最低接口。

## 稳定内核

每个 `AgentRuntime` 只必须实现：

- `status` / `health`；
- `create_session` / `list_sessions`；
- `snapshot`；
- `prompt` / `cancel`。

事件通过 `set_event_sink` 投影为 Sumika 事件。Preset、Provider bridge、Plan、Readonly、
Queue、Goal、MCP 观察、MCP 配置、Skills、Subagents、DSH Workspace 登记、附件和原始
导出都是 `AgentCapability`。MCP 配置使用独立的 `mcp-configuration` ID，因此只支持
MCP 工具目录的其他 Harness 不会显示写入控件。未实现的 capability 必须明确返回
unsupported，不允许伪造结果或回退到 Fake。

`agent.status` 返回 `runtime_id` 与 `runtime_capabilities`。前端只渲染运行时声明的
控制；新 adapter 不必实现 DSH 的 Preset、Goal revision 或 Queue/Steer。

`CapabilityCatalog` 可把 Harness 自身、Harness model、Provider profile、Skill、MCP 和
BrowserSkill 投影到同一只读目录。该目录不要求 adapter 实现 DSH 私有 API，也不改变
Session、模型路由或审批事实源；未来 Harness 只需在 adapter 返回稳定状态/能力后即可复用
同一 UI 投影。网页聊天属于需要人工登录的独立来源，不会被当作 Runtime Provider。

## 选择与构造

`AgentRuntimeRegistry` 保存真实 adapter builder；`SUMIKA_AGENT_RUNTIME` 选择当前
runtime，默认值仍为 `dsh`。未知 ID 返回 fail-closed 的
`UnavailableAgentRuntime`，不会静默回退 DSH。`CoreApplication` 允许注入 Runtime，
用于 contract test 和将来的 adapter 集成。

Provider bridge 是可选能力。声明该能力的 adapter 由 Core 将当前 Sumika Provider
档案显式同步；没有声明时，新会话由 Harness 自己管理 Provider，Core 不强制要求
Sumika Provider 档案。

### ZCode adapter

可选 `zcode` adapter 使用 ZCode 官方 `app-server --stdio` 边界，不读取其配置、Cookie
或凭据文件。当前 ZCode wire 是无 `jsonrpc` 字段的行分隔对象，adapter 先用
`session/list` 探测，再按 workspace 描述调用 `session/create`、`session/send`、
`session/read`、`session/messages`、`session/setModel`、`session/subagents` 和 `mcp/list`。
`session/requestRuntimePreferences` 使用安全默认值自动应答。`SUMIKA_ZCODE_PROTOCOL=auto`
默认兼容旧标准 JSON-RPC peer；Node 打包入口可用 `SUMIKA_ZCODE_NODE` 与
`SUMIKA_ZCODE_SCRIPT` 显式配置。Windows 上也可在用户显式设置
`SUMIKA_ZCODE_AUTODISCOVER=1` 与 `SUMIKA_ZCODE_INSTALL_DIR` 后自动解析
`ZCode.exe` 旁边的公开 `resources\\glm\\zcode.cjs`，并改用 Node 启动，避免 Electron
单实例壳提前退出；找不到脚本时不会猜测或回退。模型目录同时读取 Provider 分组和公开的 `available`
选项；显式的短 `providerId/modelId` 选择通过 `session/setModel` 发送，只有调用方提供
完整且经过结构校验的 `runtimeModel` 才会进入 `session/create` 或 `session/send`，不会
凭空生成 Provider 或凭据。现代协议未验证的 `readonly`、附件和队列能力不会显示。

## 会话连续性

前端只在浏览器本地存储当前 `runtime_id` 与 `session_id`，不保存消息、Workspace 路径、
工具结果或凭据。启动和刷新时必须先用 Runtime 的 `list_sessions` 验证该引用；引用有效时
恢复所选会话，无引用时打开 Runtime 返回的最近会话，引用失效时回退到最近会话。恢复后
Commands、Skills、Interactions、Models、Queue、Subagents 和 Workspace 归属都重新按
Session 作用域读取，浏览器缓存不能覆盖 Runtime 权威状态。

新 Session 创建后，Runtime 的列表投影可能短暂滞后。此时前端保留刚由 `create_session`
返回的 ID，等待下一次 roster 收敛；只有没有活动 ID 且 roster 为空时才清除恢复引用。
该本地引用只提供同一 Runtime 的界面连续性，不是跨 Harness 的 Session 迁移格式。

## Workspace 安全桥

`AgentCapability.WORKSPACES` 只描述 Harness 的会话归属和目录登记。Git 文件安全由
独立的 `WorkspaceRuntime` 负责，因此一个未来的 Harness adapter 不必实现 DSH 的
Workspace API 才能复用 checkpoint、diff 和恢复边界。Core 对外提供：

- `workspace.inspect`；
- `workspace.checkpoints`；
- `workspace.checkpoint.create`；
- `workspace.checkpoint.diff`；
- `workspace.worktree.preview` / `workspace.worktree.create`；
- `workspace.commit.preview` / `workspace.commit`；
- `workspace.restore.preview`；
- `workspace.restore`。

该边界只接受绝对 Git 仓库路径，拒绝 `deprecated/`、路径穿越和符号链接，并公开
文件级摘要、哈希和计数，不公开内部 blob。恢复必须带当前预览令牌、明确批准和完整
checkpoint ID；在写回前自动创建恢复前 checkpoint，并把被覆盖的当前文件放入可恢复
归档。worktree 创建和本地 commit 也采用独立预览令牌与精确确认；commit 的 patch 仅在
响应中返回，不进入审计，且不运行 hooks、不签名、不 push。该边界不替代 DSH 的
`artifact`/`rollback` API。

对声明 `workspaces` 的已就绪 Runtime，新 Session 必须绑定已登记且通过 Git 检查的
Workspace，不再回退到 Core 进程目录。Execute 请求必须携带与 Session 归属一致的
`workspaceId`；Core 在把目标交给 Harness 前创建 checkpoint，失败时不发送目标。
Plan 请求本身及未来由 Runtime 明确声明的 Readonly 不创建执行 checkpoint；当 Runtime
的 Plan Review 批准会在同一回合继续执行时，Core 必须在回复批准前创建 checkpoint，
checkpoint 失败则拒绝批准。

## 进程生命周期

Tauri 使用通用 `AgentLaunchConfig` 监督可选 Runtime 子进程。配置包含 executable、
arguments、environment、endpoint、profile、health probe 和日志路径；当前只有真实
DSH launcher。未登记 Runtime 可以由用户在外部启动，但不能开启受管 autostart。

通用环境变量为：

- `SUMIKA_AGENT_RUNTIME`；
- `SUMIKA_AGENT_AUTOSTART`；
- `SUMIKA_AGENT_EXECUTABLE`；
- `SUMIKA_AGENT_ENDPOINT`；
- `SUMIKA_AGENT_PROFILE_DIR`。

Provider bridge 的远程密钥不属于通用 Runtime 配置。Windows 桌面壳只在启动受管
Runtime 前，通过只读 helper 从当前数据目录对应的 Windows Credential Manager
namespace 读取已启用 Provider 的 API Key，并用 NUL 分隔的私有管道返回给父进程。
父进程把它放入该 Runtime 的启动环境；值不进入命令行、DSH settings、SQLite、事件或
日志。密钥轮换会改变非敏感的环境变量引用，已经运行的 Runtime 必须重启后才能使用新值。

现有 `SUMIKA_DSH_*` 变量继续作为 DSH 兼容别名。更换 Harness 时新增 adapter、事件
翻译器和 launcher 配置，不修改角色、Avatar、BrowserRuntime、SQLite 或桌宠边界。

## Browser capability boundary

浏览器是可选 capability，不是 `AgentRuntime` 的内核接口。BrowserSkill 负责实际浏览器
控制，DSH 或未来 Harness adapter 负责把结构化工具调用接入其生命周期；Sumika Core 的
`BrowserPolicyEvaluator` 负责统一的域名、敏感动作、人工接管和审计决策。DSH 适配器通过
`tools/pre-execute` 调用 `browser.policy.evaluate`，因此替换 Harness 时可复用策略和
运行时，只重写工具/审批事件映射。策略桥失败时必须拒绝浏览器调用，不能为了兼容性绕过
Core 或退回直接执行 CLI。

网页聊天档案是 Browser capability 上的独立 `web-chat/v1` 投影：它复用命名 Profile、
页面快照和受审批的 DOM 动作，但不把网页登录态当作通用 Provider 凭据。其登录、页面
就绪、一次性聊天授权和回复提取由 `WebChatRuntime` 管理；Harness 只看到受限的 Provider
结果。详见[网页聊天档案](../integrations/browser-runtime.md#网页聊天档案web-chat)。

## 验证边界

`backend/tests/test_agent_portability.py` 使用只实现稳定内核的 Runtime，验证：

- 可在不实现 DSH optional API 的情况下构造；
- 未支持能力明确拒绝；
- registry 对未知 ID fail closed；
- Core 状态与会话 RPC 不依赖 DSH Provider bridge。

Playwright 另验证不支持的控制不会出现在 Agent 页面。

## H01 版本化身份契约

本节是已实现的窄接口。纯值对象在独立SDK `quality_routing.harness`；不依赖Core、数据库、Tauri或具体适配器。受管DSH接线见下节；活动任务跨Harness迁移不在H01交付范围。

- `RuntimeBinding`，schema `runtime-binding/v1`：harness_id、instance_id（稳定实例）、distribution_id（发行组合）、adapter_version、execution_mode（managed/external/api）、identity_evidence_ref；可选launch_id和launch_evidence_ref必须同时存在或同时为空。引用只用受限标识，不传profile绝对路径、端点或凭据。
- `ExternalSessionRef`，schema `external-session-ref/v1`：harness_id、instance_id、原session_id和可选turn_id。原引用保持内容，支持中文和空格，长度至512且拒绝控制字符；不能把整个会话历史放入此对象。
- `to_dict/from_dict`版本化序列化，未知版本、额外字段、非法标识和缺少必需字段拒绝。对象冻结；序列化结果为独立副本。
- `session_key`为(harness_id, instance_id, session_id)元组，不拼接字符串；同名外部会话不能跨实例冲突。`belongs_to(binding)`只比较来源身份，已知重启不改变历史归属，**不是恢复授权**。
- `matches_attempt(current)`要求完整绑定相等且launch_id已知；启动未知时连自身也不匹配，不能用空值判定可续跑。发行组合、启动实例、适配版本或Harness变动均不匹配。

宿主接线：`AgentRuntimeRegistry.create(..., binding=None)`可注入经宿主核验的RuntimeBinding；`AgentRuntime.bind_runtime(binding)`拒绝Harness不一致及非幂等改绑。更换绑定必须构造新适配器，原对象及原引用保持。`runtime_binding()`无网络返回对象或None；`external_session_ref(session_id, turn_id=None)`缺身份时抛AgentRuntimeError。

只读RPC `agent.runtime.binding`返回schema `runtime-binding-status/v1`、available、binding及reason（host-bound/runtime-identity-unverified/runtime-instance-changed）。请求正文不能安装绑定。受管DSH由私有引导注入并重检；外部DSH/ZCode无宿主证据时available=false。运行身份失效时保留历史binding但available=false，不静默更换来源。

### 受管DSH身份与生命周期

Tauri启动受管DSH后先查协议健康，再调用无网络的Windows观察器。观察器用GetExtendedTcpTable取精确127.0.0.1监听PID，拒绝通配监听及歧义；Toolhelp祖先链必须连接到原生自有Child，沿链持有进程句柄并检查创建时间、存活、重复快照及PID复用。Core PID不代替DSH PID，cmd包装器不冒充实际监听者。

profile身份来自实际目录的卷/文件标识，逐级拒绝reparse/link和特殊路径；不写入profile，不复制登录数据。启动身份来自root/listener PID及各自创建时间。版本化managed-runtime-evidence/v1回执只由受管装配产生，经同一私有stdin第二帧传Core；不能从HTTP、环境中的自报JSON或模型参数安装。Core在构造适配器和注册sink前重检路径、启动与配置一致性，再绑定不可变RuntimeBinding。

H02已用实际冻结发行描述替换legacy-unlocked。描述位于`dsh-release/`：`channel.json`给出默认发行，`releases/<id>/release.json`给出DSH版本与npm包摘要、安装布局、协议事实、冻结锁文件摘要、安装策略、自有插件内容摘要和验证结论；`releases/<id>/pnpm-lock.yaml`是冻结锁文件。`distribution_id`由该描述推导（版本、包摘要、锁文件摘要、插件内容摘要的规范化摘要），与安装路径无关，并写入RuntimeBinding.distribution_id；adapter_version取该发行声明的协议族。启动器、安装辅助脚本、Tauri和Core读取同一份描述，不再各自保存版本号，回归由`backend/tests/test_dsh_release.py`和`tools/test_dsh_release.ps1`固定。

安装证据单独观察、不参与启动身份等值判断：`frozen-lockfile-verified`表示`node_modules/.pnpm/lock.yaml`与声明逐字节一致，`mismatch`表示该树不是由冻结解析产生，`declared-unverified`表示没有可对照的安装锁文件。日用0.1.1-rc.2安装树建于锁定之前，实测与冻结解析存在大量传递依赖差异（例如`@aws-sdk/*`），因此当前为`mismatch`；是否按冻结组合重装日用树属于单独的可见切换，本轮不动。

候选0.1.5-rc.1已按同一描述准备并在隔离目录验证：冻结锁文件逐字节一致，自有插件可组合并启动。但它把`/api`改成"进程token换签名cookie"鉴权，方法名由`<namespace>.<method>`改为`<namespace>/<method>`，payload要求`{"args": ...}`，`host.describe`、`mcp.list`、`agent.*`、`session.history`、`session.models`、`session.export`、`session.retry`、`POST /api/respond`及`/api/events.mux`均已移除或改名，旧协议包`@deepseek-ai/dsh-host-apiproxy`只发布到0.1.1-rc.2。因此该发行标记为`blocked`：描述保留、阻断原因完整记录，任何受管启动都拒绝，不能被当作已完成升级。

DSH报价、HTTP请求和事件归一化前均运行同一身份guard。Core重启时由原生保存的回执重新核验，DSH未重启就保持原launch。DSH重启后原Core适配器报告runtime-instance-changed并拒绝新调用/事件，旧任务不自动换绑；原生保存新回执供下一次受管Core启动核验。H04后续提供有授权核对的显式接续，本轮不实现热迁移或自动重发。

启动器复用development.processes中的同一ManagedProcess/WindowsJob实现，保留ManagedTestProcess兼容别名。DSH命令在Job分配完成后才放行；原生自有Python包装器持有Job句柄，启动失败或包装器退出会回收cmd、node及Job内后代，避免只杀cmd留下服务。正常退出先用保存的回执及进程句柄停止已验证监听者，再回收自有包装器；失配时不根据端口杀陌生进程。没有新增第二套任务执行器。

限制：Windows快照不是跨检查与HTTP发送的原子事务；此机制防止常规端点误复用、重启/PID复用、错误来源及误杀，不宣称抵抗完全控制本机账户的对手或提供文件/网络沙箱。外部Harness仍需自己的可验证适配器，不按URL或健康状态自动提升信任。

### 其余H01中立数据对象

以下对象均在quality_routing.harness，使用严格/v1 schema、不可变字段和JSON往返；引用使用受限标识，正文、凭据及具体DSH对象不进入契约。

| 对象 | 固定字段与含义 |
| --- | --- |
| CapabilityEvidence | capability_id、status（supported/unsupported/unverified）、limitations、evidence_refs；来源真实性由宿主核验 |
| ModelInvocation | work_request_id、requirement_revision、operation_id、purpose、candidate_id、runtime_binding、input_ref、input_digest、limits_ref |
| InvocationReceipt | operation_id、runtime_binding、submission、result_ref、usage_ref、price_ref、resource_receipt_refs、evidence_refs；completed需结果引用，definitely-not-sent不能带结果，unknown不授权重试 |
| RecoveryAssessment | work_request_id、requirement_revision、runtime_binding、operation_ids、allowed_actions、evidence_refs、reason、unresolved_operation_ids；resume必须已知launch且有证据、无未决操作；这仍不是用户授权 |
| MergePreview | work_request_id、requirement_revision、preview_id、source_digest、changes_ref、verification_refs、runtime_binding；文件变更与验证结果通过内容引用关联 |

这些是H03/H04/H05必须复用的接口，未伪装成模型网关、恢复或合入运行时。后续在既有工作/内容存储保存引用，不新建另一套总账、任务库或会话引擎。

### 后续高难接线

1. H01已实现稳定profile和自有启动核验，H02已用单一冻结发行描述替换legacy-unlocked。外部端点无可信来源时保持未绑定。候选0.1.5-rc.1的协议迁移属于后续工作，不因描述存在而视为可用。
2. 只有可信装配能调用bind_runtime。值对象校验只证明结构正确，不证明引用回执真实存在，更不产生授权；生产装配须查询自己的证据存储并核验引用。
3. Agent旧准入已把宿主绑定纳入offer摘要、WorkService尝试快照及ExternalSessionRef，发送前重新读取核对；H03/H06把同一契约用于新增受控开发路径，不能另造身份语义。
4. 历史引用增加版本化来源，旧未知来源保持未知，不批量复制transcript。跨Harness接续另走预检，仅带目标、已验证成果和必要上下文，不复制消费授权/凭据。
5. H01上述窄数据对象已定义；H03–H05实现其生命周期和真实回执，不得把对象构造成功当授权或能力验证。不得在UI添加“相信此实例”开关绕过宿主证据核验。

普通模型只做状态展示：available=false显示“运行实例身份尚未核验”，不标服务离线、不自动重连、不猜测发行版本；不得改后端绑定条件。请求该RPC不触发模型/文件扫描/端点调用。

验收：新增身份后端3项及Agent专项55项共58通过；Agent全组150通过；SDK105通过（2项可选MCP跳过），仓库外全新venv取消PYTHONPATH并用-I执行同组测试通过，确认site-packages且无sumika_core导入。wheel位于D:/Caches/sumika-h01-harness-wheel，SHA256为329d7c6025b5d7c22f2b5158f2ce7f8a83c917dd13ca81a376f428df88bf64f2。非DSH最小fixture证明接口绑定行为，不冒称第二个生产Harness。此次无前端/Rust代码变化，未重复UI/原生验收。

构建说明：本机Python未装setuptools时，`pip wheel --no-build-isolation`会报Cannot import setuptools.build_meta；采用正常隔离构建安装声明构建依赖后通过，不需修改运行时依赖。

### Agent工作绑定与事件核对

`LegacyWorkAdmission(..., runtime_binding=...)`从宿主回调取得绑定，不使用报价或请求正文自报的runtime_binding。绑定完整序列化进入offer及既有binding_digest；WorkService在external和实际attempt中分别保存副本，不新增数据库。发送前重新计算offer摘要；绑定变化在任何尝试/预算预留前拒绝。已提供稳定身份但缺launch证据时也拒绝发送。无绑定旧准入保持原费用阻断规则，不因此声称获得身份保证。

Agent execution_key由[harness_id, instance_id, session_id]结构化编码后计算摘要，不包含launch_id：不同profile同名会话互不混淆，同profile重启仍受原未决请求单飞限制。新启动不会凭改变launch_id清空未知尝试。

Core注册事件sink时捕获当时绑定，回调不读取后来更改的默认Agent，也不从事件正文取得来源身份。`observe_agent_event(event, boundary, *, source_binding=None)`仅当会话、回合、工作绑定和实际尝试绑定全部一致且启动已知时处理结算。缺失、非法或不匹配的来源不改变费用和完成状态；即使正文携带正确绑定也不能替代宿主参数。更换适配器须注册新的sink，不能在旧sink上补写身份。

旧记录缺绑定时不自动补齐，不根据同名事件释放预留；继续显示原状态，等待H03/H04凭发送回执核对。这一改动不等于安全恢复，也不保证其他事件驱动路由入口已完成身份隔离。

生产受管DSH已按本页监听进程/包装器链核验并注入；host.describe健康、profile路径摘要及随机ID均不能代替实例证据。H02仍须提供冻结发行组合。普通模型只展示现有状态，不放宽这些条件。

验证入口：test_legacy_work_admission覆盖同名事件、不同Harness/profile/launch/发行组合、缺来源、伪造正文、旧记录、发送前变化与零预留；test_harness_binding覆盖事件sink保留原来源、后补绑定不倒灌。均为离线fixture，不代表DSH身份实测。

## 相关文档

- [DSH adapter](../integrations/dsh-agent.md)
- [Desktop shell](desktop-shell.md)
- [Protocol](protocol.md)
- [Workspace 与任务](tasks.md)
- [状态矩阵](../status-matrix.md)
