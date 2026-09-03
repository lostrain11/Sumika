# Sumika 当前执行契约

本页只用于恢复当前开发目标和下一步，不是功能状态或完整架构的事实源。
功能状态以 [状态矩阵](status-matrix.md) 为准，接口和约束以对应专题文档为准。

## 目标

在当前 Windows 开发环境中，把 Sumika 完成到可以一键启动并承担日常代码仓库工作的程度，同时保留首版角色、Avatar、桌宠和本地数据能力。

## Definition of Done

- 从一个明确入口检查并启动 Agent Runtime、Python Core 和 Tauri 客户端；
- 可选择真实仓库并使用 Plan、Execute、工具、审批、MCP、Skills 和 Subagents；Readonly 只在 Runtime 提供可验证策略 capability 后显示；
- 每个 Execute 回合自动创建 checkpoint，之后可查看 diff 并精确恢复；
- 隔离浏览器支持真实连接、人工接管、敏感动作审批和下载 quarantine；
- DSH、Provider、工具或浏览器不可用时明确失败，不生成 Fake 结果；
- 使用独立 worktree 由 Sumika 完成一次 Sumika 自身改动并通过完整回归；
- 关闭客户端后不遗留由本次实例启动的受管进程。

## 当前基线

- Branch: `codex/dsh-agent-runtime`
- Baseline commit: `05d511f` (当前 `HEAD`；场景外壳重置与远景入库已完成；工作树仅剩范围外未跟踪产物)
- Last verified commit: working tree on 2026-09-03；固定 DSH `0.1.1-rc.2` 的 PowerShell/Tauri 双重版本校验、受管进程链、协议健康检查和隔离 Plan→Execute/Workspace 恢复冒烟均通过。A user-started ZCode Electron instance was read-only smoke-tested through its explicit loopback CDP endpoint on 2026-08-31; no message, form value, credential, target creation, or window close was performed.
- Runtime: DSH `0.1.1-rc.2` through the runtime-neutral `AgentRuntime` adapter; optional ZCode adapter probes the installed public `app-server --stdio` wire (`session/list`, no `jsonrpc` member) and retains a legacy JSON-RPC compatibility path.
- Status source: [status-matrix.md](status-matrix.md)
- Runtime design: [Agent Runtime](architecture/agent-runtime.md)
- DSH integration: [DSH Agent](integrations/dsh-agent.md)
- Requirements: [baseline](requirements/README.md) and [model policy](requirements/model-policy.md)

Existing untracked `example.txt`, `output/`, and `test-results/` are outside the approved development scope and must not be staged, moved, overwritten, or removed.

## 当前里程碑

**场景优先 UI 外壳重置（实现与回归完成，2026-09-04）**

Phase 0、1、2 和 3 均已完成；本轮完成客户端 UI 彻底重置第一期（场景优先外壳）与网页门户，Phase 4 仍不开始。客户端从 11 页签工作台改为「全屏场景视口 + 4 抽屉」：Avatar 占屏 60%+ 常驻（WebGL 跨导航不卸载）、气泡流 + galgame 对白框输入、工作台/角色/模块/设置四个全屏抽屉（Esc/✕ 回场景）、竖排 dock 常驻抽屉之上、桌宠浮窗同款对白框。配色开源中立（夜蓝 + Sumika 自有薄荷强调色，不绑定任何版权角色）；每角色 `theme.accent` 由角色卡导入自动读取（`extensions.theme_color`），`color-mix` 派生全套色调；模块页启用「＋ 添加模块」折叠网格；设置页做实（背景色板/本地背景图/真实数据目录/快照）；首用欢迎卡替代常驻指南页。**网页门户**：dock 第 5 图标（仅桌面版），Kimi/ChatGPT/智谱/DeepSeek/Qwen/豆包各开独立 Tauri WebviewWindow，登录存 `.sumika-desktop/portals/<站点>/`（重启持久、站点 Cookie 隔离），支持自定义站点（localStorage）；原始站点无 persona 注入，与 BrowserSkill 网页 Route 完全隔离。分层模型借鉴 amica、抽屉结构借鉴 Open-LLM-VTuber-Web、气泡借鉴 ChatVRM（三者 MIT，仅移植交互模式并全部以 Sumika token 重新表达，无文件复制，登记于 license-ledger）。Playwright 50/50、后端 576/576、cargo 8/8、build、check_docs 全绿。

**固定 DSH 主 Agent 启动闭环（实现与实机验收完成，2026-09-03）**

Phase 0、1、2 和 3 均已完成；本轮完成固定 DSH 启动链的 fail-closed 校验和真实 Windows 进程闭环，Phase 4 仍不开始。

