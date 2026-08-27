# Sumika architecture

Sumika starts as a local-first application with a deliberately small core.
The browser UI is a client, not the owner of provider or persistence logic.

这是架构专题索引。功能完成度统一维护在
[`../status-matrix.md`](../status-matrix.md)；本页和下列专题文档只描述边界、
接口、数据流和安全约束。

```text
Vue/Tauri UI (browser shell plus explicitly pinned local renderer bundles)
        | HTTP JSON-RPC commands + WebSocket events
Python application service
        | provider contract and manifest runtime
OpenAI-compatible / external-process providers
        | SQLite event and snapshot storage
```

## 专题索引

- [Protocol](protocol.md)：HTTP JSON-RPC、WebSocket 事件和命令边界。
- [Modules](modules.md)：能力目录、实现选择和配置校验。
- [Provider profiles](provider-profiles.md)：连接档案、凭据和 CC Switch 导入。
- [Local model](local-model.md)：用户选择模型、可选 Ollama 辅助脚本和推理边界。
- [Avatar](avatar.md) / [Characters](characters.md)：模型资产、角色和展示配置。
- [Desktop shell](desktop-shell.md)：Tauri 主窗口、桌宠浮窗和 Python 子进程。
- [Tasks](tasks.md)：预算、批准、生命周期和任务 HUD。
- [Agent Runtime](agent-runtime.md)：稳定会话内核、可选能力、adapter registry 和进程边界。
- [Audio](audio.md) / [Memory](memory.md) / [Vision](vision.md)：可选能力边界。
- [Manifest](manifest.md) / [Tools](tools.md)：插件发现和外部软件调用。
- [Security](security.md)：本地服务、凭据、权限和数据边界。
- [Debugging](debugging.md)：日志、诊断、事件和恢复信号。

DSH 是当前 [Agent Runtime](agent-runtime.md) 的生产 adapter；其固定协议、隔离
profile 和插件约束记录在[外部集成专题](../integrations/dsh-agent.md)。


## Boundaries

- `protocol`: serialisable messages, events and JSON-RPC errors.
- `providers`: provider-neutral LLM, ASR/TTS/VAD and vision interfaces plus
  real adapters. Deterministic test doubles live only under
  `backend/tests/fixtures`.
- `provider_profiles`: reusable connection records and credential references;
  the module layer stores only a profile id, while CC Switch remains an
  optional versioned import adapter.
- `audio`: permission-gated lifecycle for in-memory ASR/TTS/VAD calls; it does
  not own device capture.
- `memory`: opt-in, character-scoped MemoryProvider boundary with category
  policy and redacted audit events.
- `characters`: independent persona and Avatar presentation configuration;
  model binding remains behind `AvatarManager`.
- `vision`: opt-in screen/camera observation boundary with explicit source
  permissions and redacted audit events; it does not own device capture.
- `plugins`: manifest validation; third-party code is not loaded into the core.
- `tools`: approval-gated one-shot external processes using the JSONL tool
  contract; no shell or persistent process.
- `avatar`: renderer-neutral AvatarDriver plus safe local model metadata; the
  browser VRM adapter is a separate bundle behind the same boundary, while
  Live2D remains a future renderer.
- `tasks`: autonomy levels, budgets, task records and an approval-aware
  in-process runner; external execution remains disabled.
- `storage`: versioned SQLite schema, event history and snapshots.
- `transport`: local HTTP and the browser event WebSocket.

The names `ExecutionContext` and `VirtualWorld` are reserved for later work.
They must not become aliases for provider configuration or UI routes.

Snapshot recovery is exposed through `snapshot.list`, `snapshot.get`,
`snapshot.create`, `snapshot.diff`, `snapshot.restore`, `snapshot.export`, and
`snapshot.import`. A snapshot payload
contains a version, scope, target and only durable application tables. Events
and the `snapshots` table are intentionally excluded so recovery cannot erase
the audit trail. The UI always requests a diff first; restore automatically
creates a same-scope `恢复前` snapshot and publishes `snapshot.restored`.
Complete-system snapshots include sessions, messages, characters, module
settings, tasks, Avatar registrations, audio/vision permissions and memories.
Targeted snapshots currently support module settings, characters and memories.
Exported `sumika.snapshot` packages are checksummed but intentionally not
encrypted; import stores a new snapshot for review and never restores it
implicitly.

The local plugin catalog stores discovered manifest metadata, approval state,
and hashes in SQLite. It is separate from provider activation: scanning and
approving a candidate never executes its entrypoint or installs dependencies.
Plugin registrations are excluded from portable snapshots because their paths
are machine-specific; rediscovering the source directory is the recovery
operation.

## 相关文档

- [文档总入口](../README.md)
- [状态矩阵](../status-matrix.md)
- [ADR 0001：依赖轻量的首版 Shell](../adr/0001-local-first-shell.md)
