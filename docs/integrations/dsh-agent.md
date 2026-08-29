# DSH Agent 集成

Sumika 当前采用 DSH-first，但 DSH 只是 [Agent Runtime](../architecture/agent-runtime.md)
的生产 adapter，不是 Core 的基类。后端通过 `AgentRuntimeRegistry` 构造
`sumika_core.agent.DSHAgentRuntime` 访问固定版本的 DSH Web API，并把
`session / turn / tool / approval / question / error` 事件映射到稳定的
`AgentRuntime` 边界。DSH 未运行时，Agent 页面显示“未连接”，不会生成 Fake
回复，也不会自动改写全局 DSH 配置。

当前固定基线：`0.1.1-rc.2`、commit
`b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`，默认地址
`http://127.0.0.1:3080`。`SUMIKA_AGENT_RUNTIME=dsh` 是默认选择。可以用
`SUMIKA_AGENT_ENDPOINT`（兼容 `SUMIKA_DSH_ENDPOINT`）指向受管实例，用
`SUMIKA_AGENT_PROFILE_DIR`（兼容 `SUMIKA_DSH_PROFILE_DIR`）指定隔离 profile；
Tauri 仍只在 `SUMIKA_AGENT_AUTOSTART=1` 且存在
`SUMIKA_AGENT_EXECUTABLE` 时启动子进程；Windows 的 `run-desktop.ps1` 会先复用
已通过健康检查的外部端点，否则自动发现固定安装目录中已经存在且版本匹配的
DSH，再为本次启动设置这两个变量。现有 `SUMIKA_DSH_AUTOSTART` /
`SUMIKA_DSH_EXECUTABLE` 继续兼容。launcher 会把
`.sumika-desktop/dsh-profile` 作为子进程 `DSH_HOME`。Sumika 不会写入用户全局
`DSH_HOME`，启动流程也不会安装、升级或下载 DSH。`SUMIKA_DSH_ENABLED=0` 可关闭
适配器。

当前 npm CLI tarball 的 SHA-256 为
`47ec05f45ada5ab87779ae18a90456b5ebff5421dc0ff5c179677d65e1c16057`；该值也
记录在 Evolution Knowledge Registry，用于后续固定版本复核。

Windows 上可显式运行 `tools/setup-dsh.ps1` 安装固定 CLI。默认安装目录为
`D:\Tools\DeepSeekHarness\0.1.1-rc.2`，脚本使用 pnpm、跳过安装脚本并验证
CLI 版本；它不会修改 PATH 或全局 DSH。npm 生成的 `.cmd` 启动器由 Tauri
通过 `cmd.exe` 调用，命令格式为 `dsh --profile web --no-open`。

受管 DSH 的 stdout/stderr 位于 `.sumika-desktop/logs/dsh.log`；桌面退出时只
停止由本次 Sumika 实例创建的子进程。外部已运行的 DSH 不会被停止或重启。
启动、健康检查、退避重启和退出清理由通用 `AgentLaunchConfig` 监督器完成；DSH
adapter 只登记自己的 CLI 参数、环境变量和 `host.describe` 探针。

适配器按固定版本的真实协议发送 `client-request`：`session.create` 使用
`workspaceId`/`cwd`，返回的 `sessionId` 会被保存；`session.prompt` 使用
`{ sessionId, mode: "queue" | "steer", content }`，而不是自定义的模式字段。
`session.history`、`session.cancel`、按会话作用域的 `skill.list`、
`subagent.list` 以及 DSH command plane 的 `commands/list`、
`commands/execute` 已接入。命令请求使用 DSH 规定的
`{ args: { agentId, line, images } }` 载荷；Plan 的 `/plan [message]` 和
`/plan off` 通过该命令面执行，不会作为普通用户消息写入模型历史。若运行时没有
挂载 command plane，Sumika 会明确拒绝 Plan/执行切换，并且不会继续发送原始目标。
DSH 的 `mcp.list` 不在该固定 Web API 的 RPC 表中，因此 UI 会明确显示“由 DSH
tool catalog 提供，暂无独立 MCP 列表 RPC”，不会伪造可用的 MCP 目录。

