# Desktop 生态复用与独立能力接线

用户已批准本对话《Sumika 架构与后续工作调整》实施。保留自有四页设计、陪伴业务与 Harness 可替换边界，不修改 DSH 上游。暂停视觉精修。现有未提交工作保留。

## 顺序与验收

1. 写入口统一保护、准确实例停止、空白用户首启。
2. 角色会话与交接持久化，稳定消息ID，未知请求不重放。
3. 独立 Profile 验证官方 root/sidebar/main/rightbar/overlay 组合，成功后迁移四页，保留旧入口回退。
4. 可信项目交接与结果回传、定时执行桥、BrowserSkill 三站点实际授权登录链路。
5. 真审批/取消/断线恢复、安全模式、备份恢复、安装包与诊断。更新最后做。

每包区分 implemented/tested/live verified；社区源码核对不等于运行验收。当前总状态 in_progress，未切换日用 Profile。

参考固定源码：anywhere-labs 5510cb1203838f2d55f9bbd52cdcfaae1cad5eac；bruc3van 1306cfcf54f9711522dec70d879163c0a76b84bf；vibeinging d41b891be58ae4e7befa9cb236eab74ae1d8d9cc；dataelement aca970834bce88d2ec14ec278b368f6f0d168d0a。采用组合/恢复设计，不复制网络开放、运行时自动切换和上游补丁。

## 已有资产

直接复用 `ui/management.py` 的 Host/Origin/CSRF 校验，将旧 API 接入同一校验；改造现有前端 fetch 和测试客户端。角色存储、执行契约、启动器、工作台组件后续在原实现上改造，不另建并行系统。

## 当前实现与证据

- 写保护：所有新旧写 API 使用同一 Host/Origin/CSRF 校验，浏览器只允许准确 Bridge 源站。托盘保留启动实例令牌，退出时不向新端口占用者索取令牌。
- 首启：个人设置不存在时创建禁用生成的默认设置，工作台和设置可访问；已有设置不覆盖。
- 生命周期：移除按端口清理未知进程；Profile 使用 Windows 文件锁及 PID 创建身份记录；停止必须确认子进程退出才释放所有权。HTTP 写操作、角色生成落盘及退出共享锁，关闭后排队写操作返回 503；停止失败返回 unknown，服务不假报退出。
- 角色持久化：`extensions/roles/conversations.py` 独立 SQLite 保存稳定消息 ID、原文、结果状态和交接草稿。未知请求不重放；设置重建对象仍读取已完成上下文。交接原文读取宿主保存记录，不信任客户端替换。dismiss 只代表关闭草稿，不代表工作台接收或任务完成。
- 原生布局：`tools/verify_native_layout.py` / `.mjs` 在 `.sumika-next/` 隔离 Profile 组合官方 sidebar/main/rightbar/overlay；四页切换后原生草稿保留，无 iframe。其他页面仍为验证占位，尚未进入产品。

本轮验证：

1. `python -B -m unittest tests_next.test_ui_server tests_next.test_role_conversations tests_next.test_ui_workbench tests_next.test_runtime_ownership`：30 项通过，含退出等待聊天落盘、关闭后拒绝写入、失败保持可查询。
2. `python -B tools/verify_desktop_bridge.py`：真实独立进程启动/退出两次通过；重启保留历史和草稿，旧实例令牌返回 403。证据 `.sumika-next/desktop-bridge-23b46bcdbdc949118ee632f8daaf81db/report.json`。零模型请求、未触及个人数据。
3. 上轮原生布局隔离证据：`.sumika-next/layout-probe-4526fd0a1f1b47e08d5e5d5ea760288c/result.json`、`browser.json`、`layout.png`；本轮未重复运行，不作为完整产品验收。
4. `python -B tools/verify_workbench_ownership.py`：真实受管 DSH 两代启动、竞争写者拒绝、确认退出及释放锁全部通过，始终使用隔离 Profile。证据 `.sumika-next/ownership-probe-819cf2525d314141a11fc04dac6acb8d/report.json`；零模型请求。

## 未完成与已知限制

- 日用服务尚未重启：旧进程聊天仍在内存中，必须先保全再切换；当前静态文件与旧后端可能不匹配，不能将页面预览作为新版后端已部署证据。
- 原生布局还需迁入真实四页、准确源站通信及附件/工具详情/轨迹/用量/审批验收，再替代现有 iframe；不能删除旧入口。
- 可信项目解析、按需上下文、任务接收状态和完成证据回传仍待接线。
- 会话 scope 暂含角色目录绝对路径，移动资源的稳定身份迁移尚未完成。
- Profile 租约已由共享宿主层供 UI/CLI 使用；异常 starting 记录的显式恢复流程仍待完成。
- 定时页面仍需执行桥，BrowserSkill 三站真实会话绑定、备份/恢复/安装/诊断未完成。
- 角色包还原测试曾发生 Windows `PermissionError`（`roles.py` 发布目录 rename）；不是已修复事实，先前 rename 0/40 不能证明可靠，根因仍待查。

总状态保持 in_progress。现有大量未提交改动保留，不提交、不推送、不覆盖日用 Profile。

## 后续计划调整：提示词优化

用户最新要求实际模型接通延后（F-003），当前仅实现WorkBuddy式输入工具栏星光入口，明确标注尚未接通。撤下英文模板改写，不冒充模型优化；后续再评测可选本地指令模型，保留原文/差异/确认且不自动发送、不改变权限或费用路由。窄屏仅基础适配，未扩大为移动端重构。

## 继续实施：共享实例所有权

现成资产 `ui/runtime_ownership.py` 的文件锁/创建身份逻辑改造后复用，移至 `sumika_next/runtime_ownership.py`；旧模块只保留兼容导入，不维护第二套锁。`daily.run` 在创建 DSH 适配器之前获取同一租约，启动后绑定真实进程，确认关闭才释放。扩展关闭报错也要执行进程清理；关闭失败或进程仍运行保留围栏。UI 停止超时转换为 unknown，保留受管实例。