固定版 DSH 没有独立 live `mcp.list`、Readonly policy、composition 写入、artifact 或 rollback RPC。Sumika 对这些边界明确返回 `not-exposed` 或由自身 WorkspaceRuntime 补足，不伪造能力，也不进入 Phase 4。

本轮启动闭环已验证：`tools/run-desktop.ps1 -NoBuild` 只接受固定或显式精确版本的 DSH，Tauri 在配置生成和 spawn 前再次核验；Core `8771`、DSH `3080`、`/api/health`、`/api/agent/status`、`/api/agent/diagnostics`、`host.describe` 和 `session/list` 均可用。
隔离 `Plan→Execute`、审批、工具、checkpoint、diff 和精确恢复通过；真实 Provider 预检仍可能为 `needs-action`，本轮没有发送真实高价请求。

本轮（2026-09-03）已提交 ChatGPT 网页适配器回归修复（`0aadb99`）：声明当前一代 ChatGPT composer/响应选择器（`textarea[data-composer-draft-react]`、`button[data-composer-submit]`、`[data-assistant-markdown]`、`[data-message-role='assistant']`，保留旧 `#prompt-textarea` 优先）；授权标记扩充无引号“打开个人资料菜单”“账户菜单”"Account menu"；HTML 投影属性白名单新增 `aria-label`、`placeholder`、`contenteditable` 等；`send_message` 在输入框裁剪基线之外新增独立页面级视觉基线 `visual_page_baseline_id`，超时诊断改为对比页面基线，避免输入框裁剪掩盖页面上可见的助手回复。相关 83 个测试（`test_web_chat`、`test_browser_runtime`、`test_web_chat_server`）通过。

本轮（2026-09-03）已提交社区角色卡导入能力（`c5612aa`）：新增 `sumika_core/character_import.py`，对齐 SillyTavern 社区规范（`character-card-spec-v2`、CCv3/CHARX），支持 V1 扁平卡、`chara_card_v2`、`chara_card_v3` 与 JSON/PNG（tEXt `chara`/`ccv3`）/CHARX（zip `card.json`）容器，stdlib 实现、零依赖；通用字段映射（identity←description、traits←personality、relationship←scenario、system_prompt←system_prompt、greeting←first_mes，`mes_example` 在上限内以"示例对话"并入），`{{char}}`/`{{user}}` 占位符确定性替换，超限 fail-closed 不静默截断；原始卡与导入元数据保留在 `config.card_import`（世界书不注入运行时，条目保留）。新增 `character.import_card` RPC（同名需 `overwrite`、广播 `character.changed`）、角色页"导入角色卡"入口和 `tools/import_character_card.py` 离线 CLI。安和昴（GIRLS BAND CRY）角色卡已从 `D:\Code\安和昴角色卡项目\交付\安和昴_ST_V2.json` 导入 `.sumika-desktop`（9 条世界书保留未注入），随后并入默认 `sumika` 记录成为默认角色（见下段）；Agent/DSH 通道 persona 投影仍为后续目标，设计钩子已记录在 [characters.md](architecture/characters.md)（参照 `dsh-browser-policy` 的 `ctx.skills.register` 模式，须走社区插件隔离验证 + 用户批准流程）。

随后（同日）应用户要求把默认角色切换为安和昴：默认锚点记录 `sumika`（`_ensure_defaults` 仅在角色表为空时播种，重启后保留）已改名并写入角色卡 persona 与 `card_import`；原默认角色"Saki"的配置备份在 `.sumika-desktop/saki-config-backup.json`（未跟踪）；独立的重复导入行已删除。486desu 免费配布的同人 VRM `awa subaru（增加校徽）.vrm`（16.5 MB）已复制到 `.sumika-desktop/avatar-models/`（本地数据目录，不进 git；作者条款见其发布帖 BV1if421B7MH，使用前需遵守）并经 `avatar.import`/`avatar.select` 绑定为 `driver=vrm`。旧默认 `AvatarSample_A.vrm` 已通过 `avatar.unregister` 注销并自动进入发现忽略清单；仓库内置文件保留（供全新数据目录首次播种），不影响本实例。运维记录：桌面窗口关闭后受管 DSH 可能残留监听 3080，导致再次启动 fail-closed 拒绝（版本无法从 `host.describe` 验证），需先结束残留 node 进程再启动。另：网页 Route 首次发送若报 `隔离浏览器不可用`，按顺序排查——① 浏览器扩展未连接（`bsk doctor` 应显示 browsers connected ≥1，否则运行 `tools/setup-browserskill.ps1 -LaunchAgentBrowser`）；② Core 重启前遗留的命名 Profile 租约（`browser_profile_leases` 表，TTL 30 分钟，旧 owner 进程已死时可手动清除）；③ `profile.open` 在 `awaiting-extension` 期间产生的 `awaiting-browser-backend` 占位会话需 close 后重开。2026-09-03 傍晚已按此链路恢复 Kimi 网页 Route（check: ready/page_ready/authorized）。