Agent 页的 `agent.mcp.inventory` 是另一条只读边界。它检查受管 profile 中
`@deepseek-ai/dsh-mcp-client` 的包版本，并从用户选中 Session 最近 32 组消息对应的
DSH 历史里筛选公开名称符合 `mcp__<server>__<tool>` 的工具事件。返回值只包含 server
命名空间、公开工具名、状态和事件序号；命令、URL、环境变量、请求头、工具参数和结果
不会跨越 Core 边界。卡片显示“已观察”只证明该工具曾出现在这段会话历史中，不表示
MCP server 当前在线；尚未调用过时显示“尚未观察”，也不等同于插件未安装。

MCP 配置通过独立的 `mcp-configuration` capability 接入。固定版没有 composition
写入 RPC，因此 Sumika 只在受管 profile 的 `trust=user` Preset 中维护带版本标记的
`dsh-mcp-client` 行；系统 Preset、`cordis.patch.yml` 和用户全局 DSH 保持只读。UI 先调用
`agent.mcp.configuration.preview`，用户明确批准后才原子写入，并立即创建空白 Session
执行 mount validation。原文会先复制到受管 profile 的私有备份目录；写入、挂载或验证
会话归档失败时逐字恢复，检测到并发修改时拒绝覆盖。

受管配置支持 `stdio` 和 `streamable-http`，并可为每条连接登记一个受保护凭据目标。
`stdio` 将密钥映射到经过校验的目标环境变量；HTTP 将密钥映射到安全的鉴权请求头，
可带非敏感前缀，例如 `Bearer `。密钥值只写入 Windows Credential Manager。Preset
只保存版本化元数据和固定 DSH loader 表达式 `!!js process.env...`，不保存值、凭据引用
或可执行的任意 JavaScript。Sumika 重新生成并逐字验证受管行，手工篡改表达式、目标或
元数据会使读取和启动绑定 fail-closed。

新增、替换、轮换或移除密钥会要求重启。首次保存或轮换时，连接自动保持关闭；Tauri
通过版本化 NUL 私有协议一次读取当前 Provider 与 MCP 密钥，只把值注入受管 DSH 子进程
环境，并把已加载的非敏感环境名集合传给 Core。重启后用户再次编辑连接即可启用。
禁用连接缺少密钥不会阻止桌面启动；启用连接缺少密钥会明确失败。`env`、任意 headers、
URL 内嵌凭据和参数中的密钥仍被拒绝。启用行固定使用 `failOnStartupError: true`，因此
连接或工具发现失败不会被误报成可用。配置只影响之后创建的 Session；MCP 工具是否
实际出现仍以 DSH tool catalog 和会话事件为准。

### Phase 3 交付边界

Phase 0–3 已完成并通过隔离组合验收，当前暂停在 Phase 3，不自动进入 Phase 4。已交付
的边界包括：Provider 与 MCP 凭据的受保护注入、User Preset 的复制/打开/删除/恢复、
MCP 配置的 preview/apply、mount validation、stdio/streamable HTTP 连接，以及 Skill
元数据的 discover/approve/revoke。Plugin manifest 已完成安全发现、审批和 provider
边界；安装、升级、签名验证和隔离 Runner 仍属于后续能力。

2026-08-29 在全新隔离 profile 上通过了
`agent_daily_acceptance.py --runtime-smoke --mcp --skills-subagents`：Plan Review、
批准前 checkpoint、Execute、MCP `initialize/tools/list/tools/call`、Skill discover/load、
Subagent 创建/历史读取、Workspace diff 与精确恢复均为通过。该报告只保留布尔值、计数和
状态，不包含提示词、模型输出、路径、凭据或 Cookie。