验证：19项 `test_daily test_runtime_ownership test_ui_workbench` 通过；真实两轮 DSH 隔离验收通过，UI和CLI竞争写者均被拒绝，原进程仍运行，关闭后租约释放。证据 `.sumika-next/ownership-probe-54ec971bdb794c7788f9b8f00f68feec/report.json`，零模型请求。

日用只读检查：默认角色 `ui-role-chat` 历史为空，草稿接口仍返回HTTP错误，说明旧后端尚未更新；无法据此断言其他角色/会话没有内存历史。未停止日用实例，未迁移个人数据。下一步继续解决旧服务数据导出及安全切换，再迁入原生四页。

## 旧聊天保全与迁移准备

复用既有 `roomSessionId`（room-角色ID）和旧历史只读接口，发现默认ui-role-chat为空不代表活动室为空。`tools/preserve_legacy_chat.py` 枚举当前名册对应会话及旧默认会话，私密快照写入用户数据目录backups，SHA-256复读校验后，仅导入有明确当前角色归属的历史。当前安和昴2条消息导入1轮，其余已知会话为空。个人目录实际解析到D盘用户数据位置；不上传原文、不停止进程。

`Conversations.import_legacy` 使用稳定摘要ID幂等导入；先完整校验，再事务写入；无回复的用户消息保留unknown，不进入模型历史；目标已有新版聊天则拒绝混入以防乱序。4项会话测试通过，包括幂等、未知状态、非法快照原子拒绝和新历史冲突。备份标识legacy-chat-ab88f25968a647a4b56f0c1db1ff52f3，摘要ef190b467cc049abf736d9d2e81ee9a77e52a06d19c8eaf298b20a20768cd4a5。

限制：旧接口不能枚举任意自定义session，备份只覆盖已知UI会话，不能称完整进程快照；旧进程继续运行后可能新增聊天，切换前必须再核对和保全。本轮没有重启日用服务、没有宣称新后端已上线。原生布局迁入仍未完成。

## 原生布局通信层隔离验收

既有 `ui/management.py` 授权逻辑改造后复用。`WorkbenchController.browser_binding` 仅返回持有租约、进程仍运行且Trust.MANAGED的准确回环origin及instance ID。Bridge允许自身源站和这一受管源站；不开放任意localhost。原生页面写令牌以Bridge随机秘密和实例ID派生，实例更换即失效，不能使用壳层通用令牌代替。写请求取得生命周期锁后再次授权，避免排队期间实例变化。CORS和业务授权使用同一源站判断；业务审批不因此豁免。

验证：`test_ui_server test_ui_workbench test_ui_management` 共35项运行，最初管理测试替身缺少新方法报错；补齐替身后单独重跑9项管理测试全部通过，另26项在原组合运行通过。HTTP新增用例验证准确源站、错误令牌、同端口实例更换令牌失效、实例停止拒绝访问。

`tools/verify_native_layout.py` 改用真实受管控制器和独立Bridge，私有设置/数据库/角色默认生成均隔离；浏览器实测跨源预检、无令牌403、实例令牌200、原生启动浮层可用、四页切换草稿保留均通过。证据 `.sumika-next/layout-probe-a4c0db9a73e24d7fb8c0951f5eb19f25/`；0页面错误、0外部模型请求，日用Profile未改动。

这仅完成原生通信前置；活动室/能力/设置仍为探针占位，尚未迁入产品。下一步复用既有业务页面接入根布局，不新增平行数据源或第二套导航；真实审批、附件、详情仍按原计划验收。

## 用户角色更新与页面共享请求层

按用户要求重新导入 `D:/Code/安和昴角色卡项目/交付/安和昴_ST_V2.json` 最新交付（未修改源项目）。工具 `tools/update_user_role_card.py` 复用现有import_card验证与角色存储，先全量校验备份，再更新卡片、派生persona/worldbook和校验表，保留ID、用户显示名、模型等资源绑定。个人备份标识role-card-c03f6406e39444e0b961d19aafb50193；原文和备份仅存用户目录。源/目标SHA256均b2d7578633c5181072aaf162f048f0a8e101e8f8f0a104dc86b91699f797bf4e；实时API角色verified=ok、complete=true、model_3d=true，两条旧聊天仍在。未重置记忆、未调用模型、未叠加语言政策。

继续原生迁移：新增 `ui/app/bridge-client.js`，现有bind/management/handoff模块复用它，API基址取可信模块自身来源，不从URL参数或模型输出取；拒绝外部目标，写请求缺令牌时获取当前实例令牌，不自动重试写请求、不跟随重定向。原管理与业务逻辑保留。静态脚本在既有准确源站授权后提供对应CORS头，未放开任意本地端口。

验证：现有页面20项管理浏览器检查通过。第一次原生探针失败原因是静态模块响应缺CORS头（layout-probe-28a291e5cc1e4734a080b94739de827e）；补齐后真实动态导入和共享请求层写入通过，外部目标被拒绝，切页草稿保留。成功证据 `.sumika-next/layout-probe-dcfc0fc5c00a42689b7f501a9ea1d69e`，0页面错误、0模型调用。该结果仍不代表四页DOM已迁移：下一步页面挂载/卸载与角色资源URL适配，保持原生组件状态和原设计，不另写平行业务实现。

## 日用后端切换完成

旧 Bridge PID26988/命令行/监听归属核验；调用它的workbench/stop后DSH PID21100确认退出。再次保全已知UI会话（legacy-chat-634a6943208249b5ae3798059845969a），安和昴2条无变化，幂等导入0新增。仅已知会话覆盖，不将旧接口无法枚举的自定义session称为完整备份。

首次Copy-Item递归Profile跟随profiles/node_modules依赖链接，已中断；诊断纠正：阻塞来自备份复制，不是停止API。改用不跟随链接且跳过node_modules的文件遍历，个人备份backend-data-830dc5652a5844dca33a758a0046d27b含21个Profile文件，逐个SHA256校验，另存角色设置。随后确认旧Bridge身份和工作台已停止，停止旧Bridge，启动新Bridge PID18292及受管DSH PID3360（5175）。用户env.ps1在启动进程中加载，无凭据输出。没有自动重放会话/任务或模型调用。

