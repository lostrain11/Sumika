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

- [A+ 双模式客户端](../ui/a-plus-client.md)：当前 UI、能力布局及同一原生窗口的 workspace/pet 切换；下列 Phase 2 外壳记录保留其历史上下文。

- [Protocol](protocol.md)：HTTP JSON-RPC、WebSocket 事件和命令边界。
- [Modules](modules.md)：能力目录、实现选择和配置校验。
- [Provider profiles](provider-profiles.md)：连接档案、凭据和 CC Switch 导入。
- [Local model](local-model.md)：用户选择模型、可选 Ollama 辅助脚本和推理边界。
- [Avatar](avatar.md) / [Characters](characters.md)：模型资产、角色和展示配置。
- [Desktop shell](desktop-shell.md)：Tauri 主窗口、桌宠浮窗和 Python 子进程。
- [Desktop automation](desktop-automation.md)：应用协议、Electron CDP、Windows UIA 和受控前台接管的通用适配器边界。
- [Tasks](tasks.md)：预算、批准、生命周期和任务 HUD。
- [Agent Runtime](agent-runtime.md)：稳定会话内核、可选能力、adapter registry 和进程边界。
- [高难实施固定契约](../refactor/harness-portability-hard-tasks-v1.md)：滚动交接、Harness替换、可信确认、模型网关、恢复及合入。
- [滚动规划与交接](task-planning.md)：H00实际字段、就绪检查、阶段状态及剩余边界。
- [可信宿主确认](host-confirmation.md)：H01局部传输边界、私有引导、原生确认及未覆盖入口。
- [开发恢复](development-recovery.md)：操作日志、只读检查、源码测试证据、进程回收及 DSH/Codex 上游复用核验。
- [Audio](audio.md) / [Memory](memory.md) / [Vision](vision.md)：可选能力边界。
- [Manifest](manifest.md) / [Tools](tools.md)：插件发现和外部软件调用。
- [Security](security.md)：本地服务、凭据、权限和数据边界。
- [Debugging](debugging.md)：日志、诊断、事件和恢复信号。
- [Agent observability](agent-observability.md)：日用遥测、插件对比和自进化评估闸门。
- [可复用组件](reusable-components.md)：本轮规划的核心、适配器、装配入口边界及独立验收；不表示已提取或发布。
- [需求基线](../requirements/README.md)：长期产品意图、重构验收标准和模型策略契约。

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
- `desktop_automation`: explicitly registered desktop applications behind a
  transport-neutral adapter; profile leases, approvals, idempotency and audit
  stay in Core, while CDP/UIA clients remain optional transports.
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

## 产品领域契约（重构 Phase 1）

本阶段承接 [Phase 0 盘点](../refactor/module-inventory.md)，不是重做已经存在的场景 UI，
也不是 DSH 日用验收的同名 Phase 编号。任务范围与 DAG 记录在
[阶段任务包](../refactor/phase-1-contract-task.json)，完成度见状态矩阵的 `domain-contracts`。

### 所有权与依赖

新增的 [domain/contracts.py](../../backend/src/sumika_core/domain/contracts.py) 只有标准库依赖，
不导入 Server、Storage、Runtime、Provider 或 picker。领域状态以冻结的值对象表达，
`to_dict()` / `contract_from_dict()` 使用 `sumika.domain/v1` 和明确的 `kind`；未知版本、
未知字段、错误类型、重复标识和不一致的引用拒绝解析，错误不回显输入值。
这个序列化契约尚未成为 RPC，也不是新的持久化数据库格式。

| 领域 | 契约与唯一事实源 | Phase 1 边界 |
| --- | --- | --- |
| Assistant | `Assistant` 关联已有 `character_id`、独立 MemoryNamespace、可选资源/AgentPreset 引用 | persona 和角色卡仍由现有角色记录拥有，不复制到状态投影 |
| Scene | `Scene` 区分 `pet` / `workbench` / 预留 `home`，成员 ID、当前角色、四抽屉、背景引用 | 桌宠不含抽屉；同场景不代表共享记忆；没有渲染、日程或主动发言 |
| Capability | `Capability` 是 ModuleCatalog 的只读模块选择状态 | 不是第二套 Provider 目录；enabled、实现和状态分开，required_permissions 不是已授权列表 |
| Device | `Device` 是登记状态声明，限 LAN 摄像头/传感器、只读、远程关闭 | 不发现设备、不保存 IP/凭据、不控制小车或家庭设备 |
| Model Policy | 继续使用 [ModelCatalogEntry / RoutingRequest / RoutingDecision](../../backend/src/sumika_core/model_policy.py) 的 `model-policy/v1` | 不另建路由器；Provider 档案和 Sumika 最终复核保持权威 |
| Task | 继续使用 [TaskRecord / TaskBudget](../../backend/src/sumika_core/tasks/models.py) 与 [AgentTaskProjector](../../backend/src/sumika_core/tasks/agent_projection.py) | Runtime 是活动状态事实源；不新增竞争的任务状态机 |
| Evaluation | 继续使用 [EvaluationRecord](../../backend/src/sumika_core/model_evaluation.py) 的 `sumika.model-evaluation/v1` | 只保存可比较的脱敏证据，不自行提升质量等级或改生产路由 |
| Permission | `Permission` 明确主体、能力、资源、单次/会话范围与观测证据引用 | 默认 unknown；granted 必须有 evidence_id，但 DTO 本身不是授权票据，原审批、撤销和有效期检查仍必须执行 |
| Memory Namespace | `MemoryNamespace` 由助手独占，shared_with 默认空且只能显式声明 | 共享列表也不是访问许可；当前 MemoryRuntime 仍按 character_id 隔离，没有实现跨角色共享 |