固定 DSH Web API 没有独立的 live `mcp.list`、Readonly policy、composition 写入、artifact
或 rollback RPC。Sumika 对这些能力明确返回 `not-exposed`，或由自身 WorkspaceRuntime
补足可验证的 diff/恢复边界；不会把观察到的工具或包存在误报成在线能力。后续只有在用户
明确恢复目标后，才开始 Phase 4 的更广泛日用任务和真实第三方账号/MCP 验证。

### User Preset 管理

Agent 页读取 DSH 的真实 `agentPreset.list`，并通过固定协议提供
`agentPreset.copy`、`agentPreset.openDocument` 和 `agentPreset.remove`。用户 Preset 还可
显式执行 mount validation：DSH 创建一个指定 Preset 的空白 Session 来触发真实组装，
成功后必须通过 `workspace.archiveSession` 归档该验证 Session；创建或归档任一步失败都
明确报错。除上述带 Sumika 标记的 MCP 行外，Sumika 不解析、展示或重排 Preset 的其他
composition 内容，也不会直接删除 DSH profile 中的目录。

删除不是只由 Skill 约束的工具能力。Core 在每次删除前重新读取 DSH roster，只允许
`trust=user` 的精确 Preset ID，并同时要求 `approved: true` 与完整 ID 二次确认；系统、
未知来源、路径式或已经不在 roster 中的 ID 一律拒绝。UI 先要求用户输入完整 ID，再显示
不可恢复确认。审计只记录 Preset ID 和结果，不记录名称、路径或 composition。自动测试
只 mock DSH 的 `agentPreset.remove`，不会删除受管 profile 的真实内容。

Developer 页的“DSH 能力探针”（`agent.diagnostics` 或
`GET /api/agent/diagnostics`）会逐项调用只读 RPC，并显示 `available`、
`session-scoped`、`not-exposed`、`rejected` 或 `unavailable`。它会额外检查受管
`web` profile 的 `package.json` 或受管 `profiles/node_modules` 包路径是否安装了
`@deepseek-ai/dsh-mcp-client`，但不会执行 MCP 插件、读取配置密钥或把包的存在误报为可用目录。`mcp.list` 返回 HTTP
404 时被记录为 `not-exposed`；只有实际返回目录才会标记为 `available`。探针结果
是一次性运行元数据，不写入聊天历史或 Provider 档案。

`session.models` 现在为当前会话提供模型目录、当前选择、`routable` 状态和分组失败
信息。Sumika 只返回 Provider/模型标识、显示名称、说明及 reasoning effort 元数据，
不会透传适配器内部状态或凭据。模型切换继续使用 `session.selectModel`，只影响当前
DSH Session。

Agent 页还接入了 `workspace.list` 和 `workspace.create`。后者只让 DSH 登记一个已经
存在且通过 `WorkspaceRuntime` 检查的 Git 目录；它不会创建、移动或删除目录。新建
DSH 会话必须显式携带已登记的 `workspaceId`，不再使用当前进程目录。删除 Workspace
登记、重排、归档会话等真实 DSH 协议本轮不在 Sumika UI 暴露。

这层登记与 Sumika 的 Git 安全层分开。Agent 页的“Workspace 安全与回滚”使用
`WorkspaceRuntime` 的 `workspace.inspect`、`workspace.checkpoint.create`、
`workspace.checkpoint.diff`、`workspace.restore.preview` 和 `workspace.restore` RPC，
对同一目录保存文件摘要和受控 blob。恢复前会自动保存恢复前 checkpoint，并在明确
批准后把当前变更移入仓库内的可恢复归档；公共响应不包含文件内容、绝对归档路径或
内部 blob。文件列表超过展示上限时只截断 UI 摘要，不截断恢复范围。