实测日用历史API返回2条稳定ID消息及supports_clear=true；20项管理界面回归通过，角色作用域清空HTTP隔离测试通过，3→6→8历史/取消/确认一次清空浏览器夹具通过。真实用户聊天没有被清空。清空后刷新待交接草稿，避免继续提示已清来源。

失败备份backend-switch-fe98f622d7a14d14885ecda06d14812f清理被自动审批审核以blocked by policy拒绝，保留且未绕过。该目录位于个人备份区，含本轮不必要的依赖副本；正式校验备份是backend-data标识，不混淆。后续备份必须跳过node_modules与reparse点。

日用旧后端阻碍已解除；原生四页仍未迁入，当前工作台仍使用原入口。下一步继续实际页面挂载与资源适配。

## 活动室历史角色绑定补强

分页和非分页历史读取现在都校验当前 role_id；角色切换竞态不会读取旧角色会话。清空接口继续要求 role_id 与 room-角色ID 同时匹配。新增2项HTTP隔离测试通过，整体最近回归41项通过；浏览器管理20项通过。

## 原生布局回归验收

近期日用切换、角色更新、活动室历史改动后，重新运行 `tools/verify_native_layout.py`：启动浮层、根布局插槽、受管源站令牌、共享页面请求层、四页草稿保留全部通过。证据 `.sumika-next/layout-probe-f8a3d5e4ad634e2bbad0d764bd019a45`，无页面错误、无模型调用。`tools/verify_room_history.mjs` 的3条/加载更早/清空确认夹具也通过。原生探针仍是隔离验证，产品工作台暂未从iframe迁入。

## 工作台加载失败反馈

复用现有 `bindWorkbench` iframe 回退入口，增加受管 DSH frame 的load/error状态：加载期间显示轻量提示，页面加载错误时提示“工作台加载失败，点击重试”，只重新加载当前已验证URL，不重新启动进程、不重放任务、不改变草稿。成功load后移除提示。20项管理浏览器回归通过，未新增第二个入口。

## 2026-09-15 可信项目交接闭环后端

- 实现 `extensions/roles/handoff.py` 的显式项目解析、宿主可信上下文和 host-verified 结果回执。
- `Conversations` 增加交接状态事件表与幂等状态机：pending → received → completed/unknown/failed；未知状态不自动重放。
- 管理接口增加 receive/result 操作；拒绝无 host-verified provenance 的客户端回执。
- 验证：`python -B -m unittest tests_next.test_role_conversations -q`（6 项通过）；`sumika_next.cli check`、`handoff` 通过。
- 未完成：工作台 UI 接收状态显示、真实 Git/验收证据读取和四页原生迁入。

## 2026-09-15 交接状态显示

工作台交接草稿接收后保留 `received` 状态并显示“交接已接收/项目上下文已由宿主核验”，禁用重复接收；仍需工作模型重新规划，不自动发送。


## BrowserSkill 会话绑定核验与纠正

现成资产：extensions/desktop/browser_skill.py、browser_consultation_bridge.py、ui/management.py 和已有三站授权；改造复用，不另建凭据库。复用 project-continuity 记录执行边界。用户已决定保留 iframe，原生迁入暂缓。此前只看页面和统计会话数不等于完成咨询链路。

实现并实测三站绑定身份与 bound_bridge.observe，只读全部 observed；绑定前个人授权文件已做字节校验备份，未改变 read/send 权限，未保存网页正文或登录凭据。新增绑定、身份复用、移窗/跨站、离线、撤权测试，25 项相关测试通过。前端绑定恢复、实际提交与响应持久化仍待做；没有调用发送。后续只有真实提交前需确认具体测试消息，不再重复索要已获准的只读/开窗授权。


## 2026-09-17T06:30:31.840684+00:00 三站显式重新绑定

用户明确允许重新启动并绑定。启动前session list为空；新建一个受管会话并打开三站，复用bind_session及bound_bridge.observe逐站验证，全部ready/observed。个人授权记录先备份并逐字节校验，旧read/send权限未改变，未发送消息，未保存页面正文。详细身份及时间在个人browser-binding-verification.json中。ready仅说明绑定与读取链路，不证明登录或提交验收；第2项整体仍未完成。后续继续提交/响应链路与前端恢复验收。


## 咨询提交持久化边界

复用BrowserConsultationBridge及已有SQLite持久化模式；原ConsultationBrowser仅进程内requests，无法保证重启后不重放，因此新增独立consultation_journal并接入宿主专用submit（未暴露通用HTTP点击）。提交前落UNKNOWN，ID绑定站点/原文摘要/实例/窗口/标签/选择器；并发只有一个调用者可dispatch，重复ID无浏览器副作用。回执仅标submitted，不等于回答完成。正文不写日志。23项相关测试通过。扩大到管理回归共32项时出现已有角色导入rename WinError5，31通过1错误；未将整组报告为通过。

尚未真实发送。站点selector核对、已有草稿保护、浏览器内原子origin检查、响应关联和完成判定仍未完成；当前CLI前后检查不能消除导航竞态，不作为端到端安全完成证据。下一步先补这些前置，再请求对三站具体测试原文的发送确认。


## 提交前草稿及来源保护

复用BrowserSkill evaluate接口，将origin核对和草稿写入/发送点击放在同一同步页面调用中；JSON传参，不执行网页返回的代码。已有非空草稿不覆盖，发送前必须与批准原文完全相同；拒绝多输入框、多按钮、不可用按钮。失效、超时继续UNKNOWN且不重发。20项Python测试通过；tools/verify_consultation_guard.mjs使用当前Codex自带Playwright及真实Edge离线拦截夹具通过，零外部请求，覆盖textarea/contenteditable、已有草稿、编辑竞态、错误来源、禁用按钮及单次点击。Python环境没有Playwright，改用已有Node包，无安装下载。仍未真实提交；实际站点selectors、响应关联/完成判定及产品接线未验收，不能宣称三站咨询完成。


## 三站输入适配核对与发送许可待确认