## 接下来的三个动作

1. 后续启动统一使用 `tools/run-desktop.ps1 -NoBuild`；网页 Route 发消息前还需受管 Edge Agent Window 在线：运行 `tools/setup-browserskill.ps1 -LaunchAgentBrowser` 打开它，`browser.status` 变为 `ready` 后网页聊天才可用（窗口关闭或应用重启后需重新执行）；若预检显示 `provider=needs-action`，由用户单独授权并重新健康检查。
2. 在日用会话中使用安和昴角色设定（聊天通道 persona 已生效，场景壳下可直接体验新 UI），并继续逐站用 DOM/ARIA、HTML projection 与 OCR 修通真实网页发送和回复提取，优先解决 ChatGPT 的回复定位。
3. UI 重置后续轮次（按需排期）：聊天上下文装配（世界书关键词注入 + 记忆分层）、工作台项目分组的会话绑定后端、背景视频/网页壁纸层；Agent/DSH 通道 persona 投影仍为后续任务（见 characters.md 设计钩子）。五站 `3 + 2` 聚合验收继续按既有口径执行。

## 固定决策

- DSH 是默认 Harness，但不是 Core、UI、角色、Avatar、任务或 Workspace 的基类。
- DSH Session、Plan、Skills、Subagents 和审批是活动状态的事实源。
- MCP 使用用户 Preset 和 `dsh-mcp-client`；配置、凭据和启停仍由 Sumika 审批。
- DSH 没有可靠 rollback RPC，因此 checkpoint、diff 和恢复由独立 `WorkspaceRuntime` 负责，并通过工具暴露给 Harness。
- 社区插件必须在隔离 Profile 中验证许可证、API、权限和卸载恢复后才能启用。
- 一键启动只复用和检查用户已安装的固定 Runtime，不自动安装或更新软件。
- 模型策略使用 `model-policy/v1`；`difficulty=auto` 目前是保守规则，ZCode 额度只有在公开 app-server capability 存在时才读取，未知额度不得标为免费。ZCode adapter 默认 `SUMIKA_ZCODE_PROTOCOL=auto`，可用 `SUMIKA_ZCODE_NODE` + `SUMIKA_ZCODE_SCRIPT` 配置 Node 打包入口，或显式开启 `SUMIKA_ZCODE_AUTODISCOVER=1` 解析公开 bundle；不读取 ZCode 私有配置。
- 路由默认推荐后确认；无候选、未确认、额度耗尽或健康失败时，Session、Provider 绑定和 Execute checkpoint 均不得先行创建。
- 正式文件修改只发生在独立 worktree、分支或等价的可恢复 Workspace 中。
- 完整客户端只能通过已验证的固定 DSH 启动链；Core-only 调试不继承 PATH 中的全局 DSH。

## 明确暂缓

- 音频、视觉、Live2D 新驱动；
- 多角色自动互聊、VirtualWorld 和 LifeAgent；
- RemoteRunner、Android、macOS/Linux 正式桌面发布；
- 正式安装器、自动更新和代码签名；
- 自动安装、升级或启用第三方插件；完整日用遥测采集器等 Agent 闭环稳定后再实现。

## 当前阻塞