Execute 请求必须携带当前 Session 实际归属的 `workspaceId`。Core 重新读取 DSH
Workspace roster，确认 Session 归属后先创建 checkpoint，再把目标交给 DSH；检查或
checkpoint 失败时不会发送目标。用户仍可在 UI 中额外创建命名 checkpoint。
Plan 请求本身不创建 checkpoint；由于批准 `exit_plan_mode` 的 Plan Review 会在同一回合
直接继续执行，Core 会先识别精确的待处理审查、验证 Session/Workspace 归属并创建
checkpoint，然后才向 DSH 回复 `Approve`。任一步失败都不会批准计划。
WorkspaceRuntime 不提交 Git、不删除已有 `deprecated/` 内容，并不声称 DSH 已提供
artifact 或 rollback RPC。

固定版 DSH 没有可由 Sumika 验证的独立 Readonly policy/Preset，因此 adapter 不声明
`readonly` capability，UI 也不显示该模式。Plan 继续通过 DSH command plane 提供真实的
非修改规划流程；Readonly 只有在未来 Runtime 提供可验证策略后才会进入可选项。

`session.fork` 用于从源会话的最近完成回合创建子 Session；固定协议也允许以后传入
消息对应的 `atSeq`。Sumika 当前只提供“从最近完成回合创建分支”，创建后原会话和日志
保持不变。这是可恢复分支，不是原地 rollback，也不会修改 Git 工作树。

Sumika 通过 `agent.session.snapshot` 对 `session.history` 做安全投影：只返回最近的
用户/Agent 文本、Plan 投影、工具名称与状态、审批摘要和数值运行统计。工具调用若带有
DSH host 计算的 `ToolEventView`，还会显示经过白名单的卡片标题、文件位置、退出码和
有限结果摘要；原始 streaming chunk、系统/插件提示词、工具参数与完整工具结果不会进入
UI 或 Sumika 事件日志。`session.cancel`
在 Agent 页显示为“停止回合”；继续执行由用户再次提交目标完成，避免把 DSH 尚未公开的
暂停协议伪装成已实现能力。

Agent 页会把 DSH host 提供的 `ToolEventView(card=diff)` 投影为文件级 diff 摘要，只显示
标题、状态、文件数量和受限路径，不返回完整 patch、原始工具参数或结果。固定版 DSH
仍没有独立的 artifact、diff 或 rollback RPC，因此这项能力表示“已观察到工具产生的
改动”，不表示 Sumika 已具备产物仓库或一键回滚。

固定版另提供无 RPC envelope 的 `GET /api/session.export`。当前会话的“导出原始日志”
通过 Sumika Core 流式代理该 ZIP，不把完整内容载入内存；默认同时导出子 Agent 日志和
引用附件。ZIP 含原始会话 JSONL，可能包含聊天正文、工具输入、模型上下文和附件，只在
用户主动点击时下载，不写入 Sumika 事件日志。上游返回非 ZIP、会话不存在或持久化后端
不支持 raw artifact 时会明确失败，不回退为本地拼装的伪导出。

会话区同时提供三项受控的会话操作：

- `agent.sessions.search` 转发 DSH 的 `session.search`，每次最多返回 20 个会话摘要；
  查询为空、过长或含控制字符会在 Core 边界拒绝。若部署将 session-query index 的
  `openAt` 设为 `never`，界面会显示搜索未启用，不会退回本地全文扫描。
- `agent.session.rename` 转发 `session.rename`，标题由 DSH 规范化并写入标题事件；
  Sumika 审计只保留会话 ID、规范化标题和序号，不记录消息正文。
- `agent.session.attachment` 只允许读取 DSH 已验证且被该会话引用的图片。Core 只接受
  PNG/JPEG/WebP/GIF、限制 base64 大小，并向 UI 返回脱敏引用；图片数据不写入 Sumika
  事件或日志。会话消息仅携带附件元数据，用户点击“查看图片”时才读取正文。

Agent 页会记住最后选择的 DSH Session，但只在 `localStorage` 保存 `runtime_id` 和
`session_id`。重启或刷新后先以 `agent.sessions` roster 校验，再重新加载该 Session 的
命令、Skills、待处理交互、模型、队列、Subagents、Workspace 归属和最近八组消息。
DSH roster 是权威源；消息正文、路径、工具结果和凭据不会写入该偏好记录。创建会话后
若 roster 短暂为空，前端保留 DSH 刚返回的 ID，避免把最终一致性窗口误判为会话失效。