通过只读DOM读取核对三个受管页面，新增consultation_sites.py固定站点选择器，未提交；GPT发送按钮需有草稿后实际核验，当前空白态为语音按钮，不能混用。Kimi空白P/BR导致innerText为换行，guard现仅对无文本且只有P/BR/DIV占位结构判空，不清除用户草稿。真实Edge夹具通过；此前20项Python用例通过。准备三站各一次指定SUMIKA_OK测试，请求新发送许可；未上传文件或个人内容，不自动重试，提交及响应端到端尚未完成。


## 三站真实测试发送结果

用户批准每站发送一次指定SUMIKA_OK测试。DeepSeek/GPT经submit_text提交，各自assistant区域唯一回答为SUMIKA_OK、草稿清空。Kimi首次返回UNKNOWN并保留草稿；用户提供截图指向发送按钮，核对首页/唯一启用控件/精确原文后，仅点击既有草稿一次（个人one-shot记录防重放），进入新chat并观察到SUMIKA_OK、草稿清空。首次未完成原因仍未证明，不归因于选择器错误或已修复。详细证据在个人browser-send-test-evidence.json；初始UNKNOWN不覆写。三站真实连通已验证，但自动响应关联/完成判定、Kimi首次路径可靠性与产品接线仍需完成，不标整体完成。


## 提交阶段与延迟就绪处理

新增SQLite consultation_steps记录checking/filling/waiting_ready/clicking/acknowledged/interrupted，不保存页面/提示词原文。填入后只读轮询按钮就绪（3秒轮询窗口，单次CLI自有超时仍适用），只填一次、点击最多一次；拒绝跨站或草稿变化。21项目标测试及真实Edge离线夹具通过，包括先禁用后启用的按钮只读轮询及单次提交。没有新增真实消息。Kimi首次失败无阶段证据，不能据本轮补强倒推原因为时序；真实修复验收尚未完成。用户对指定三站测试发送的确认已收到且已执行，不再记录为待确认。下一步响应关联/完成证据与产品状态消费。


## 网页咨询定位与绑定状态恢复

用户明确：网页咨询主要用于主 Agent 完成计划或复杂成果后的交叉验证，寻找遗漏、反例与潜在问题。网页模型不主导规划，其输出仅为不可信审查建议，由主 Agent 核验和决定是否采纳；不得自动改写已批准计划、扩大授权、改变模型路由或派发任务。

现成资产：复用 ui/app/management.js 的网页咨询授权窗口、ui/management.py 的状态与绑定接口；设计参照 ui/prototype-d/index.html 约1051行连接与权限。均为改造后使用，无平行入口。当前现场三站 binding_status 均为 stale；没有重新发送已消耗授权的测试消息。

已接通状态显示、显式标签选择（包括只有一项时）、精确 origin/Agent scope/window 过滤、授权变更后刷新；未知 inventory 不展示确定数量。tools/verify_browser_authorization_ui.mjs 用真实 Edge 隔离夹具验证上述路径，零真实授权写入、零咨询发送。未重启日用后端。

下一步仍是提交前响应基线、用户消息与新回答关联、站点可靠完成标记和持久化恢复，然后将审查结果接回主 Agent。现有三站人工实测不得倒补为自动响应完成证据；当前仅绑定管理子项通过，不标 BrowserSkill 整体完成。


## 响应关联与重启恢复实现

现成资产改造：consultation_journal.py、browser_consultation_bridge.py、consultation_sites.py 继续承担唯一提交链路；新增 consultation_response.py 与固定 consultation_snapshot.js 负责响应契约与站点只读采集，不引入第二套浏览器或授权库。

已实现：提交前把站点、绑定身份、原文hash及历史消息有序hash基线与UNKNOWN在同一SQLite事务落盘；历史正文不落盘。响应要求原历史前缀未变、本次精确用户消息与其后唯一assistant、站点完成控件及非生成状态。首页到新线程首次关联后固定线程；提交guard同时限制基线页面路径。旧答案、额外用户消息、历史编辑、截断、读失败、切会话均unknown。完成正文仅保存在个人journal，带外部审查建议边界。collect_response按持久化身份恢复只读观察，不自动导航/重绑/重发；历史记录无基线不能倒补。cancel只取消本地请求，明确不保证远端停止，重启不重发。

三站重新绑定已沿用此前明确授权，个人授权文件备份并字节核对，权限不变。三站只读采集均读取到消息与完成控件；DeepSeek后台历史页最初未渲染消息，激活标签后出现，现增加history_not_loaded拒绝以防空基线。未发送新咨询；现有历史仅验证采集，不能证明新请求关联已通过。站点DOM完成控件仍需下一轮真实生成过程验收，不能把离线夹具当作站点流式保证。

验证：31项Python测试通过；verify_consultation_snapshot.mjs三站Edge离线夹具通过（控件、生成中、推理区排除、历史未加载）；verify_consultation_guard.mjs通过并新增同站线程变化拒绝；均零外部消息发送。后端日用进程未重启。剩余：完整产品/Agent审查入口与明确批准、真实新请求关联/中断/恢复验收、附件草稿保护；再提出具体测试消息发送确认。第2项整体in_progress。


## 主 Agent 原生交叉审查工具及真实审批取消

复用DSH tools/pre-execute ask协议与原生审批服务，不另建审批UI。新增review_dsh.mjs及review_service.py；模型只能提供site/prompt，approved及会话归属由宿主生成。白名单工作目录+主工作preset，角色和子Agent拒绝；查询/收集/取消限同工作会话，返回建议不授予权限。配置显式enabled，关闭不注册。独立核心继续不依赖DSH。

34项Python测试、4项Node测试通过。tools/verify_web_review_dsh.py用已有ModelFixture和Dsh适配器，在独立Profile真实验证approval/asked→approval/decided(cancelled)→tool/result(ABORTED_BEFORE_DISPATCH)，证明取消发生在工具体执行前。证据在.sumika-next/web-review-native-ee58179d2a794dcfadbd3e74b0beab8c；外部模型和网页消息0，日用配置未改。测试脚本已将实际确认的取消结果加入断言；对本次现有events复验通过。

