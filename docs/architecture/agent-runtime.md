# Agent Runtime portability

Sumika 的 Agent 子系统采用“稳定会话内核 + 可选 capability”边界。当前生产
adapter 是 DSH，但 Core、UI 和 Tauri 生命周期不以 DSH 的完整功能集合为最低接口。

## 稳定内核

每个 `AgentRuntime` 只必须实现：

- `status` / `health`；
- `create_session` / `list_sessions`；
- `snapshot`；
- `prompt` / `cancel`。

事件通过 `set_event_sink` 投影为 Sumika 事件。Preset、Provider bridge、Plan、
Queue、Goal、MCP、Skills、Subagents、Workspace、附件和原始导出都是
`AgentCapability`。未实现的 capability 必须明确返回 unsupported，不允许伪造结果或
回退到 Fake。

`agent.status` 返回 `runtime_id` 与 `runtime_capabilities`。前端只渲染运行时声明的
控制；新 adapter 不必实现 DSH 的 Preset、Goal revision 或 Queue/Steer。

## 选择与构造

`AgentRuntimeRegistry` 保存真实 adapter builder；`SUMIKA_AGENT_RUNTIME` 选择当前
runtime，默认值仍为 `dsh`。未知 ID 返回 fail-closed 的
`UnavailableAgentRuntime`，不会静默回退 DSH。`CoreApplication` 允许注入 Runtime，
用于 contract test 和将来的 adapter 集成。

Provider bridge 是可选能力。声明该能力的 adapter 由 Core 将当前 Sumika Provider
档案显式同步；没有声明时，新会话由 Harness 自己管理 Provider，Core 不强制要求
Sumika Provider 档案。

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

现有 `SUMIKA_DSH_*` 变量继续作为 DSH 兼容别名。更换 Harness 时新增 adapter、事件
翻译器和 launcher 配置，不修改角色、Avatar、BrowserRuntime、SQLite 或桌宠边界。

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
- [状态矩阵](../status-matrix.md)