最近消息区域的“加载更早消息”使用 DSH `session.history.beforeSeq` 游标继续向上翻页。
适配器把当前页最早事件的 sequence 作为下一页游标，前端只合并脱敏后的消息、工具、审批、
产物和时间线，不覆盖已经显示的当前页；低频同步或只读投影短暂为空时也保留已有内容。
游标分页不会暴露原始事件、工具参数或完整结果，历史用尽后按钮消失。

### 刷新、断线与失败回合恢复

Agent 页面每 15 秒执行一次低频同步；WebSocket 重连、窗口重新聚焦和页面重新可见时
立即同步。同步先以 DSH `agent.sessions` roster 校验当前 Session，再并行读取 snapshot、
queue、interactions、models、Subagents、Workspace 和任务投影。同步请求不会在发送、审批、
队列编辑或其他 Agent mutation 期间重绘页面；完成后最多补发一次排队同步，避免覆盖输入中
草稿或确认状态。

若最近回合明确以 `error`、`failed`、`cancelled`、`aborted` 等终态结束，且最近用户目标
只有文字，Agent 卡片显示“重试最近目标”。重试必须由用户确认，并再次提交精确 Session ID；
Core 在 adapter 调用前创建 Workspace checkpoint，只向 Runtime 传递模式和 Session ID，
不转发审批字段。图片目标、缺失历史、运行中或已完成回合不会自动重放；含图片的目标只提示
用户重新附加。返回值和审计事件仅含回合标识、模式、长度和 checkpoint ID，不含目标正文、
工具结果或审批文本。

当前重试实现复用正常 `session.prompt`，因为固定 DSH Web API 没有稳定的 `session.retry`
RPC。适配器从受限 `session.history` 提取最后一个失败/取消文本目标，拒绝非文本或新近成功
回合；未来 Harness 若提供原生重试协议，可在 `AgentRuntime` capability 中替换而不改变 UI
和 Core 的审批边界。

Agent composer 也支持同一组图片格式的临时附件。文件只在内存中转为 DSH `session.prompt`
的 image content block，发送成功后立即从 Sumika 前端状态清除；Plan 命令仍只接受文字，
不会把图片静默丢弃或当作普通文本。

Core 对 JSON 请求执行分路径大小限制：普通接口（包括 `/api/chat`）最多约 2 MB；`/rpc`
最多 18 MiB，以容纳经过 base64 编码的单次图片提示。图片本身仍由 Agent adapter 限制为
最多 12 MiB、受支持的 PNG/JPEG/WebP/GIF，并不会因为 HTTP 上限放宽而进入事件或日志。

健康检查成功后，适配器连接只读 WebSocket `/api/events.mux` 和
`/api/events.host`，将 `session/event`、`session/queue`、`session/jobs`、
`approval/requested`、`approval/resolved`、问题和宿主事件投影到 Sumika 事件日志。
`session/queue` 是 DSH 的权威瞬时 inbox 快照，核心只在内存中缓存其 `queued` 和
`steering` 项的有限文本投影，`context` 项只计数不展示。审批通过
`/api/respond` 发送 `client-response` envelope，并携带原始 `rpcId`、
`sessionId`、`approvalId` 和结果；断线会重连，核心关闭时会停止桥接。未知
字段进入不可变的 `extensions`，解析失败或未知审批响应保持 fail-closed。

### 待处理交互

DSH 的服务器请求不会被当作普通事件丢给聊天页。适配器在内存中维护一个按原始
`rpcId` 索引的短生命周期队列，并只向 UI 暴露以下脱敏投影：

- `approval/requested`：`id`、`session_id`、`approval_id`、工具名称、原因和创建时间；
- `question/requested`：问题 `id`、标题、说明、选项以及是否允许多选。