下一步：附件/复杂草稿保护、原生批准后的隔离执行和响应回传验收；准备具体跨站新测试文本再请求用户确认，之后再部署日用插件。当前工具实现与拒绝路径已验证，不等于第2项整体完成。


## 复杂草稿保护与下一轮验收待确认

consultation_guard在inspect/fill/ready/submit前拒绝非空file input，以及contenteditable中的图片、链接、不可编辑节点、mention/attachment/data-type节点；保留原草稿，不上传附件。真实Edge离线夹具验证通过。第三方已上传附件预览卡不保证均覆盖，仍需具体站点核验，不宣称全形态支持。

当前三站绑定只读复核均PermissionError（未自行重放旧请求）；后续沿用开窗与绑定授权恢复。已准备.sumika-next/web-review-acceptance/pending.json：三站各一次中文交叉审查，人工构造三个缺陷（超时重发、稳定文本等于完成、网页建议自动改计划）；不含项目/角色/个人资料。此次内容为新消息，等待用户明确确认后才能发送，旧SUMIKA_OK授权不能复用。核心发送/恢复代码已实现，原生批准后的真实响应链路与日用安装仍未验收。


## 三站交叉审查回读与日用安装核验（接续）

本节更新前文待确认状态：用户已批准的新三站各一条测试全部发送、完成并经原生工具回读；隔离重启不重发，外部付费API调用为0。原始回答仅在个人/忽略运行数据中，证据 `.sumika-next/web-review-acceptance/live/report.json`。网页意见仍仅供主Agent核验，不改写批准计划。

复用现成资产：review_dsh.mjs、BrowserSkill适配与个人journal直接使用；Profile安装通过独立review_install.py改造现有patch，持有ProfileLease，保留无关配置且字节核对备份；无上游修改、无新UI入口。安装收据 `.sumika-next/web-review-acceptance/install.json`。日用工作台已启动，embed_ready=true，settings/describe实际成功；尚未证明日用会话发现工具，不能等同第2项整体完成。

37项Python定向回归、4项Node适配测试通过。修复Windows中文CLI的UTF8解码、Lexical延迟提交导致同步filled=false、GPT临时WEB线程过早固定；同一浏览器标签按持久化lane阻止未知请求并发新发。测试原生prompt requestId须唯一，否则DSH去重并不执行。上述修复保留精确草稿核对和最多一次点击，不自动重试未知操作。

用户要求已执行：Kimi清除旧草稿并使用快速；GPT开启思考并选择左侧回复1。本次Kimi依赖一次受控续提交，GPT原测试发送时未开思考，不能夸大相应验收范围。待核验日用工具发现、受管浏览器恢复入口、站点上传后附件预览形态；本次三条消息和更早SUMIKA_OK授权均已用完，不重发。


## 日用连续请求与显式恢复入口

改造已有 review_dsh.mjs：提交ID加入原生 step/start 的 turn/step 与callId，避免后续轮次复用callId误拒绝；缺少执行步骤则不发送。旧请求owner前缀保持不变，历史查询不受影响。5项Node测试通过；隔离原生审批取消再次通过，证据 `.sumika-next/web-review-native-9278ffcbf79f408cbbb785c6f6d87493/report.json`，没有新网页消息。

设计参照 ui/prototype-d/index.html 的设置/连接与权限区域，复用现有网页咨询授权对话框；恢复动作属于已批准BrowserSkill恢复接线，不新增导航。增加显式打开受管窗口、选择现有受管会话并打开固定站点；不自动绑定、不授予read/send、不发送。会话browser/window身份必须与界面快照匹配；结果未知需先刷新，后端不重试。BrowserSkill原有启动/绑定及授权库继续单一来源。13项Python测试和真实Edge隔离UI夹具通过。本轮尚未重载日用后端，页面新增动作暂不可视为日用可用。

待做：安全加载日用、工具发现、恢复真实验收；Kimi全自动新请求路径和已上传附件预览检测仍有原限制。没有扩大对外发送授权。


## 日用恢复真实验收

原生 session/control 实核6个日用会话jobs与queue均为空后，使用受保护生命周期接口正常关闭并启动Bridge/DSH，未按端口杀进程。工作台running/嵌入均就绪。本轮恢复入口与原生步骤请求ID修复已加载。

现场BrowserSkill旧会话列表为空、三站stale，故通过日用 /api/manage/browsers/start 新建受管窗口，再分别open固定站点、bind明确标签。授权文件先做字节核验备份，不更改read/send。Kimi首次导航还未落定，检查未匹配即停止；只刷新既有页后绑定，没有再次创建。三站最终ready、登录状态仍保持unknown；Kimi可见快速模式。证据 `.sumika-next/web-review-acceptance/daily-recovery.json`，本轮网页新消息0。

仍须日用工具发现核验；Kimi修复后的全自动新请求及GPT思考模式测试需新消息授权，具体两条（两站同文各一次）草案 `.sumika-next/web-review-acceptance/final-send-proposal.json`。此前三站测试额度全部已用，不复用授权、不重放。


## 第2项最终验收：网页交叉审查

用户「运行」批准第二轮Kimi快速/GPT思考各一条固定无私密测试，现均已用完。Kimi自动完成检查、填写、就绪等待、单次点击与提交确认；随后出现临时线程 `/chat/pd5dc799-76da-4b6e-bfa2-71b54d3f9f33` 再转正式UUID，修复仅识别这一明确临时格式，既有历史或正式线程变化仍拒绝。对同一请求只读回读成功，无人工续提交。GPT发送前实核思考按钮aria-pressed=true，提交后页面空正文；激活并重载同一线程后读到已保存回答，没有重发。

| 完成条件 | 当前证据 |
|---|---|
| 三站真实授权、绑定、发送及准确回传 | live/report.json：DeepSeek完成；final-live/report.json：Kimi/GPT完成且native_readback=true |
| 原生审批与角色/子Agent隔离 | review_dsh测试5项；真实取消证据web-review-native-9278ffcbf79f408cbbb785c6f6d87493，ABORTED_BEFORE_DISPATCH |
| 未知不重放、取消及重启恢复 | journal/response测试；final-live/report.json restart_no_replay=true；取消明确仅本地 |
| 日用实际注册 | daily-registration.json registered=true；插件注册后从真实ctx.tools.get校验再输出启动证据 |
| 日用失联恢复 | daily-recovery.json：通过现有管理接口start/open/bind，三站ready；Edge界面夹具验证显式选择 |
| Profile安全安装与开关 | test_review_install四项；备份字节核验、幂等、保留其他行、写入失败恢复；disabled不注册工具 |
| 中立边界与隐私 | 独立Python执行/存储；DSH仅薄工具适配；回答为建议、审批仍原生；原始回答仅个人/忽略目录 |

