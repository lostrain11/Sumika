# Sumika 产品需求基线

本基线把当前可核实的用户目标整理成稳定需求 ID，供实现、评估和未来架构重构使用。
它记录长期意图，不替代状态矩阵；一项需求可以已经实现、部分实现、延期或被后续决定取代。
快照范围为现有仓库、Git 证据和当前可见对话，无法恢复的历史原文不作推断。

## 产品定位与平台

### `CORE-001` 可日用的 Sumika 桌面助手

Sumika 是面向日常工作的桌面 Agent，同时保留角色、Avatar、桌宠和本地数据体验。
首要成功标准是用户能从明确入口启动，并在真实仓库中完成可恢复的开发任务。

- 来源：用户确认的 Codex 日用平替目标，见 `EX-CORE-001`。
- 状态证据：[执行契约](../current-execution.md)；当前状态参考 `dsh-agent-runtime`、`tasks`。

### `PLATFORM-001` Windows 优先、跨平台边界诚实

Windows 的 Python Core、受管 Runtime 和 Tauri 桌面端是当前稳定目标；macOS/Linux 先提供
直接 Python Core 命令，原生 Tauri 启动器只能标为实验性或预留。启动器不自动安装或升级
Ollama、模型、DSH、浏览器扩展或第三方插件。

### `UX-001` 工作型界面

左侧导航和固定状态区应稳定、可访问、可键盘操作；右侧内容独立滚动，不因聊天、Provider
或 Agent 内容增长而移动固定导航。错误、未连接和未配置状态必须可理解且不伪装成功。

## Chat、角色与 Avatar

### `CHAT-001` 可靠聊天流程

聊天页应显示最近记录并在新消息后保持滚动位置；发送中、失败、取消和 Provider 未就绪时
给出明确状态。没有真实后端时不生成 Fake 回复。

### `CHARACTER-001` 角色独立身份

每个角色可以单独命名；`Sumika` 是项目名，不是所有角色的默认显示名。角色身份、人格、
关系、说话风格、行为、边界、回答长度、系统提示词和首次问候应按角色保存。

### `CHARACTER-002` 人格配置必须生效

人格字段按固定顺序进入 Provider 的 system message；首次问候只作为临时上下文和空聊天页
提示，不写入消息表。编辑器按“角色身份 / 人格设定 / 高级设置”折叠分组，表现设置和
聊天人格保持分离。

### `AVATAR-001` 自然且可观察的 VRM Avatar

Avatar 默认位于中心舞台，VRM 0 模型面向用户，具有自然站姿、轻量待机动作和可选自动旋转。
视线和头部可跟随鼠标并平滑回中；缺少骨骼、表情或 look-at 时安全降级为静态模型。
表现设置按角色保存，不修改原始模型文件。

### `AVATAR-002` 透明桌宠

桌宠模式只绘制 Avatar 和紧凑聊天栏，窗口背景透明；模型区域支持上下左右拖动，聊天栏和
控制按钮不误触发拖动。主窗口、隐藏和辅助控制只在悬停或聚焦时出现。

## Provider、凭据与模型来源

### `PROVIDER-001` 可替换 Provider 档案

连接信息以可复用档案保存，模板只填写默认值，启用前必须测试端点和模型。用户可保存草稿、
切换最近使用档案和归档恢复；没有真实实现的协议不出现在生产选择列表。

### `PROVIDER-002` 用户主动选择模型

Ollama 和模型不应被启动脚本强制安装、启动或设为不可更改的默认值；`qwen3:4b` 只是可选
模板。已有会话和用户明确启用的连接不得被迁移静默改写。

### `PROVIDER-003` 凭据隔离

API Key、Token 和敏感请求头只进入受保护凭据存储。SQLite、事件、日志、Provider 档案公开
投影和模型上下文只保存引用或脱敏值。ZCode 的登录态只能通过其受支持的本地会话协议使用，
不得读取配置文件提取 Token。

### `PROVIDER-004` CC Switch 单向兼容

支持版本化导入预览、字段映射、多端点保存和敏感字段脱敏；不执行来源 JavaScript，不直接
绑定 CC Switch 内部数据库。未知协议版本和未支持字段必须拒绝执行并保留不可执行元数据。

### `PROVIDER-005` 失败即明确失败