当问题同时带有 DSH 固定的 `intent.kind = "plan-review"`、`Approve` 和
`Keep planning` 选项时，Core 会额外标记 `plan_review` 投影。Agent 页会把它显示为
独立的计划审查卡片：计划详情使用有界的可滚动文本展示，“批准并执行”发送
`Approve`，“继续规划”发送 `Keep planning`（可附带受限的意见文本）。两者都使用
原问题 ID 和完整 answer batch，不把审查内容写入 Sumika 聊天消息。
“批准并执行”还必须携带当前 Session 的 `workspaceId`；Core 返回的有界回执包含新建
checkpoint 摘要，前端据此刷新 Workspace 安全区。

“直接讨论”使用单独的 `agent.question.cancel` RPC，发送 DSH 要求的
`ok: false` / `error.code: "cancelled"` 响应。它表示用户关闭审查并准备发送新消息，
不会伪造一个选项答案；运行时保持 Plan 模式，直到用户或 Agent 明确切换。

Agent 页的“待处理交互”区域通过 `agent.interactions` 读取队列。审批只能选择
`allowed-once` 或 `rejected`；问题回答必须与 DSH 请求中的问题数量、顺序、问题 ID、
选项和单选/多选约束完全匹配，也可以提交受长度限制的自定义文本。核心在发送前再次
校验，随后向 `/api/respond` 发送：

```json
{
  "type": "client-response",
  "rpcId": "<原始请求 ID>",
  "result": {
    "ok": true,
    "value": {
      "sessionId": "<session ID>",
      "answer": {
        "answers": [{"id": "choice", "selected": ["现在执行"]}]
      }
    }
  }
}
```

DSH 只有在响应明确接受后，Sumika 才会移除队列项；网络失败、过期请求或 DSH 拒绝
不会清除，便于用户重试或等待 `approval/resolved` / `question/resolved` 事件。审计
事件只记录请求 ID、会话 ID、动作和回答数量，不记录选项文本、自定义回答、凭据或聊天
正文。核心退出时队列会丢弃，不写入 SQLite，也不会伪造恢复后的审批。

### 工具事件与待发送队列

Agent 页的“工具”区域默认折叠每次调用。它只消费 DSH host 随事件附带的
`ToolEventView`：`generic`、`terminal`、`diff`、`search`、`read` 和
`web` 卡片会转换为 Sumika 自己的摘要；没有 view 时保留工具名和状态。
`rawInput`、完整 diff 文本、完整搜索命中和原始结果不会跨越 Core 边界。

“待发送队列”不是聊天历史，也不是持久任务列表。它只在收到 `session/queue` 后显示，
并通过真实的 `session.updateQueue` 支持 `edit`、`remove` 和 `steer`。编辑仅允许
纯文本项目且限制为 12000 字符；附件或未知 content block 只能移除，`context` 项不
能编辑。队列快照和编辑文本不会写入 SQLite，刷新或核心退出后以 DSH 的新快照为准。

## Provider 桥接

当 Sumika 中存在已测试的当前 Provider 档案时，Agent 新建会话会执行一次显式
桥接：把档案投影为 `llm-pi-ai` 下独立的 `sumika-<profile>-<hash>` route，随后
调用 `session.selectModel` 选择该档案的模型。DSH 原有 Provider 和默认模型不被
覆盖；旧 route 只在同一个 Sumika 档案再次同步时更新。Agent 页的“同步当前档案”
按钮可单独执行这一步，便于在发送目标前检查状态。

Base URL、模型和非敏感请求头进入 DSH settings；API Key 只通过
Windows Credential Manager 持久化。Tauri 启动受管 DSH 前调用只读 Python helper，
只读取当前已启用且健康档案的密钥，再通过 NUL 分隔私有管道把值放入 DSH 子进程的启动
环境；密钥不进入命令行、DSH `credentials.set`、settings、SQLite、事件或日志。DSH 的
`credentials.describe` 必须把该引用报告为 `source=env`、`writable=false`，否则同步
保持 fail-closed。没有鉴权的本地 Ollama 等 route 只使用固定的非敏感占位值。