上述相对证据文件位于 `.sumika-next/web-review-acceptance/`，取消证据位于 `.sumika-next/`。43项Python定向测试和5项Node测试通过，外部付费API调用0。日用注册核验最初缺日志，不是插件配置被覆盖；确认实际patch仍有插件，改为注册断言后stdout输出，受管空闲重启后得到证据。

边界：只支持三站固定文本咨询；已上传附件预览未全形态验收，带附件草稿不列为支持范围。DOM变更/验证码/未知状态失败关闭；不承诺所有站点异常自动恢复。日用注册及恢复真实验证，发送执行在真实隔离DSH中由本地确定性模型驱动，不宣称日用付费模型实际调用。网页意见不能主导计划或授予权限。第2项完成，不将整个P5或下一项标完成。


## 网页咨询默认关闭总开关

按用户「补完」增加既有授权窗口内的启用开关。设计参考 ui/prototype-d/index.html 的设置/连接与权限，直接改造 ui/app/management.js openBrowsers，无新导航。权威状态仅个人 browser-authorizations.json 顶层enabled，缺失或非true都关闭（包含旧授权文件）；不由已有read/send推断启用。DSH插件enabled仍只管理工具注册，用户开关由独立BrowserSkill宿主逐操作重读，不需重启DSH才生效。

关闭不清除sites、binding或SQLite历史，保留本地查询/取消；阻止新读取、打开、绑定、发送和会话启动。已经提交至网站的生成不承诺远端停止。开启本身不授予站点read/send，也不代替原生逐次发送审批。26项Python定向测试、真实Edge授权对话框开关夹具通过。备份个人授权文件后将日用开关设为false，核验空闲后受管重启Bridge；日用GET均disabled，POST启动被拒绝，既有站点记录保留。


## 第3项：记忆实际接线开始

日用settings实核memory_provider=embedded、auto_extract=false；内置本地记忆已有实现并用于角色上下文，关闭的是普通聊天自动提炼。semantic为已有可选实现，未据旧评测自动切换。复用RoleSession/ExtractionGate和持久化会话，不另建引擎。修复自动提炼来源ID使用进程随机hash：日用传入Conversations稳定turn:user，独立调用使用唯一UUID。31项现有定向测试通过，新增稳定来源/重建去重测试；本次不改用户记忆、不启用自动提炼，日用后端尚未重载这项修复。后续验证召回、重启、隔离与提议层剩余缺口。


记忆接线续验：修复不启用compiled card时RoleSession缺role_context、姓名本地化要求compiled card、RoleChat无selection异常三个相关缺口。tests_next/test_memory_chat_context.py在真实RoleChat provider边界验证事实注入、用户隔离和遗忘，并用新Python进程验证SQLite恢复/项目隔离；连同role_service/auto_extraction共12项通过，无真实模型调用、无个人数据写入。发现semantic当前日用Python无fastembed，独立memory-env存在，且open_session未传embedding_cache；该分支不能算接通，继续复用既有运行时修复。日用仍embedded，自动提炼仍关闭，本轮后端修改尚未重载。


语义记忆日用调用接线：复用现有memory-env、embedding-models及SemanticMemory，不安装新依赖。新增embedding_runtime/embedding_worker只执行离线embedding批次，关闭下载与遥测，不传API凭据；每次检索至多一个隐藏子进程并设置60秒超时，无重试/替换provider。RoleChat.open_session传入已安装路径；设置页选择semantic前执行合成文本依赖预检，失败不保存新配置。

15项定向测试通过；真实日用解释器通过独立环境调用本地512维模型，verify_memory_chat_runtime.py验证中文改述召回进入角色system参考、事实更新/重开恢复、用户隔离，耗时2.86秒，云端请求0。证据.sumika-next/memory-chat-runtime-6e9afca723d54b7285848aea60236893/report.json。另测设置预检失败保持原文件。当前策略每次非空检索启动进程，性能边界明确，不宣称常驻低延迟。个人provider仍embedded，auto_extract仍false；新接线尚未重载日用。第3项继续进行。


## 第3项：长期记忆开关与提取边界

已有资产：复用 extensions/memory 的存储/提议/门槛，extensions/roles 的上下文链路；设计稿 ui/prototype-d/index.html 设置的数据与存储区及 ui/app/management.js 既有表单改造使用，不新增导航。memory.enabled 控制聊天检索、注入和自动写入，显式管理保留。当前个人 embedded / auto_extract=false 不变。

Bridge 已正常受管重载，工作台启动返回成功。真实 Edge 等待动态导航 data-section=data 后点击，长期记忆开关可见并开启、自动提取关闭；此前等待失败是点击了初始化前的静态导航，不能作为已通过证据。42 项记忆/聊天/提取/embedding 定向测试通过。随后收紧规则提取的整句匹配和独立爱好键，拒绝非有限置信度；代码测试通过，最新规则尚未再次重载日用进程（自动提取仍关闭）。没有个人记忆写入或外部模型请求。

未完成：模型提议层、复杂纠正和长程提取质量评测；不将第3项或P6整体标完成。


## 第3项：可选模型提议接线

复用 MemoryWriter/memory_proposals 隔离表及现有角色管理窗口，新增默认关闭的 memory.model_proposals。角色回复同一次生成附带候选，宿主绑定消息ID并核对quote逐字属于用户原话；门槛不等于语义真实性。候选在管理窗口展示原话，经确认后以 user-confirmed 来源写入；无模型fact_key覆盖权限。忽略/确认持久化、重复事件不重提，导出恢复保留状态及原话。两个元数据标记顺序均测试，未额外调用模型修复输出。