资源只用 `ResourceRef(package_id, version, asset_id, resource_kind)` 引用本地角色、Avatar、
声音与场景包。版本不能是 unknown/latest，标识不能是路径/URL；但引用不证明资产存在、
许可证合规或已安装。旧 Avatar 只有 `legacy_avatar_id`，没有证据时不虚构资源包版本。
资源解析、导入和迁移留给后续独立任务。

### 场景与安全默认值

- 未启用/未配置模块保留在可添加目录，不出现在活动模块投影；已经启用但报错的模块仍可见，
  便于恢复，不自动开关或偷偷选择替代实现。`Capability.visible` 只是显示规则，不是执行许可。
- 麦克风、屏幕、摄像头、LAN 设备权限是不同能力与资源标识，不能从场景、角色或模块开关继承。
  Permission 不能直接驱动 Browser、Audio、Vision 或 Device 执行；未来应用服务必须查询原授权源。
- 虚拟世界配置强制关闭即暂停。有限补算是预留参数，默认 0（不补算），本版校验上限 300 秒。
  这个数值是可调整的工程保守值，不是用户确认的时间长度；本阶段不运行任何时间结算或后台任务。
- 集合最多 64 项是当前投影的技术边界，不是产品人数承诺；超限明确报错，不截断或合并角色。
- 新值对象不是日志格式。显示名属于 UI 数据；任何共享账本仍须走独立脱敏规则。

### 旧数据兼容与证据

[domain/projections.py](../../backend/src/sumika_core/domain/projections.py) 接收调用方已读取的
角色和模块快照，纯函数转换，不持有存储/服务、不读文件、不发网络请求、不产生事件：

```text
existing Storage character snapshots -> assistant_from_character -> Assistant
existing ModuleCatalog snapshots -> capability_from_module -> Capability
future application services -> domain projections -> scene UI
future picker adapter -> advisory candidate evidence -> existing ModelPolicy -> runtime revalidation
```

旧角色 ID 同时作为首期 assistant_id 和 namespace_id，保持现有 MemoryRuntime 的查询范围；
不重命名、不写回 config、不拷贝 persona/角色卡、完整路径或 Provider 配置。未知 Provider 状态
保持 unknown，`none` 实现不能变成 ready，字符串 `"false"` 不得被当作已启用。
快照中未使用的私密字段不进入投影；已有非法 ID 不静默清洗，由后续显式迁移任务解决。

验收以 [契约单测](../../backend/tests/test_domain_contracts.py) 与
[真实内存 SQLite / ModuleCatalog / MemoryRuntime 合同测试](../../backend/tests/test_domain_projections.py)
为准，覆盖版本往返、不可变嵌套状态、同场景独立记忆、无数据写回、默认隐藏、错误可见和拒绝越界声明。
既有 Task、Policy、Evaluation 回归继续验证原事实源；通过这些检查不代表 UI 已切换到新契约。

### 需求映射与下一阶段

关联稳定 ID：`CORE-001`、`UX-002`、`CHARACTER-001`、`AVATAR-001`、`CAPABILITY-001`、
`MEMORY-001`、`MULTI-001`、`DEFERRED-001`、`MODEL-005`、`MODEL-006`、`MODEL-011`、`SEC-001`。
这些 ID 来自 [需求账本](../requirements/requirements.json)；远景承接
[LT-003 / LT-004 / LT-005](../requirements/baseline.md)，不把“预留契约”记为“功能已实现”。

本次不修改已有未提交的 `server.py`、Model Policy、Runtime 及执行契约；此处记录增量恢复入口，
原 [执行契约](../current-execution.md) 的日用事项和用户改动均保留。

场景 UI 模块化接线已完成第一阶段，而不是再建一套 UI：

1. `scene-shell`、`scene-store` 和 `scene-view` 已从 `main.js` 抽离；保留 Avatar 不卸载、四抽屉、
   桌宠行为和既有 RPC，且删除了旧场景渲染器的重复实现。