Provider、模型目录、凭据或 Runtime 不可用时显示未就绪和可操作原因，不回退到 Fake、不静默
改用付费模型、不伪造健康状态。

## Agent Runtime、插件与 Workspace

### `AGENT-001` Runtime 中立边界

DSH 是当前默认 Harness，但 Core、UI、Tauri、角色、Avatar、Browser 和 Workspace 不得以 DSH
私有对象作为基础类。稳定内核是健康检查、Session、snapshot、prompt 和 cancel；其他能力
通过可声明的 capability 暴露，未来 Harness 只需新增 adapter。

### `AGENT-002` Codex 对标的 Agent 能力

真实 Agent 页面需要逐步支持 Session、Plan、Execute、流式事件、工具调用、审批、队列、MCP、
Skills、Subagents、任务产物和错误恢复。未被固定 Runtime 验证的能力必须显示 unsupported，
而不是通过 UI 猜测或伪造。

### `MCP-001` 受控的 MCP 配置和调用

MCP 连接通过用户 Preset 和受管配置进入 DSH；配置先预览、再经用户批准和 mount validation。
stdio 与 HTTP 连接的凭据使用受保护存储，未知字段、任意表达式和未验证服务器必须 fail closed。

### `SKILL-001` 可审计的 Skill 生命周期

Skill 只先发现和展示受限元数据；加载、批准、撤销和调用都绑定隔离 Profile 和当前 Session。
来源、权限和卸载恢复未验证时不能进入生产列表。

### `TASK-001` Agent 回合与任务投影

DSH 的 Session/turn 状态是活动事实源，Sumika 的 Tasks 只做有界只读投影，不能维护第二套
活动回合。失败、取消、审批和重试必须保留可追踪的 checkpoint 关系。

### `WORKSPACE-001` 可恢复的仓库修改

Execute 和 Plan Review 批准前创建 checkpoint；修改在独立 Workspace/worktree 中进行，用户
可查看文件级 diff、预览恢复、精确恢复和本地提交。失败清理和归档必须可恢复，不自动 push。

### `PLUGIN-001` 高度可插拔

同类型实现应能在 UI 中切换。社区插件先在隔离 Profile 中检查许可证、API、权限、卸载恢复
和端到端行为，验证通过且用户批准后才进入生产列表；Sumika 自有插件尽量可独立发布。

### `CAPABILITY-001` 统一能力实现目录

同一个功能可以由本地服务、云端 Provider、外部软件、Harness、插件、Skill 或隔离浏览器
实现。Sumika 应提供一个只读的统一目录，展示真实来源、传输方式、处理位置、状态、权限和
当前选择；目录只是各注册表的安全投影，不创建第二套路由或配置事实源。名称含 Fake、Stub
或 Placeholder 的条目，以及带有路径、Token、Cookie 或 Authorization 的元数据不得进入目录。
网页聊天候选必须明确标记为需要人工登录，不能伪装成 API Provider。

- 来源：用户关于“同一功能可由不同实现并在 UI 自由选择”的确认，结合现有模块、Provider、
  Agent 和 Browser 边界归一化。
- 验收：目录能按能力分组显示当前和可选真实实现；单个来源失败只显示受限错误；敏感字段
  和 Fake/占位项不会出现在 HTTP、RPC 或 UI 投影中。
- 当前实现：`capability-catalog` 状态行和 [Module catalog](../architecture/modules.md)。

### `DESKTOP-001` 通用桌面软件适配器

桌面软件是可替换的能力实现，不应被写死为 ZCode。Sumika 通过稳定的
`DesktopAdapter` 契约统一应用协议、Electron `CDP`、Windows `UI Automation` 和经批准的
前台接管；transport client 只负责协议调用，Core 负责生命周期和策略。

- 来源：用户要求为 ZCode 增加可复用的通用桌面软件自动化工具包，并保留未来替换实现的能力。
- 验收：任一实现可在不修改 Core/UI 策略的情况下登记；未实现的 transport 明确返回不可用，不伪造窗口操作。
- 状态证据：[桌面自动化专题](../architecture/desktop-automation.md)；当前状态参考 `desktop-automation`。

### `DESKTOP-002` 桌面操作安全边界

桌面自动化必须显式登记和批准，profile 只能被一个写入者租用，控制和敏感动作需要批准，发送
不确定时返回 `unknown`，且凭据、窗口正文、路径和全局输入不得进入持久化审计。