55项相关Python测试与真实Edge合成数据确认/忽略流程通过。组合套件中的角色包rename出现既有WinError5，未将该组合标全绿。日用受管重载和工作台恢复完成，个人provider embedded、auto_extract=false、model_proposals=false不变；未改个人记忆。

真实本地模型测试：当前模型库已无旧MiniCPM5，不下载或自动fallback；显式选择已安装Qwen3 8B，在独立11439端口、自有子进程及合成角色运行。验收结果待回读，不提前标完成。


### 第3项完成条件审计（最终模型复验进行中）

| 完成条件 | 当前证据 |
|---|---|
| 角色真实上下文收到记忆，关闭后不检索/不注入/不加载语义模型 | test_memory_chat_context，包含卡编译开/关、用户/项目隔离及新Python进程恢复 |
| 规则提取开关默认关闭、来源ID稳定、偏好不互相覆盖 | test_auto_extraction、test_extraction_policy |
| 可选模型提议默认关闭、同次生成、无额外修复调用 | test_model_memory_proposals；settings API读回false |
| 提议不参与检索，确认/忽略、作用域、事件幂等和备份恢复 | test_model_memory_proposals、ManagementTests.test_model_proposals_require_confirmation_and_preserve_scope |
| 前端实际显示并调用确认/忽略 | verify_memory_proposals_ui.mjs，真实Edge运行交付UI+合成接口，未写个人数据 |
| 真实本地模型生成、确认后召回 | memory-model-live-c20e52cb968d44909f21bf20d060e94d/report.json positive_proposal_generated=true/confirmed_recalled=true |
| 确认状态跨进程持久化 | .sumika-next/memory-proposal-restart.json，新Python进程读取accepted=1 |
| 语义provider现有环境真实可用，更新/遗忘/隔离/恢复 | .sumika-next/memory-final-consistency.json 13/13；memory-final-quality.json 语义13/14、关键词8/14 |
| 日用加载且保持个人选择 | Bridge正常受管重载、工作台running，GET embedded/enabled=true/auto_extract=false/model_proposals=false |

56项相关自动化测试通过。仍保留广组合测试中独立角色包rename WinError5记录，未将其归为本包已修复。

真实模型局限：首次随机设置正例未生成可用候选，第二次诊断超时，第三次temperature=0/context=2048正例成功但含一条笼统候选“用户饮用频率”；不能把模型输出当成准确事实。用户确认是实际边界，不以置信度代替。语义检索14例中一个含混过敏问法漏召回，记忆不是无遗漏事实库。不自动切换个人provider，未来仍做更大规模方案选优；本次功能接线验收不代表AML榜单或完整P6。

验收工具清理修复：Windows terminate父Ollama不回收llama-server；按本次日志命令、模型hash、端口、父PID和创建时间核验后清理3个自有残留，再读进程为空。工具改为在Popen确认存活时按自有进程树退出，不按端口终止进程。

最终复验78cf6ebe显示双标记输出不稳定：漏正例、假设被提候选（未入事实库）。据此改用单一JSON附注承载intent和memories，宿主过滤明显假设/引用。57项相关测试通过，新真实验收运行中，目标仍未标完成。


### 第3项最终结果：功能接线完成

最终代码单一结构化附注，真实模型证据 `.sumika-next/memory-model-live-d88a6ca86a544290adf283573a004f41/report.json`：正例候选生成、确认后召回、两个假设/引用反例无候选，均true。原始输出只含合成对话并留在忽略目录；零云端请求、零个人记忆变更。测试进程树退出后CIM确认无Ollama/llama-server残留。此前失败与超时证据保留，不掩盖模型不稳定性。

最终57项相关Python测试通过，日用Bridge再次空闲受管重载；真实Edge重新验证开关可见、默认关闭、原话展示、确认/忽略正确调用。原个人embedded/enabled=true/auto_extract=false/model_proposals=false不变。第3项要求的已安装能力接通、开关、模型提议、确认/隔离/持久化、实际运行验证均已核对；完成本项，不将整个P6、AML或未来所有provider选优标为完成。

边界仍保留：候选质量由选用角色模型决定，解析失败或不输出附注时不重发；同次生成会增加少量输出token。模型提议必须用户确认。语义检索仍有单例漏召回，关键词检索更有限。当前未替用户切换语义检索或开启任何自动提取。


## 能力配置归属与提示（R-117 / R-118 / R-119）

按用户当前设计方向，复用ui/prototype-d/index.html卡片/详情与表单、bind.js能力投影和management.js既有配置保存：语音识别/朗读合并“语音交互”，麦克风改为详情中独立授权；保留ASR/TTS/麦克风模块独立开关。长期记忆配置归入能力详情，设置数据页仅保留通用用量。提示支持悬停、键盘焦点、点击和Escape；设计稿占位“未接入”标记从已接通数据分区移除。

原registry仅enabled，不是采集许可。新增麦克风options.user_authorized，缺失默认不授权；管理API要求明确确认与revision，执行服务在调用capture_audio前拒绝无授权。原生每次approved校验仍保留。读取与展示不修改任何个人配置、不启动录音。旧enable=true不自动迁移成授权。

文档R-119明确这批布局是设计参考，未来前端模型可以采用更合理替代，不作为必须照搬的规范；功能、用户数据和真实授权边界仍保留。用户原话记入requirements.json，整理见approved-plan.md和ui-design-coverage.md。

验证：10项Python定向测试通过；真实Edge合成接口验证唯一卡片、配置保存、麦克风独立授权、设备选择、提示可聚焦访问；原记忆提议确认/忽略UI测试迁移后通过。1440/1024截图检查修复新详情插入导致的旧panel索引错位；子权限变更不丢未保存表单。证据.sumika-next/evidence/capability-settings/。未做实际录音；权限测试在硬件访问前验证拒绝。日用Bridge已加载后端修改，个人settings/模块授权/记忆均未改动。


## 模型库归集完成（R-121）

