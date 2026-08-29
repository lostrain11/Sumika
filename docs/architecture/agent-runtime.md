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

## 验证边界

`backend/tests/test_agent_portability.py` 使用只实现稳定内核的 Runtime，验证：

- 可在不实现 DSH optional API 的情况下构造；
- 未支持能力明确拒绝；
- registry 对未知 ID fail closed；
- Core 状态与会话 RPC 不依赖 DSH Provider bridge。

Playwright 另验证不支持的控制不会出现在 Agent 页面。

## 相关文档

- [DSH adapter](../integrations/dsh-agent.md)
- [Desktop shell](desktop-shell.md)
- [Protocol](protocol.md)
- [Workspace 与任务](tasks.md)
- [状态矩阵](../status-matrix.md)