Provider 档案每次实际变更密钥都会生成新的非敏感 `credential_revision`，route 中的
环境引用也随之变化。若 DSH 已经运行，Agent Provider 面板显示“需要重启”及具体原因，
重启前不允许同步，避免旧进程继续静默使用旧密钥。当前桥接适配已实现的
OpenAI-compatible Chat Completions route；自定义敏感请求头、尚未测试的协议和不完整
档案会明确拒绝，不会回退到 Fake 或静默使用另一个模型。

同步顺序固定为“验证凭据来源 → 写入精确 route → 通过 `llm.providers` 验证 adapter
已激活”。route 验证失败时，只在该 route 仍与本次写入完全相同时按最新 revision 恢复
旧值；检测到并发修改会拒绝覆盖。远程密钥从不参与这条 Runtime 写入与回滚链。

`python tools/smoke_dsh_round.py --endpoint <isolated-endpoint> --profile-dir
<isolated-profile>` 可显式运行测试专用协议 smoke。它启动仅测试可见的标准库
OpenAI-compatible SSE stub，完成 route、Session、模型选择、prompt、WebSocket 事件和
最终 snapshot 验证，再移除唯一测试 route 与凭据引用。它不测试模型质量、不注册生产
Provider，也不读取用户凭据；每次运行会在隔离 DSH Profile 中保留一个 Session 作为
协议证据。

显式增加 `--mcp` 时，profile 根目录还必须包含内容完全匹配的
`.sumika-mcp-smoke-profile.json` 安全标记。smoke 会复制一个临时用户 Preset，挂载仓库内
测试专用的标准 MCP stdio server，完成 `initialize`、`tools/list`、
`mcp__sumika_smoke__echo` 工具调用和结果回传，并确认挂载验证 Session 已归档。该流程已在
固定 DSH `0.1.1-rc.2` 上验证 26 个可见工具及一次真实 MCP `tools/call`。Preset 和会话留在
专用隔离 profile 中作为证据，不会写入生产 profile；该 smoke 当前证明无鉴权 stdio
协议闭环。受保护 MCP 凭据的存储、表达式防篡改、多绑定启动协议、重启门控和密钥隔离
由 Python、Rust 与 Playwright 专项测试覆盖；带真实第三方密钥的端到端 smoke 仍需用户
明确配置目标服务后执行。

`python tools/agent_daily_acceptance.py --runtime-smoke --profile-dir <isolated-profile>`
是日用验收入口。它会创建临时 Git 仓库和临时 checkpoint store，调用上述 smoke 的
`--plan-execute` 流程，依次验证 DSH Plan command、`exit_plan_mode` 审查、明确批准、
Execute 工具链、Workspace diff、恢复预览和精确恢复；临时仓库在进程结束时清理。该脚本
只输出有界状态和计数，不输出 DSH 原始 stdout、Prompt、模型内容、路径或凭据。当前已在固定
DSH profile 中通过 `--plan-execute --mcp --workspace-recovery` 组合回合。`--mcp`
可在同一隔离 profile 中追加无鉴权 MCP fixture，`--full-tests` 才会运行 Python、Node、
前端构建和 Rust 回归检查。没有显式 `--runtime-smoke` 时只运行 Core preflight，便于
启动前快速判断 Provider、Workspace 和能力状态。

对已经完成的真实 Provider Session，可改用只读 `--real-session <session-id>`。该模式不会
重新发送 Prompt 或调用模型，而是通过 Core `agent.acceptance.evidence` 从最多 1000 条事件
中验证 Plan Review 请求与批准、批准前 checkpoint、回合完成、写工具、diff、恢复预览和
精确恢复。checkpoint 晚于批准、任一终态缺失或恢复未完成都会令阶段失败。Session、
checkpoint、request ID、路径、时间戳、Prompt 和模型输出都不会进入报告：

