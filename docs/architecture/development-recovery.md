# 开发执行记录、验证证据与测试进程

状态：部分实现。对应[剩余计划](../refactor/remaining-execution-plan-v2.md) R01c、R02c、R03a/c；当前实现不提供未知操作自动重发，也不代表自动续跑、独立验收或日用自改已完成。

## 上游对照与复用决策

本轮按用户要求实际读取上游源码，而非只比较功能名。执行顺序遵循[上游优先规范](reusable-components.md#上游优先差量实现)：**固定版 DSH 优先直接复用；Codex 开源 CLI/app-server 补充对照；只自行补宿主差量**。Sumika 生产 Agent Runtime 是 DSH，但本文件涉及的 `run_development` 是独立 API 直连路径，当前未经过 DSH。两者不能混称。

核验来源：

- DSH：本机 `D:/Tools/DeepSeekHarness/0.1.1-rc.2/node_modules/.pnpm` 中实际安装的 `@deepseek-ai/dsh-session-persistence`、`dsh-compaction-basic`、`dsh-compaction-tool-result-pruner`、`dsh-jobs-local`、`dsh-pwsh-local`、`dsh-subprocess-local`，版本均属固定版依赖图；检查其 `package.json` 与 `lib/index.js`。CLI/package 声明 MIT，来源 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)；项目固定源码基线见 [DSH 集成](../integrations/dsh-agent.md)。正式提取仍须逐包/逐文件核验许可和依赖。
- Codex：通过 `git ls-remote` 锁定本次源码观察点 `5c013177d85b72d61dc35e0634511c6d55af5cc5`，读取下列实际文件及根 LICENSE/NOTICE。Apache-2.0，NOTICE 另记第三方来源；这不是对已安装 Codex 客户端版本的声明。源码只读缓存位于 `D:/Caches/sumika-upstream-review/codex-5c013177d85b72d61dc35e0634511c6d55af5cc5`，不含账户资料。
- [Codex 官方 app-server 文档](https://developers.openai.com/codex/app-server) 明确提供 `thread/resume`、`thread/compact/start`、`turn/interrupt` 和审批/流式事件，可作为未来独立 Runtime 接口候选，不要求现在切换底座或复制桌面 UI。

| 本次或下一步机制 | 已核实的现成实现 | 取舍及边界 |
| --- | --- | --- |
| 持久记录、恢复 | DSH `SessionPersistenceCoordinator.append/prepare/load` 校验连续 seq、序列化写入、准备恢复时占有身份；有写后队列与 flush。Codex [rollout recorder](https://github.com/openai/codex/blob/5c013177d85b72d61dc35e0634511c6d55af5cc5/codex-rs/rollout/src/recorder.rs) 分开排队、persist 和带确认的 flush | 通用机制已有，之前应先比较。DSH 会话直接用原持久层；API 路径现有 metadata journal 仅绑定 WorkService 请求版本/预算/副作用，不替代上游完整 transcript。排队成功不能当作执行前已持久化 |
| 工具测试进程生命周期 | DSH `dsh-pwsh-local` 经 `ctx.subprocess.spawn`，`dsh-subprocess-local` Windows 分支使用受管树检查及 `taskkill`。Codex [unified exec process](https://github.com/openai/codex/blob/5c013177d85b72d61dc35e0634511c6d55af5cc5/codex-rs/core/src/unified_exec/process.rs) 将执行委派 Local/ExecServer，另有 [process_group](https://github.com/openai/codex/blob/5c013177d85b72d61dc35e0634511c6d55af5cc5/codex-rs/utils/pty/src/process_group.rs) Unix 组清理与 Linux 父死亡信号 | DSH 工具由其原执行器管理，不重复监管。API 路径保留小型 Windows Job 适配，以内核 handle 关闭覆盖 Core 崩溃；本轮真实测试已覆盖。不能由读到一个 process_group 文件就断言 Codex 全部 Windows 路径无保护；未运行上游崩溃对照，不声称比上游强 |
| 有界上下文 | DSH `ToolResultPruner.pruneContent/pruneSession` 已有无模型头尾保留、中间省略、Unicode code point、替换来源与计量事件；`BasicCompaction` 有模型总结及容量阈值。Codex [history](https://github.com/openai/codex/blob/5c013177d85b72d61dc35e0634511c6d55af5cc5/codex-rs/core/src/context_manager/history.rs) 保持工具调用/回执配对，[compact](https://github.com/openai/codex/blob/5c013177d85b72d61dc35e0634511c6d55af5cc5/codex-rs/core/src/compact.rs) 区分压缩替换窗口和持久 checkpoint | 下一包先验证 DSH 原能力，不重写另一套 DSH 压缩器。直连 SDK 若需纯 Python 窄适配，复用设计/测试原则并写明依赖成本；不能直接字符串截断 JSON、丢调用配对或让总结授予权限。模型总结不属于免费确定性裁剪 |
| 源码测试证据 | Git/checkpoint 与摘要是既有技术，不属于 Sumika 独有发明 | 保留当前绑定批准测试命令及源码状态的宿主回执；未核实上游有与此完全等价的跨宿主成果认证接口，不据此声称上游没有。独立测试集与原仓库合入仍另验 |
| 消费和未知提交 | 上游会话生命周期不等同 Sumika 的授权版本、资金类别、共享预留、结算事实 | 继续复用唯一 WorkService 账本；不能用上游恢复/补齐中断事件来取消未决预留或决定重发。本轮没有引入第二份持久会话或自动重放器 |

本轮只读核验上游，没有复制第三方源码、增加上游依赖、启用自动压缩、改 Codex 个人文件或升级日用 DSH。当前 journal/Job 修改不是“上游没有这些功能才自研”，而是保留 API 路径与宿主所需的窄边界；如果后续执行路径改用成熟 Runtime，应复用它的对应能力并退出重复执行职责，不并行维护两套同义循环。

下一包 R03a/b 的具体顺序：

1. 用现有隔离 DSH profile 核验持久恢复和确定性裁剪；记录实际 API、flush 语义、工具配对和中断事件，禁止连接日用会话。源码核验不冒充运行验收。
2. 在现有 Agent Runtime 适配层保留外部 session/turn 引用，查询状态不重复 prompt。没有可确认的发送事实就维持未知。
3. 对 API 直连路径明确选择受管 Runtime 委派还是小型上下文适配；优先不引入完整第二 Harness。若保留本地上下文，须有版本化持久 checkpoint、完整工具配对、裁剪来源、原始结果引用和摘要授权检查，再开放续跑。
4. 同时重检候选、授权版本、费用预留、源副本及测试证据。工具回执缺失不得靠模型猜测补成成功；裁剪不改变事实或授权。上述合同和故障测试通过前，UI 仅提供只读 inspect。

## 单一存储与接口

### 已接入的执行增强边界

`development/contracts.py` 定义窄 `DevelopmentExecutor` 接口：预检、只读检查和执行。`development/executor.py` 的 `ApiDevelopmentExecutor` 复用现有 SDK `run_development`，只负责源码副本、工具/Skill协议、测试及交付前摘要核对；不接收 CoreApplication、WorkService、数据库或凭据仓库。Core装配入口注入副本工厂，WorkService只提供已绑定模型调用、受控helper、取消、准备回执、操作日志及事件回调。

WorkService保留任务状态、用户确认、共享资金预留/结算、journal持久化和成果存储。新任务与授权保存 `development_executor_id`，执行中不可无声切换。旧记录缺字段只映射 `api-source-copy/v1`，不会自动映射新Runtime；旧 `development_factory` 构造参数仅作为同一适配器的兼容入口，不能和新executor同时配置。回执版本为 `development-execution/v1`。

这次改造是现有API分支解耦，不是新增另一套完整Harness，也没有让DSH经过API工具循环。DSH仍走既有AgentRuntime/LegacyWorkAdmission路径，其会话、历史和工具管理由DSH拥有。新增接口目前仅本地模块验收，不能称整个WorkService已独立发布。后续增强业务核心的提取应继续复用quality-routing及原账本，不能把本类改成大而全的上下文容器。

执行日志放在现有 `work-requests/v1` 记录的 `development_journal` 字段，沿用记录的助手、任务、需求版本和授权。没有副本内JSONL文件、第二套数据库或新的费用账本。旧记录缺少此字段仍可读取。工作流的事务比较更新沿用 `Storage.save_record_group`。

SDK模块 `quality_routing.development_journal` 只提供纯数据校验、追加和恢复分类；宿主通过 `run_development(..., journal=callback)` 注入持久化。没有callback的独立旧调用仍可用，但不能宣称具备持久恢复能力。Sumika开发路径已接callback。

每个事件包含 `schema_version=development-journal/v1`、`operation_id`、`kind`、`turn`、`phase`。模型操作ID为 `model-<turn>`，工具为 `tool-<turn>-<slot>`；稳定性限定在同一个工作请求版本中。工具另有 `slot/name`。输入输出只记录SHA-256，日志schema不接受原文、凭据、任意附加字段。现有工作事件中的结果正文仍留在原受控工作记录中，日志不是用于重建完整对话的第二份内容存储。

| 时点 | 日志与后续行为 |
| --- | --- |
| 模型/工具执行前 | `started`及输入摘要先提交数据库；写入失败不执行 |
| 返回后 | `finished`及输出摘要先提交，再向原事件/界面发布 |
| 宿主明确证明模型未发送 | `rejected`，不保留该操作未知标记；费用由原Provider结算规则处理 |
| 工具执行中抛错 | 保守记`unknown`并停止，不能推测写入没发生 |
| 返回已发生但回执存储失败 | `started`保留，重启归未知，不自动再执行 |
| 纯参数JSON解析失败 | 未执行工具，`rejected`；正常报告错误 |
| journal出现非法事件/重复ID | 拒绝继续；重启分类为需要检查，不能清日志后重跑 |

开发模型预算attempt保存 `development_operation_id`，必须先存在对应持久化意图才能预留；同一操作拒绝第二笔预留。开发submit、意图写入和预留使用比较更新，竞争失败不派发。该保护不等于支持多个活跃Core共同执行：启动恢复仍以单一Core拥有工作队列为前提。

## 中断恢复和只读检查

Core重启遇到执行中/取消待定记录时检查journal和原费用attempt：

- 存在无确定回执的模型/工具操作：`submission-unknown`，保留费用预留；记录 `development_recovery.pending_operations`。
- 日志位于安全边界：`interrupted`，不自动重建副本或重新派发。
- 无journal的旧任务：保留旧兼容逻辑；未知费用依旧保持未知。
- 取消未知任务：保持 `cancel-requested`；再次submit/confirm/revise不会把未知操作重新变为ready。不会通过取消释放未决费用。

新增只读 RPC：

```json
{"method":"work.task.inspect","params":{"request_id":"task-id","assistant_id":"assistant-id"}}
```

宿主只使用该任务已保存的规格和副本位置，不接受调用者提供任意磁盘路径。检查任务归属、授权摘要、受管副本根、链接和checkpoint绑定，再读diff及源码摘要；扫描前后变化时拒绝提供稳定结论。没有准备完的副本或任务仍活跃时明确不可检查。

返回：任务ID/版本/状态、`recovery`、`workspace_digest`、`baseline_unchanged`、`diff`、`test_evidence_current`、`independently_verified=false`。调用不会写库、调用模型、运行测试或修复文件。`recovery.state=interrupted`表示日志本身没有待核对操作，不替代顶层已完成任务状态。

当前不能只靠hash还原模型原文、决定未知写入一定成功、证明测试子进程执行到哪一步。因此尚未提供resume按钮、未知操作确认已完成接口或自动续跑。后续R03a/b必须保存有界上下文/checkpoint，验证源文件、候选、授权、账单和已应用事实，再提供明确的续跑入口；不能把inspect直接接到submit。

## 测试证据

`DevelopmentWorkspace.source_digest()`绑定准备时的源码路径、当前可见源码内容/权限、缺失文件及确认的测试命令。遍历文件系统而非仅凭Git未忽略文件清单，新增的gitignored源码也参与校验。`.git`、依赖/构建/运行缓存等既定排除目录不参与；遇未知二进制、超限文件、链接或读取错误会阻断认证，不默默当作没有变化。依赖目录和外部环境尚未完整版本化，这不是整个操作系统的快照。

测试回执保存前后摘要及 `workspace_unchanged`，运行前后有变化即使exit code为0也不能认证。SDK收到有效前后摘要且与当前状态一致才记通过；最终模型回复与交付diff后再检查。摘要回调返回None/非法值不能回退旧revision或让缺失测试通过。未注入摘要的旧SDK调用显式标 `verification_basis=write-revision`。

这证明“指定测试针对这份源码通过”，不证明验收用例未被执行者削弱；独立冻结验收集、依赖/环境指纹、检测修改后又还原的瞬态竞态仍未完成。成果维持 `verified=false`，不能把绿色测试提升为独立验证。

## Windows测试进程

`development/processes.py`是本机平台适配器。Windows建立 `KILL_ON_JOB_CLOSE` Job Object；启动一个等候管道放行的Python引导进程，先加入Job，再允许启动用户确认的命令。Job分配失败时测试命令不运行，也不退回无监管启动。

正常返回、取消、超时、异常均关闭Job并回收其后代，包括父进程先退出的情形。Core意外退出后内核关闭持有句柄，同样回收Job成员。Job句柄不传给后代。输出写临时文件、有量限制和截断标记；快速写满后退出的进程也不能绕过输出超限状态。POSIX保留独立进程组清理，未冒称跨平台等同Windows验收。

这是进程生命周期保障，不是文件/网络/凭据权限沙箱。测试代码仍具有当前用户权限；恶意通过外部服务启动程序等行为不在普通后代Job保证范围内。

## 验证和后续分工

专项见 `backend/tests/test_development.py`、`test_development_processes.py`、SDK的 `tests/test_development_journal.py`。包括真实SQLite重开、写入后丢回执、scope/重复/取消/事务冲突、树变化、测试反写源码、Windows真实后代进程及 `os._exit` 无Python清理的宿主退出。全部模型调用为fixture，没有消耗真实模型额度。

普通模型可以按上述契约接只读检查UI、状态提示、补既定异常样例和完善输出排版。以下仍需专门审查：R03有界上下文和自动续跑、R05原仓库合入/撤销、R02完整费用/推理计量、R01路径及复制一致性；没有因为本阶段通过就降为低风险或标成日用替代已完成。