2. Characters、Modules、Settings、Workbench、Agent、Web Workbench、Developer 业务视图已独立；
   渲染器从装配层注入状态与格式化函数，不拥有 Runtime 副本或发起业务请求。
3. 增加独立只读应用服务接线新投影；对照现有 RPC 验证兼容后再收敛装配层，不同时重构路由。
4. 本轮延续既有中性配色，采用纯色背景、角色强调色与统一布局层；通过真实浏览器截图验收，
   不是以后端合同测试替代视觉检查。外观预设和本地背景图仍在设置中选择。
5. picker 正式 Adapter 仍是后续独立里程碑：显式 profile + billing_group + remote_id 映射，
   stale/unknown 证据隔离、额度与中转价格有效期、请求/应用推理强度分离，最终选择留给 Sumika。

阶段编号以本轮重构计划为准；音视频、陪看、居所、多助手调度和 LAN 实机功能仍未在本阶段启用。

### Phase 2：场景外壳的第一刀

`frontend/src/scene-shell.js` 拥有导航项、抽屉分组、抽屉标题和页面标签的纯前端契约；
`frontend/main.js` 只引用这些元数据，不再维护第二份映射。该模块不读取 Core、Storage 或
Provider，也不改变 `state.activePage`、已有 `data-page` 事件和 Avatar 保留逻辑，因此是可独立
替换的场景外壳边界，而不是新的状态事实源。

`frontend/tests/scene-shell.test.js` 覆盖 Chat/抽屉页映射、未知页面、标签回退和元数据冻结；
生产构建与现有 50 项 Playwright smoke 作为行为证据。场景视图已经由
`frontend/src/scene-view.js` 集中维护；不要在后续变更中把业务请求、门户、Avatar WebGL 和样式
一起移动。

### Phase 2b：纯场景状态投影

`frontend/src/scene-store.js` 将旧入口中的少量场景显示状态投影为不可变对象：当前页面、
抽屉、桌宠浮窗、Avatar 可见性、发送中状态和门户面板状态。它不拥有业务状态、不发请求、
不写入本地存储，也不替代 Core 的会话、权限或路由事实源。未知导航回到 Chat，浮窗模式不生成
抽屉；抽屉关闭统一回到 Chat。

`main.js` 仍保留原有完整状态对象和业务函数，只在场景渲染和导航边界消费投影；场景 topbar、dock、
chat 和 drawer 通过 `createSceneView` 注入依赖。这一步让下一阶段可以分别移动业务 panel，而不把
Avatar 保留逻辑或 RPC 事件一起搬迁。
`scene-store.test.js` 覆盖默认值、不可变性、浮窗和未知页面回退；通过构建和既有 Playwright 才能
把这项拆分视为完成。

### Phase 2c：抽屉业务视图

业务视图已经移入 `frontend/src/*-view.js`：Characters/Avatar、Modules/连接配置、Settings/指南、
Workbench/任务历史通知、Agent、Web Workbench、Developer。`page-view.js` 负责页面调度与共同页框，
兼容入口 `src/main.ts` 也引用唯一导航表，不再维护过期列表。`main.js` 保留 HTTP/RPC、授权动作和
Avatar WebGL 生命周期；拆分不是新建 Vue 应用或切换 Provider。

`module-selector.js` 只投影活动模块与可添加目录，严格 `enabled === true`，LLM 不再例外常驻。
已启用但错误的模块仍可见；添加库默认折叠，不授予权限或启动设备。能力审计统一在 Developer，
费用证据位于 Modules 的按需折叠区，音频/视觉/外部工具面板只随对应活动模块显示。

`view-state.js` 保存当前页面的临时折叠、焦点和编辑状态，不写磁盘，不成为角色/会话事实源。
全局 Esc 和模态键盘监听仅绑定一次，先关闭连接配置、再关闭门户或场景抽屉；关闭抽屉后焦点回到
对应 Dock。背景在新场景 DOM 安装后应用，避免配置只短暂生效后被重绘覆盖。

`scene-layout.css` 是预览与生产共用的场景布局层，360/640 使用底部 Dock，较宽窗口使用侧栏。
移除尚无行为的聊天附件和查看文档按钮；桌面门户保留既有独立窗口，但入口移入聊天工具栏，Dock
始终只有四项。门户内嵌 webview 属于独立原生改造，不把当前浏览器 mock 记作原生验收。

范围与验证见 [UI 收尾记录](../refactor/phase-2c-ui-completion.json) 和
[UI 回归](../../frontend/tests/ui-refactor.spec.js)。本轮不修改 Model Policy、Provider、Storage 或后端 RPC，
不启用新的音视频、虚拟居所、多助手、设备能力或 model-picker Adapter。

## 相关文档

- [文档总入口](../README.md)
- [需求基线](../requirements/README.md)
- [状态矩阵](../status-matrix.md)
- [ADR 0001：依赖轻量的首版 Shell](../adr/0001-local-first-shell.md)