- 隔离 Ollama（`127.0.0.1:11435`）现在可见 `qwen3:1.7b`（约 1.36 GB）和 `qwen3:4b`（约 2.50 GB）；1.7B 仅用于快速协议/UI 冒烟，4B 保持 DSH 默认。用户原有 `127.0.0.1:11434` 服务未停止，也没有被改写。
- 1.7B 的直接 OpenAI-compatible 请求已通过，但在标准 DSH 工具目录下工具选择和长推理质量不足；不能把“能响应”当作 Codex 日用 Agent 验收通过。
- 真实 Provider 若缺少凭据必须请用户重新输入，不得从 SQLite、日志或聊天恢复；安全启动注入已实现，模型质量仍待持续对照评估。
- 上一次隔离验收中，BrowserSkill CLI `0.1.11`、受管 Edge Agent profile 和 `ext-v0.1.7` 的 protocol 1.1 检查均通过，自动读写 smoke 已通过；人工接管请求因本轮没有用户操作而超时。DeepSeek、ChatGPT、智谱、Qwen 与 Kimi 网页 Route 于 2026-09-02 完成人工登录、页面检查、`chat.read`/`chat.send` 长期普通文本授权，并在 Core 目录中验证为 `routable=true`。Kimi 单站真实咨询已完成；ChatGPT 已有页面提交证据，但回复 DOM 提取在 300 秒后以 `deadline-exceeded` 结束且未重发，因此五站整体验收仍未通过。测试后 Core `8771` 已停止且 BrowserSkill 活动 session 为 0；豆包和敏感写操作仍需用户在明确任务中授权。网页额度仍为 `unknown`。
- 隔离 SSE stub 已验证 DSH 协议，但不会替代真实模型；真实模型复杂任务质量仍需用户主动配置 Provider 后单独评估，Sumika 不读取历史密钥或自动安装模型。
- 真实 ZCode CDP 只读 smoke 已于 2026-08-31 通过：`http://127.0.0.1:9222` 返回 Electron 版本信息，发现 1 个 page target（标题 `ZCode`），页面 `readyState=complete`；观察请求关闭正文读取，仅保留标题、URL scheme 和控件计数。端口和用户实例在 smoke 后仍保持运行。尚未验证发送、填写、登录或任何敏感动作。

## 验证记录

当前工作树已通过：

- Python unittest: 576 tests；Tools unittest: 58 tests；Playwright: 50 tests（50 passed；UI 重置后选择器全面更新为场景壳导航，含 retry、worktree/commit、队列重绘草稿、Session 恢复、会话级控制重载、历史游标翻页、网页聊天配置抽屉、模型策略推荐/确认，以及 Plan Review 三种操作）；
- `node --check frontend/main.js`;
- frontend production build;
- `cargo check --manifest-path src-tauri/Cargo.toml` and `cargo test --manifest-path src-tauri/Cargo.toml` (6 passed);
- `python tools/check_docs.py`;
- `tools/dsh-launch.ps1` and `tools/run-desktop.ps1` PowerShell parse checks；`tools/test_dsh_launch.ps1` passed；DSH route bridge、desktop automation 和 browser policy plugins passed 19 Node tests；Python `compileall` passed；
- `git diff --check`；
- 隔离 `python tools/agent_daily_acceptance.py --runtime-smoke`：Plan Review、批准、Execute、工具、checkpoint/diff/精确恢复均通过；整体预检为 `needs-action` 仅因真实 Provider 未授权。
- `backend/tests/test_cdp_transport.py`: 4 项专项测试通过；
- 真实 ZCode CDP smoke（2026-08-31）：`health`、已有 `ZCode` page `open`、`observe(include_text=false)` 和 runner 断开通过；端口仍监听且 page target 数量未增加。
- BrowserSkill 实机：CLI `0.1.11` 与官方 `ext-v0.1.7` 的 SHA-256、daemon、扩展和 browser protocol 检查均通过；Sumika policy companion 已安装到受管 DSH profile，并完成 `browser-skill` 加载、隔离 session、只读导航、导航审批、ARIA snapshot、本地非敏感表单写入和 session stop；测试后无活动 BrowserSkill session，隔离 DSH 端口已释放。DeepSeek、ChatGPT、智谱、Qwen 与 Kimi 网页 Route 的人工登录、页面检查和普通文本授权已于 2026-09-02 验证为可路由；Kimi 单站真实咨询完成，ChatGPT 回复提取超时且未重发，五站聚合仍待完整通过。
- `tools/agent_daily_acceptance.py` 与 `--plan-execute` smoke 已完成语法检查；新的隔离 DSH `127.0.0.1:3100` profile 在 2026-08-29 通过 `--runtime-smoke --mcp --skills-subagents` 组合验收，包含 Plan→Execute、MCP、审批、diff、恢复、Skills 和 Subagents；BrowserSkill 读写组合回合也已通过。真实 Provider 的既有 Session 可用 `--real-session` 只读纳入报告，复杂任务质量仍待对照。
- WorkspaceRuntime 专项：checkpoint/恢复、状态截断、冲突/rename、worktree、patch 和精确 commit；独立 worktree 已由 DSH 完成受控文档自修改并通过 diff、恢复和本地 commit（`10ff976`）；Workspace UI：创建预览、双重确认、文本 patch、本地提交和归档路径脱敏。
Windows launcher 另以真实进程验证三条分支：复用或监督固定版 DSH，以及 DSH 缺失时 Agent fail closed；各次退出后 `3080`、`3081`、`8770`、`8771` 均释放，用户的 Ollama `11434` 未被停止。
Agent 命令闭环已验证：Session 创建后重新读取 command catalog；无 `plan` 命令的 Preset
仍可普通 Execute，只有活动 Plan 显式切换到 Execute 才发送 `/plan off`。
固定 DSH 协议 smoke 已验证 25 个工具 schema、流式请求、最终消息、完成状态和 WebSocket
事件；隔离 Workspace 的 `read/question/pwsh/edit`、命令审批、文件级 diff、恢复预览和
精确恢复均已通过。嵌套 `tool-result` 可按 `callId` 关联且丢弃原始正文；Agent Task 投影、
retry 边界、正文过滤和 Workspace checkpoint 已通过后端与 Playwright。Provider 被动目录
检查会在 Agent 状态、会话创建、模块启用、模块列表和发送前运行，端点停止会阻断请求。
真实 `glm-4.5-air` 已通过只读、`workspace-write + ask` 权限审计和 Plan Review 批准前
checkpoint 的单文件写入/精确恢复回合；统一报告验证 checkpoint 早于批准、回合完成、
唯一文件 diff、恢复预览和精确恢复，且不包含 Session ID、路径或正文。模型在更复杂任务中的规划、工具选择和错误恢复质量仍待持续评估。

