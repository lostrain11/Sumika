# 可信宿主确认

H01整合实现：可信调用者、有限原生动作、参数分支及实例绑定均已接线。整包验证状态以[当前执行记录](../current-execution.md)为准；以下早期阶段测试保留历史证据，不代替最终回归。

## H01 整合后的权限边界

`host_authorization.CONFIRMATION_METHODS`是有限方法集合，`requires_confirmation(method, params)`区分扩权和纯撤权。前端同名判断接收完整params，Rust只转发同一有限集合；三方一致性及Python/JavaScript分支一致性有测试。新请求仍绑定方法、完整参数摘要和本次Core发行者，不能通过approved、嵌套request.approved、字符串真值、伪造token或旧Core凭据取得调用者身份。

新增保护覆盖：模块实现/配置、插件批准/启动、工具执行、音视频权限及Provider调用、Provider配置/秘密保存及激活、Agent会话创建/预设/模型/工作区修改、内置Skill启用、快照恢复、浏览器档案/动作/诊断/下载释放、网页聊天许可、桌面自动化、福利配置/签到及交互刷新。完整动作以代码有限集合为准，不能新增任意RPC代理。原预算路径保持：角色/工作预算、Agent/Web准入不因持有原生身份而绕过既有目标、版本、质量或费用检查。

纯关闭分支仅接收规定字段：例如module.update仅module_id+enabled=false，音视频仅permission_id/permission+granted=false。混入config或实施变更仍要求可信宿主。原Agent Skill撤销四别名的既有可信约定保持；plugin.revoke/reject、停止/取消等不扩权动作仍沿用原规则。未批准tool.run只能到已有明确拒绝分支，不能靠配置require_approval=false执行。

内置浏览器attach/poll/complete/alive/bind_portal全部经main原生来源校验；桥token本身不再足以通过普通HTTP领取请求或伪造回执。这些是宿主来源认证，不是每次后台poll都询问用户。工作台可执行有限桥操作，陪伴及网页无此权限；凭据不下放模型。没有受管宿主时敏感操作明确不可用，不回退HTTP。

`agent.event.ingest`公共入口停用：无可信上下文返回-32041，即使内部可信测试上下文也返回-32042，不调用有状态normalize_event、交互跟踪或scheduler。真实DSH事件在适配器身份重检后进入注册时固定来源的sink。事件缺少来源或与已确认arm的trigger_binding不符，不消费请求、不写去重、不派发、不释放预算。

`replan`不再隐式写入或替换待触发请求；只有经准入的arm_turn建立挂起上下文。replan(false)仍可产生规划投影，但不改变待执行内容。Agent会话有reserved运行/未决尝试时，select_model、select_preset、model.policy.apply和provider.sync拒绝修改该会话；其他新会话的后续选择保持可用。