复用现有Ollama manifests/blobs与GGUF、嵌入/语音目录，不重下载、不混合改写runtime库。9个明确目录迁至E:/Models；逐文件初始SHA256、复制后目标SHA256和原文件复核，检查目录未变后移除精确源目录并建立junction。完整清单 E:/Models/migration-records/20260917-181427/manifest.json。无运行中的Ollama迁移；用户OLLAMA_MODELS改为E:/Models/Ollama/main，旧目录兼容。{"roots": 9, "files": 160, "GiB": 48.921, "freed_C_GiB": 2.908, "freed_D_GiB": 3.238}。

verify_model_library.py 从3个新目录实际启动隔离Ollama只读列举8模型，与manifest列表完全匹配，零生成，进程树退出；verify_memory_chat_runtime.py实测旧路径指向的嵌入模型完成中文召回、更新、隔离，2.89秒。最后再次核验9个junction、文件数、大小。C盘与D盘已释放原权重空间；不去重、未删除有价值的评测记录或验收副本。常见模型/缓存/下载目录已扫描，未声称扫描所有游戏、软件包内部权重。软件包内OCR模型保留在包内。

本次完成物理模型迁移，三个用途分栏、用户指定扫描目录及辅助模型实际接通仍待做，不能据迁移称产品全部完成。


## 共享模型库UI首批接线（部分完成）

复用设计稿ui/prototype-d/index.html设置表单与management.js模型连接区；用户已明确授权本地模型分栏。新增独立library.py只读有界扫描，路径配置复用既有settings原子保存/revision。最多16目录、2万文件、10秒，跳过嵌套junction/symlink，不调用模型或下载。Ollama manifest核对blob大小并标登记/不完整，原始GGUF等仅发现，不保证兼容。UI允许保存目录、手动/可选启动扫描、填入角色模型名称（不自动启用）。

4项定向测试通过；真实E:/Models扫描18项无错误；真实Edge设置页显示18项。空目录配置初始化为E:/Models、auto_scan=false，其他用户模型配置未变。Bridge空闲重载。仍未完成三用途子分栏、辅助模型配置及推理、工作原生模型绑定；不将扫描列表当完整方案。

## 恢复主计划：角色目录与聊天作用域

旧待办与当前现场对齐：四页迁入按用户后续决定暂缓；BrowserSkill三站与记忆基础接线已有后续验收，不重做。MiniCPM仅调研，产品接入暂停。桌面能力剩余真实验收、安全发行与迁移仍未整体完成。

本包复用 Conversations SQLite、Bridge scope 和 RoleSession；改造后使用，不增加第二套会话库或UI入口。新增 role_scope_bindings，以明确用户/项目/目录登记原scope作为稳定不透明身份；移动需显式 relocate_scope(expected_scope)，事务中拒绝已有目标绑定或目标历史（含清空存档）。旧位置retired后拒绝访问，防旧配置继续写另一份记录。未知请求、消息ID及handoff不重写、不重放。长期记忆本来按role_id隔离，不随目录改动。

38项会话/迁移/HTTP/管理测试通过，包含真实临时目录移动后数据库重开、原历史和草稿恢复、跨用户与项目隔离、重复迁移幂等、旧身份及目标冲突拒绝。

状态为partial：这是会话身份基础，不是完整搬家工具。后续必须补离线迁移编排：备份、验证角色资源、绑定新位置、发布settings、失败恢复。API docstring明确调用方负责这些步骤。未迁移个人数据、未重启日用Bridge，当前日用还未加载此包。

## 角色资源迁移编排：隔离验收完成

复用现成角色校验器、Conversations、settings保存和Bridge写入锁。实现 extensions/roles/relocation.py、受保护管理接口及 tools/relocate_user_role.py，无新增UI。相较上轮“离线”设想，实际通过单个Bridge宿主锁串行执行，以免聊天与迁移交错；离线直接调用底层函数不负责阻止其他进程写入。

流程：确认当前用户导入角色和settings revision → 核验源资源/拒绝链接和重叠目录 → 原样设置备份及SQLite backup+integrity_check → 复制到新目录并SHA256对比 → 持久化prepared → 绑定不变scope → 保存新路径 → completed。原角色目录保留，不删除。通过作用域登记投影名册，后续切换角色或重复迁移仍定位新目录。

中断后普通HTTP写请求与聊天作用域访问失败关闭，GET可查状态；显式resume校验目标和配置未被其他操作更改后继续，或rollback恢复原配置/原绑定并保留副本。已completed不允许rollback，防覆盖迁移后聊天。无自动重试/模型请求/任务重放。

验收：43项迁移/历史/HTTP/管理回归通过；后增加真实隔离HTTP测试，6项迁移专项全部通过。涵盖无令牌403、中断后409、显式恢复、名册新路径、二次迁移、备份、旧/新历史不合并、配置与资源变更拒绝。

修复已确认Windows问题：sqlite3.Connection上下文只处理事务，不关闭连接。备份连接改用contextlib.closing，防备份文件占用。此前四个失败测试临时目录的清理命令被自动审批以blocked by policy拒绝，未绕过，目录保留于.sumika-next。

命令（运行最新版Bridge后）：
- `python -B tools/relocate_user_role.py`：只读状态。
- `python -B tools/relocate_user_role.py --target D:/ChosenParent/role --apply`：确认迁移当前用户角色；目标父目录需存在，目标本身不能存在。
- `python -B tools/relocate_user_role.py --resume RECEIPT_ID --apply`：继续未完成切换。
- `python -B tools/relocate_user_role.py --rollback RECEIPT_ID --apply`：回退未完成切换。

未重启日用Bridge，未移动个人角色。安装包、全应用备份恢复与诊断仍未因此完成。

## 角色迁移接口日用部署

用户明确要求删除先批准。四个已核实的失败测试目录通过批准后精确删除，并核验不存在，无其他删除。沙箱初始化失败，操作均经require_escalated批准执行。

空闲检查后经保护接口平稳停止Bridge，复用隐藏启动器恢复Bridge与工作台。重载前后settings、roles、活动室当前角色历史、待交接草稿的SHA256一致。迁移状态接口返回无待处理迁移；未移动个人角色或发送模型请求。证据：role-relocation-deployment-evidence.json。