- 来源：用户关于使用桌面自动化操纵 ZCode、同时不影响其他工作窗口的要求，结合现有安全边界归一化。
- 验收：租约冲突、审批令牌复用、嵌套凭据和未知发送均有可重复测试；Core 关闭只清理本实例会话。
- 状态证据：[桌面自动化专题](../architecture/desktop-automation.md)；当前状态参考 `desktop-automation`。

## 浏览器、安全与可进化系统

### `BROWSER-001` 隔离浏览器能力

BrowserSkill 负责 DOM/CDP 和浏览器会话，Sumika policy companion 负责域名、敏感动作审批、
人工接管和下载 quarantine。登录、OTP、验证码、上传、下载、提交、删除、购买和权限修改
必须暂停并请求用户。凭据和人工输入不得进入聊天、模型上下文或日志。

### `SEC-001` 数据和删除安全

保留已有会话、Provider、角色、模型、依赖和归档；清理优先可恢复归档，禁止无确认的永久删除、
强制覆盖、全局重置和删除用户全局 Runtime。所有外部写入、付费动作和权限变化都要有明确授权。

### `STARTUP-001` 可预测的启动和退出

一键入口只检查和启动已经安装且版本受管的 Core、Harness 和桌面端；关闭后应释放本次实例
创建的进程和端口，不接管或终止用户外部运行的服务。

### `LICENSE-001` 来源可审计

外部代码、模型、动画、图标和行为参考记录 URL、固定版本、许可证、使用方式和修改说明。
无法确认独立授权的模型或动画只可作为行为参考，不复制或打包。

### `OBS-001` 面向 Agent 的可读调试

运行日志应是有界、脱敏、机器可聚合的 JSONL，记录阶段、耗时、结果、资源和不透明关联标识，
不记录 Prompt、模型输出、工具参数、文件内容、凭据或 Cookie。日聚合可用于发现 bug、比较
插件/模型，但不能凭少量或不可比样本自动改变生产配置。

### `EVOLUTION-001` 受控知识登记

DSH、Codex、BrowserSkill、记忆系统榜单、Provider 免费额度来源和类似项目进入独立 Registry，
记录固定版本、能力、许可证、检查时间和评估结论。自动发现和隔离评测可以无人值守，安装、
升级、启用和路由变化仍需用户批准。

## 多角色与延期边界

### `MEMORY-001` 可替换的角色记忆

记忆是可选、角色或 Agent 作用域的 Provider capability；不同记忆实现可以在 UI 中替换和
比较。共享记忆、多角色互聊和自动合并确认仍需独立策略，不能默认发生。

### `MULTI-001` 多角色预留

未来一个场景可包含多个角色，每个角色保持独立 `character_id`、persona、DSH Session、记忆
命名空间、模型策略和预算；临时参与关系用 `InteractionContext`，空间位置用 `WorldLocation`。
本阶段不实现自动互聊、共享长期记忆或主动发言调度。

### `DEFERRED-001` 明确延期能力

真实 ASR/TTS/VAD、视觉捕获、Live2D 新驱动、VRMA/MMD 动作库、VirtualWorld、LifeAgent、
RemoteRunner、Android 和正式多平台安装发布，必须等真实运行模块和安全边界完成后再加入。

## 历史取代关系

| 早期意图 | 后续决定 | 处理方式 |
| --- | --- | --- |
| `HISTORY-OLLAMA-DEFAULT`：自动安装并拉取 Ollama/qwen3 | 用户自行选择、安装和启用模型 | 保留历史记录，标为 `superseded` |
| 把 DSH 当作整个 Core 的底层 | 使用 Runtime-neutral `AgentRuntime` adapter | 保留 DSH 默认实现，禁止 UI/Core 私有耦合 |
| 直接复用外部 CCS/插件内部结构 | 只使用版本化导入协议和隔离适配器 | 未支持字段不可执行 |
| 把模型速度作为唯一选择依据 | 先满足质量/安全门槛，再比较成本和额度 | 由 `model-policy/v1` 约束 |

## 基线使用方式

重构前生成受影响需求 ID 清单；重构后逐条关联代码、测试、迁移和恢复证据。只有经过
实际测试的行为才可在状态矩阵标为 `已实现`。需求意图改变时新增 supersession 关系，
不要删除旧记录。
