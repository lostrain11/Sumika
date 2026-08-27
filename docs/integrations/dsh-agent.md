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
桌面端只有在同时设置
`SUMIKA_AGENT_AUTOSTART=1` 和 `SUMIKA_AGENT_EXECUTABLE` 时才会启动子进程；
现有 `SUMIKA_DSH_AUTOSTART` / `SUMIKA_DSH_EXECUTABLE` 继续兼容。launcher 会把
`.sumika-desktop/dsh-profile` 作为子进程 `DSH_HOME`。Sumika 不会写入用户全局
`DSH_HOME`。`SUMIKA_DSH_ENABLED=0` 可关闭适配器。

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

MCP 配置写入仍保持关闭。固定版 `dsh-mcp-client` 由 Agent preset 的 Cordis plugin row
挂载，而且包本身明确没有异步重同步后的独立 server-to-tool snapshot。后续配置管理
必须先创建 Sumika 自有的 user preset、隔离凭据注入并通过 mount validation，再允许用户
显式启用；当前实现不会静默修改 `cordis.patch.yml`、系统 preset 或全局 DSH。

### User Preset 管理

Agent 页读取 DSH 的真实 `agentPreset.list`，并通过固定协议提供
`agentPreset.copy`、`agentPreset.openDocument` 和 `agentPreset.remove`。Sumika 不读取、
展示或直接改写 Preset composition，也不会直接删除 DSH profile 中的目录。

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
存在的目录；它不会创建、移动或删除目录。新建会话可显式携带 `workspaceId`，否则
继续使用当前进程目录。删除 Workspace 登记、重排、归档会话等真实 DSH 协议本轮不在
Sumika UI 暴露。

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
`credentials.set` 写入受管 DSH 凭据层，Sumika 日志、事件和 API 返回均不包含密钥。
当前桥接适配已实现的 OpenAI-compatible Chat Completions route。自定义敏感请求头、
尚未测试的协议和不完整档案会明确拒绝，不会回退到 Fake 或静默使用另一个模型。

桥接只影响新建或明确选择模型的 DSH Session；已经运行的旧 Session 保持其原有
模型选择。若 DSH 未安装、`llm-pi-ai` 未挂载或 route 注册失败，Agent 请求保持
fail-closed，先修复同步状态再继续。

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
