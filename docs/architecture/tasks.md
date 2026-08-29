# Task center

The task center is an audit surface backed by a small approval-aware execution
boundary. `TaskManager` owns persisted task records, lifecycle validation, and
`task.created` / `task.updated` events. `TaskRunner` consumes the same record
without moving runner code into the HTTP handler or SQLite layer.

## Record shape

Each task stores:

- status: `pending`, `running`, `waiting_approval`, `paused`, `completed`,
  `failed`, or `cancelled`;
- autonomy level: `L0` through `L3`;
- token, cost, time, and disk budget limits;
- requested permissions and character scope;
- progress, structured result, logs, and artifacts/diff references;
- created and updated timestamps.

The current default task represents core readiness only. It has no runner and
does not imply autonomous behavior.

## API

- `task.list` / `GET /api/tasks` lists records for the HUD.
- `task.get` returns one record.
- `task.create` creates a pending record. The UI uses `L2` for user-approved
  tasks.
- `task.runner.list` lists explicitly registered in-process handlers.
- `task.run` without `approved: true` moves a non-terminal task to
  `waiting_approval`; an explicit approved call may run the selected handler.
- `task.update` changes status or appends one log/artifact entry. Invalid
  lifecycle transitions and out-of-range progress are rejected.

The first UI exposes four compact columns: active, waiting for approval,
completed, and failed/paused. Expanding a card shows budget, permissions,
result, logs, and artifacts. The first registered handler is `core-health`, a
deterministic local health check that does not spawn processes or modify files.

## Agent Runtime 只读投影

`agent.task.projections` 把当前 `AgentRuntime` 的 Session、最近 turn、计划、待处理
交互、实际 token/时延、产物和可验证 Workspace 摘要映射到任务中心。最近 16 个 turn
只以状态、模式和步骤/工具/审批/产物计数展示，不含回合正文。投影由
`AgentTaskProjector` 在读取时生成，带有 `source: agent-runtime` 与
`read_only: true`，不会写入 `tasks` 表，也不会复制 DSH 的活动状态。

任务中心不会对投影卡片显示旧任务的批准、暂停、取消或 runner 操作；唯一动作是跳回
对应 Agent Session。Workspace 路径只用于 Core 内部调用 `WorkspaceRuntime.inspect`，
公开卡片仅包含 workspace ID/标题、branch、HEAD、dirty/file count 与 checkpoint count。
单个 Session snapshot 或 Workspace 检查失败时，只记录错误类型并降级该卡片，不把路径、
消息正文、工具参数或异常正文写入投影。

## Workspace 安全与回滚

任务记录和 DSH 的 Workspace 登记不等同于文件恢复能力。Sumika 的
`WorkspaceRuntime` 是独立的 runtime-neutral 边界，负责对一个已经存在的 Git
仓库执行：

- `workspace.inspect`：读取分支、HEAD 和受限的 Git 状态摘要；
- `workspace.checkpoints` / `workspace.checkpoint.create`：保存 tracked 与
  untracked 文件的 SHA-256、模式和受控副本；`deprecated/` 与符号链接永不纳入；
- `workspace.checkpoint.diff`：返回文件级摘要和变更计数，不返回文件内容；
- `workspace.worktree.preview` / `workspace.worktree.create`：验证新分支与尚不存在的
  目标目录，要求新鲜令牌、明确批准以及精确分支/目录确认；只从当前 HEAD 创建，
  不复制源目录未提交变更，失败时不自动删除 Git 可能留下的状态；
- `workspace.commit.preview`：只接受从干净 Git 状态捕获的 checkpoint，返回有上限的
  UTF-8 文本 patch；二进制、非 UTF-8 和大文件只列出省略项；
- `workspace.commit`：再次验证 HEAD、branch、文件状态和预览令牌，只暂存精确路径并创建
  本地 commit；禁用 hooks 和签名，不 push；
- `workspace.restore.preview`：在不修改工作区的情况下计算归档和写回范围；
- `workspace.restore`：要求新鲜的 `preview_token`、`approved: true` 和完整
  checkpoint ID。恢复前自动创建 checkpoint，并把当前变更移动到仓库内可恢复的
  `deprecated/<UTC>/workspace-restore/`。

Agent 页面把 DSH 的 Workspace 登记用于会话归属，把上述 Runtime 用于 Git 安全和
回滚；切换 Harness 时不需要重写这层。新 Session 必须绑定已登记并通过 Git 检查的
Workspace，Execute 在调用 Harness 前按 Session 归属创建 checkpoint；无法验证归属或
checkpoint 失败时不发送目标。Plan 请求只读规划时不创建 checkpoint，但批准 Plan Review
会在同一回合继续执行，因此 Core 在回复批准前执行相同的 Workspace 归属检查和 checkpoint
门控。用户也可显式创建 checkpoint、独立 worktree、审阅 patch、创建本地 commit 和批准
恢复。Sumika 不把 DSH 的 artifact 或 rollback RPC 伪装成已实现。

Workspace 恢复不会提交 Git、删除文件或清理已有归档；本地提交也不会 push、删除
worktree 或清理失败状态。两类写操作都要求独立的新鲜预览和精确确认。大批量 diff 的
公开文件列表可以截断，但恢复计数和实际恢复范围保持完整。

## 相关文档

- [Modules](modules.md)
- [Tools](tools.md)
- [Security](security.md)
- [Agent Runtime](agent-runtime.md)