Preset mount validation 已通过固定 DSH 实机验证；无鉴权 stdio MCP smoke 完成
`initialize`、工具发现、模型调用和结果回传，MCP 自定义凭据使用 Credential Manager、
固定 `process.env` 表达式和重启门控。带真实第三方密钥的端到端 smoke 仍需用户明确配置。

Provider 与 MCP 密钥只保存在 Windows Credential Manager；桌面 helper 通过私有 NUL v2 协议注入受管 DSH 启动环境。Python/Rust/UI 隔离和真实 Provider 只读回合曾通过隔离验收；当前 Provider 是否可用必须以最新 preflight/health 结果为准。

ZCode app-server 适配器已通过隔离现代 wire fixture：工作区 session、Provider/`available` 模型目录、MCP 状态、子 Agent、事件归一化、运行时偏好应答、短模型选择和完整 `runtimeModel` 校验；现代能力不再宣称 `readonly`、附件或队列。现有标准 JSON-RPC fixture 仍通过 `auto` 探测回归；真实 ZCode 自动发现实测可读到 2 个模型（`glm-5.1`、`glm-4.7`），公开额度接口未提供，保持 `unknown`。

Agent observability 已接入 Core RPC/DSH event 边界：`.sumika*/logs/agent-observability/` 只写 bounded JSONL receipt，按 UTC 日输出 p50/p95 与结果/资源汇总；不写提示词、模型输出、工具参数/结果、文件内容、凭据或 Cookie。`python tools/aggregate_agent_day.py --write` 可离线生成摘要；`agent.acceptance.evidence` 与 `--real-session` 可把既有真实闭环投影为布尔值、计数、枚举和耗时。模型策略基础 catalog、确定性难度推断、额度 TTL、固定评测任务集和推荐前确认已通过 2026-08-30 回归；长期样本质量判定、学习型分类器和自动路由仍未实现。

Skills/Subagents 专项：隔离 `.agents/skills` fixture 已被 `skill.list` 发现，`/sumika-smoke` 正文注入已确认；DSH `subagent` 已创建 one-shot 子 Agent，`subagent.list/history` 可读其摘要。该专项只使用隔离 Profile 和测试 Provider，不改变生产会话；可由 `tools/agent_daily_acceptance.py --runtime-smoke --skills-subagents` 重复执行，报告仅保留布尔值和计数。
未执行：`cargo fmt --check`，因为当前工具链没有 `rustfmt`；不得为此静默安装组件。

## 恢复顺序

1. 完整读取本页；
2. 读取状态矩阵中当前里程碑涉及的条目；
3. 检查 Git root、branch、HEAD、remote 和工作树；
4. 读取当前里程碑链接的专题文档、需求基线和相邻测试；
5. 从“接下来的三个动作”继续，并用仓库和运行时证据校验本页内容。

若本页与 Git、测试、状态矩阵或真实运行时冲突，以可复现证据为准，并在继续实现前修正本页。

## 更新规则

- 只在里程碑开始、完成、出现阻塞或切换分支时更新；
- 保持在 150 行以内，不复制专题文档或聊天过程；
- 不记录 API Key、Token、聊天正文、用户目录、临时日志或认证信息；
- 每次更新都同步当前里程碑、三个动作、阻塞和验证记录；功能完成度只更新状态矩阵，本页不得创建第二套状态定义。