```powershell
python tools/agent_daily_acceptance.py `
  --core-url http://127.0.0.1:8771 `
  --real-session <session-id> `
  --report-dir .sumika-desktop\logs\acceptance --json
```

为验证 Skills 与 Subagents，可追加 `--skills-subagents`：脚本会在隔离工作区创建一次性
`.agents/skills` fixture，通过真实 `skill.list` 发现并调用 Skill，确认 Skill 正文只到达
测试 Provider；随后调用 DSH `subagent` 工具，并用 `subagent.list` / `subagent.history`
核对直接子 Agent 与摘要。该选项会暂时把隔离 profile 的默认模型切到测试 route，结束时
逐字恢复原设置；报告只投影 `discovered/loaded/created/history` 布尔值和子 Agent 数量，
不输出 prompt、回复正文、文件路径、工具参数、凭据或 Cookie。建议日用命令为：

```powershell
$env:PYTHONPATH = 'backend/src'
python tools/agent_daily_acceptance.py --runtime-smoke --skills-subagents `
  --profile-dir <isolated-profile> --endpoint http://127.0.0.1:3080 --skip-preflight
```

该回合只用于隔离验收，不会安装 Skill、修改生产 Session 或改变用户的 DSH Profile。

显式增加 `--workspace-recovery` 时，脚本只接受带固定 marker 和基线文件的专用 Git
测试仓库，并拒绝 Sumika 源码 checkout。DSH 必须先 `read` 目标再 `edit`；脚本随后要求
所有工具结果均为 completed，再验证唯一文件 diff、恢复预览令牌、恢复前 checkpoint、
可恢复归档和基线内容。DSH 的嵌套 `tool-result` 只投影 `callId` 与 completed/failed，
错误正文、工具参数和结果内容不会进入公开 Session snapshot。

桥接只影响新建或明确选择模型的 DSH Session；已经运行的旧 Session 保持其原有
模型选择。若 DSH 未安装、`llm-pi-ai` 未挂载或 route 注册失败，Agent 请求保持
fail-closed，先修复同步状态再继续。

## BrowserSkill policy companion

官方 `@wxg-prc-cpg/browser-skill-dsh-plugin` 保持 BrowserSkill 工具和会话实现的事实源；
Sumika 不 fork 该插件。受管 profile 额外安装 `@sumika/dsh-browser-policy`，通过 DSH
公开的 `tools/pre-execute` waterfall 将脱敏工具元数据交给 Core
`browser.policy.evaluate`。`allow` 才继续执行，`ask` 进入 DSH 原生审批，`deny` 和 Core
不可达都不会调用 `bsk`。策略插件还补充结构化 `browser_request_help`，将登录、OTP、
CAPTCHA 和凭据输入交给隔离浏览器窗口中的用户。

这层是 Harness adapter，不是浏览器实现：BrowserSkill 继续负责实际 DOM/CDP，Core
继续负责策略、审计和 quarantine，DSH 只负责 Agent 工具生命周期。因此未来新增其他
Harness 时可复用 Core `BrowserPolicyEvaluator` 和 BrowserSkill runtime，只重写对应的
pre-execute/approval 适配器。当前 DSH 进程必须在 policy plugin 安装后重启才能加载它；
外部已运行的 DSH 不会被 Sumika 强制停止或重启。

## 迁移边界

- 旧 Sumika Chat、会话、角色、Avatar、桌宠和 Provider 档案继续可用。
- DSH Session 是新运行时对象，旧会话只能查看/导出，不伪装为 DSH Session。
- Provider 迁移必须预览；密钥仅在受保护凭据存储可用时转移，否则要求重新输入。
- DSH 插件必须先在隔离 profile 中完成许可证、权限、卸载恢复和端到端测试，
  再由用户批准进入生产列表。

## 相关文档

- [隔离浏览器](browser-runtime.md)
- [Evolution Knowledge Registry](evolution-registry.md)
- [状态矩阵](../status-matrix.md)
- [DSH 许可证和来源登记](../ui/license-ledger.md)
