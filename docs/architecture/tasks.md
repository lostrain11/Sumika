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
Workspace isolation, diff generation, rollback, and remote execution remain
separate follow-up boundaries.

## 相关文档

- [Modules](modules.md)
- [Tools](tools.md)
- [Security](security.md)