DSH实例核验、私有回执、重启失效与Job Object复用见[受管身份实现](agent-runtime.md#受管dsh身份与生命周期)。DSH插件目前不能用公开bridge_tools(register=true)自行声称可信来源；H03受限运行凭据接入前该注册路径明确不可用，不能为了H02加载成功恢复自报信任。

此边界不等于整个Core的账户级HTTP鉴权或OS安全沙箱；不保护已控制当前OS账户并能执行任意Python/原生代码的攻击者。源码合入仍由H05实现，安全续跑与自动实例接续由H04实现，不把类型定义或停止旧重放当作已完成这些能力。

## 实际调用链

### 旧Agent重试的安全停用

`agent.session.retry`现先检查可信调用者（普通RPC为-32041），可信调用仍返回-32042：无法证明原回合未发送且无未决副作用。拒绝发生在legacy_work报价/派发、预算预留、checkpoint与适配器重放之前。正文submission_state、possibly_sent、revision不能提供恢复证据，重复确认也不放行。

只读`agent.session.retry.preflight`接收sessionId或session_id，返回`schema_version=legacy-retry-assessment/v1`、原session_id、`status=blocked`、`retry_allowed=false`、`reason=retry-evidence-unavailable`、`submission=unverified`、`side_effects=unverified`、`allowed_actions=[inspect]`、`requires_confirmation=false`。它不查询历史、不调用模型、不证明会话存在，只声明当前产品不支持安全重放。界面先预检，阻断时保留会话并提示检查，不弹批准框、不提交retry。

原`_rpc`内部旧实现及DSH retry_prompt暂保留，不删除历史能力代码；内部测试仅验证其checkpoint顺序/回执过滤，不作为生产安全重试证据。受管生产入口只能经过公开rpc，适配器对象不可暴露给不可信插件。此次不是全进程/OS沙箱，也不保护有权直接调用内部Python对象的代码。

重新开放的前置条件：H03持久操作ID、原运行绑定及逐调用发送回执；H04原会话核对、工具副作用/checkpoint配对；版本化RecoveryAssessment绑定具体操作而非最近回合。只有宿主证据证明未发送、无未决副作用且原授权仍有效，才能接续；未知保留只读核对。不能简单把retry_allowed改为true、信任模型字段或把failed/cancelled终态当not-sent。原重放文本/模态限制和预算仍须保留，跨Harness/候选切换需新预检。本轮不引入一个可伪造的“安全重试”布尔开关。

`CoreApplication.rpc(method, params, *, caller=None)`检查由传输层提供的CallerContext。普通HTTP `/rpc`不构造可信上下文，即使正文包含approved、trusted、actor，或请求头携带宿主凭据也不能批准。

`HostAuthorization`位于独立模块，不依赖CoreApplication、存储、模型或Tauri。CallerContext绑定方法、请求摘要和本次Core发行者身份；正文不能构造发行者身份。内部服务方法仍由可信装配调用，不能把对象引用交给不可信插件。

本轮限制方法：work.authorization.confirm、quality.task.confirm、quality.task.budget、schedule.create/update/pause、agent.approval.respond、agent.question.respond、agent.mcp.configuration.apply、workspace.worktree.create、workspace.commit、workspace.restore、agent.skills.approve/revoke及agent.skill.approve/revoke。merge.apply/undo已保留后端拒绝边界，原生尚不放行尚未实现的合入动作。

Skill注册四个别名均先过可信调用者校验，之后保留精确candidate ID及原文件摘要校验。批准仅登记元数据，不安装/执行Skill、不授予付费权限；撤销保留源文件，运行中会话不被无声改写。真实临时Skill的HTTP测试覆盖两个别名的批准/撤销，前端测试为原生确认夹具并保留发现所得元数据，不冒称真实DSH加载。

旧workspace写入口现在先校验可信调用者，再执行原有preview token、精确分支/目标/checkpoint及源状态检查。未认证调用在文件服务之前拒绝，即使正文附approved和完整预览字段，或普通RPC带宿主请求头也不例外。可信调用仍不能省略预览。原恢复前归档、提交不推送、worktree不自动包含未提交变更等业务语义保持。此增量不是H05受控合入/撤销或Windows并发写保护完成。

MCP配置apply复用既有适配器预览与备份，不新建配置服务。可信传输之外仍要求approved、精确preset及有效previewToken；凭据值包含在本次请求摘要中，确认后篡改值会拒绝。真实凭据只经现有受控宿主流程，不记录到审计事件；夹具验证变更凭据、HTTP伪造拒绝及可信调用，不能冒称真实MCP挂载完成。

Agent问答可携带Plan Review批准，因此整个回答入口都要求可信宿主，不依据调用者声称的普通问题类别放行。原先的交互查找、精确选项和checkpoint先于批准的业务顺序保持；未认证请求在任何checkpoint或运行时回复前拒绝。普通浏览器仍可查看问题，但必须在原生工作台回答。取消入口未因此授予执行权限。

请求摘要入口：`host.confirmation.digest`接收method/params，仅返回规范JSON的SHA256，无授权或模型调用。摘要绑定本次提交参数，不是H05成果diff预览摘要，不能以此声称已完成源码审查。

原生`host_confirm`只接受上述限定方法、对象参数和摘要；调用现有main WebView标签、窗口与可信origin检查。陪伴、内置远程网页及任意RPC转发不获权限。前端helper先复制参数，避免用户编辑影响正在确认的请求；陪伴转回工作台，普通浏览器提示使用原生工作台，失败不回退HTTP、不重发。

原生通过`POST /internal/host-confirm/v1`提交method/params/digest，认证材料位于X-Sumika-Host请求头。Core校验认证与摘要后生成只适用于此动作的CallerContext，再进入原业务版本/上限检查。此局部接口没有新增总账，不将确认等同模型执行。

## 引导与生命周期

Core首次启动及supervisor重启现在使用挑战握手，不再以`/api/health`中的ok判定自有进程就绪。宿主每次探测生成32字节随机nonce，POST `/internal/host-identity/v1`，正文只有nonce、不带宿主密钥。Core返回schema_version=`sumika-core-identity/v1`、nonce、实际os.getpid()及proof；不接受客户端指定pid或额外字段。proof为HMAC-SHA256，key是stdin收到的64位小写hex字符串的ASCII字节，消息是`sumika-core-identity/v1\n{nonce}\n{pid}`的ASCII字节（无末尾换行）。

Rust用hmac验证签名，核对挑战与自有Child PID，成功后再次检查Child仍存活；旧nonce、错误PID、旧密钥及只有ok的服务均拒绝。握手连接/发送有超时，响应读取总时限750ms、上限8192字节，启动循环沿用15秒限制；失败只清理自有child，不终止占端口的第三方服务。无引导材料的外部Core明确拒绝证明请求。证明接口只能生成固定域的身份签名，不能调用确认或执行任意RPC。

此证明表示响应方持有本次私有引导材料并报告预期PID，不证明代码未被篡改、不能对抗控制当前账户或中继真实Core的攻击者。握手本身不发放消费授权，不验证DSH profile、发行组合或DSH启动身份，不替代后续每次调用与任务绑定检查。现有确认传输仍沿用本机宿主密钥通道；本次没有宣称整个HTTP服务具备会话级双向认证。

Tauri用系统随机源生成32字节随机值，经私有stdin发送`sumika-host/v1`JSON帧。Python仅在显式`--host-bootstrap-stdin`启动参数下读取，不从环境变量、URL、数据库或普通配置加载认证材料。读取有1024字符上限，非法/缺失帧拒绝启动。

认证材料只在原生/Core内存与该本机确认传输中使用，不交给前端、模型工具或DSH环境。每次Core重启重新生成；已有Issuer上下文不能用于新Core。管道写入失败回收本次自有子进程。认证边界不声称防御已完全控制当前操作系统账户的攻击者。

外部手动启动Core没有宿主材料时，仍能读取诊断和使用既有非敏感功能，但上述敏感确认及整合保护的方法均拒绝。不是整个Core已变成只读服务，也不允许以外部模式绕过消费授权。

## 测试与回执

Core身份增量：后端受影响46项通过（含身份模块14项），Rust39项通过；custom-protocol独立输出构建通过。跨语言固定HMAC向量、错误挑战/PID/密钥、无引导、额外字段、普通健康假服务且请求不泄密均覆盖。最新原生证据`D:/Caches/sumika-h01-native/1789101525937/result.json`：双窗口、全部限定确认、退出及真实自有Core中断重启通过；smoke核对目标父PID和bootstrap参数后才结束测试子进程，新PID/新proof及确认通道恢复验证通过。未调用DSH、登录或模型。新增Rust hmac 0.12.1及其subtle 2.6.1锁定依赖，无其他版本升级；前端/SDK未改，不重复其全量验收。

retry安全停用：后端专项93、前端83、Rust37及E2E阻断1项通过，生产与隔离custom-protocol构建通过。`D:/Caches/sumika-h01-native/1789097886343/result.json`验证普通HTTP拒绝、主窗口可信确认后仍阻断、陪伴拒绝及完整窗口生命周期。未运行真实模型、DSH重放或写用户仓库；未重跑未变SDK及全量E2E。保留原内部测试并明确更名为legacy internal，新增公共HTTP零执行测试，不能用内部测试冒称安全续跑完成。

Skill增量：后端专项65、前端83、Rust37及Skill E2E1项通过；生产与隔离custom-protocol构建通过。原生`D:/Caches/sumika-h01-native/1789097206967/result.json`覆盖四个别名的HTTP拒绝、主窗口精确候选校验、陪伴拒绝和完整双窗口退出。首次UI夹具只返回state/id丢失name，修为返回发现所得完整元数据后通过，没有修改生产显示逻辑或降低断言。

workspace增量：后端`test_host_authorization test_agent_server test_workspace_runtime`共79项通过，前端83、Rust37、受影响E2E4项通过；生产与隔离custom-protocol构建通过。原生`D:/Caches/sumika-h01-native/1789096362685/result.json`验证三个写入口的普通HTTP拒绝、主窗口业务预览拒绝、陪伴越权拒绝及完整双窗口退出。原生请求故意缺少预览，不实际写仓库；文件行为由临时仓库单测覆盖。首次误写test_workspace模块名导致ImportError，改用实际test_workspace_runtime后通过，未修改产品修复该命令错误。

上传恢复点`2822e28`后的MCP增量：后端专项63、前端83、Rust37及受影响E2E3项通过；生产与隔离原生构建通过；`D:/Caches/sumika-h01-native/1789096029685/result.json`验证真实主窗口MCP通道、保留业务参数拒绝、普通HTTP及陪伴越权拒绝。不调用MCP运行时；真实MCP加载/安装仍属后续发行组合验证。

续做最终验证：后端全量1257、专项91、前端83、Rust37通过；Playwright全量86通过，生产及隔离custom-protocol构建通过。最新原生证据`D:/Caches/sumika-h01-native/1789095677009/result.json`覆盖新增Plan Review HTTP与陪伴拒绝及完整双窗口退出，截图已查。下列1255项及旧smoke路径为前一阶段证据，不替代最新结果。

- 后端全量1255项通过：`artifacts/h01-backend.log`。后续增加Agent权限拒绝、非法Unicode认证及最新边界专项35项通过。
- Rust37项通过，debug handler及custom-protocol handler均注册host_confirm；Cargo只声明已在锁文件中的getrandom 0.3，未升级DSH或其他锁定包。
- 前端83项单测通过，新增副本绑定、普通浏览器拒绝、陪伴转交、未知不重发、任意方法拒绝；生产构建通过。
- 隔离custom-protocol二进制为`src-tauri/target/native-smoke/debug/sumika-desktop.exe`，没有覆盖日用debug二进制或配置。
- 真实原生smoke通过：`D:/Caches/sumika-h01-native/1789094697537/result.json`；含私有引导、普通HTTP伪造拒绝、陪伴拒绝、任意RPC拒绝、两个真实窗口、同一Core、各模式及干净退出。不存在请求返回业务“未找到”证明已通过宿主认证，不伪称真实付费授权或模型调用成功。
- 最新工作台截图已检查。真实多屏热插拔仍未验收。旧smoke通用textarea选择器因增加测试命令输入而失效，已改为name=goal，未修改产品布局。
- Playwright确认夹具明确使用native-fixture，普通HTTP出现确认调用会失败；不将夹具当真实原生证据。最终运行结果以执行记录为准。

## 下一子包与普通模型交接

以下表格记录H01早期审计时的缺口；本页顶部整合边界及Agent身份文档描述现行实现。H02–H06按其各自验收继续，不能把H01完成当作开发执行、费用恢复或安全合入完成。

### 已定位的下一批入口

以下为代码审计发现及逐项进度；未完成项不能交给普通模型自行决定权限语义：

| 入口 | 当前缺口 | 固定处理及验收 |
| --- | --- | --- |
| workspace.worktree.create / workspace.commit / workspace.restore | 可信传输已补齐；H05安全合入和并发保护未实现 | 原预览/精确对象/源状态校验保留；HTTP伪造零写入、可信夹具业务校验及真实窗口边界通过；不能用此结果宣称H05完成 |
| agent.session.retry | 已接可信确认并安全停用；缺少原操作未发送/副作用证据，尚不能安全续跑 | 公共入口在报价/派发前阻断，预检只允许inspect；H03/H04按上文证据契约重开。内部旧DSH重放不能直接暴露；route测试不代替Agent验证 |
| agent.skills.approve/revoke及单数别名 | 本次四别名可信注册确认已补齐，真实DSH加载仍另验 | 临时Skill真实HTTP批准/撤销及文件保留通过；原生权限与精确候选条件通过；不把注册批准当执行或付费授权 |
| agent.mcp.configuration.apply | 本次已补可信传输，真实新发行组合挂载未验 | 保留当前预览、脱敏和配置备份；HTTP拒绝/摘要篡改/可信回执及原生窗口边界通过；H02另验真实隔离DSH，不扩大当前完成结论 |
| browser、plugin、audio.permission.set、vision.permission.set等 | 已按顶部有限集合与条件分支接入可信宿主 | 无来源扩权零业务调用；有限纯撤权保持；未扩大为任意RPC代理 |
| Core及DSH受管启动 | Core用引导HMAC；DSH另用监听进程祖先及创建时间核验 | 两种身份分别验证；真实隔离DSH/Core重启均有证据；H02另提供冻结发行组合 |

下一批每个入口都必须同步后端拒绝测试、原生限定动作、最小UI接线及显式native fixture；不能为了旧E2E通过恢复普通HTTP授权。现有参数摘要仍不等于服务器报价/预览版本绑定，后续需按业务对象再次校验。

H02发行组合、H03逐调用网关/账本、H04恢复、H05预览绑定及合入、H06自改仍未实现。不得提前切换日用DSH。

普通模型只处理已存在helper的提示和状态展示：

1. 输入使用原work/quality字段，通过统一transportRpc进入confirmThroughHost；不直调HTTP确认，不获取宿主凭据。
2. native确认失败时保留原请求ID、版本和用户输入；未知只显示查询状态，不自动再确认或再提交。
3. 陪伴转交保持原角色请求，用户在工作台确认后继续原请求，不能创建第二份消费授权。
4. 非原生页面明确显示限制，不增加浏览器信任开关。工作台测试用隔离native-fixture，后端安全测试不能启用HTTP信任参数。
5. UI验收覆盖确认前零执行、失败保留输入、取消、手动编辑后新摘要、陪伴转交和键盘操作。范围只限view/host/helper测试，不更改后端权限白名单。
6. 回退需要保留后端拒绝规则；不能通过恢复普通HTTP确认修复UI。提交证据路径、实际命令、未验收限制并更新当前记录。
