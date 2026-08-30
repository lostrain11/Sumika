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
- Baseline commit: `b005c3f41cf712a2183bb0c9d711f1638f63d2f0`
- Last verified commit: `133bc90`; current worktree additionally contains the WorkspaceRuntime safety/commit bridge, Execute and Plan-approval checkpoint protection, DSH protocol/MCP credential bridge, Agent task projection with bounded turn ledger, BrowserSkill launcher discovery, bounded usage/context presentation, content-independent Agent observability sink/daily aggregator, the unified capability catalog projection with source-failure reporting, the `model-policy/v1` catalog/router, ZCode global-model/quota hooks, TTL observations, confirmation-gated Agent integration, the `web-chat/v1` BrowserSkill profile adapters with fail-closed snapshot handling, and the runtime-neutral desktop automation contracts/DSH bridge (verified in the current worktree on 2026-08-31)
- Runtime: DSH `0.1.1-rc.2` through the runtime-neutral `AgentRuntime` adapter; optional ZCode adapter probes the installed public `app-server --stdio` wire (`session/list`, no `jsonrpc` member) and retains a legacy JSON-RPC compatibility path.
- Status source: [status-matrix.md](status-matrix.md)
- Runtime design: [Agent Runtime](architecture/agent-runtime.md)
- DSH integration: [DSH Agent](integrations/dsh-agent.md)
- Requirements: [baseline](requirements/README.md) and [model policy](requirements/model-policy.md)

Existing untracked `example.txt`, `output/`, and `test-results/` are outside the approved development scope and must not be staged, moved, overwritten, or removed.

## 当前里程碑

**Phase 3 后续 - 模型策略与额度边界（基础闭环已实现，2026-08-30）**

Phase 0、1、2 和 3 均已完成；本次恢复只补充模型策略的基础路由、公开模型目录和保守额度观测，Phase 4 仍不开始。

Phase 0 已完成：执行契约、固定恢复顺序和文档检查边界；WorkspaceRuntime 的检查、checkpoint、diff、恢复、worktree、patch 审阅和本地 commit 已接入 Agent 页。Phase 1 已完成：固定 DSH `0.1.1-rc.2` 的启动、健康检查、Provider route 桥接和安全凭据注入；隔离 OpenAI-compatible SSE stub 已通过 Session、模型选择、prompt、事件和最终 snapshot 协议闭环。

Phase 2 已完成：DSH Session、Plan、Execute、工具、审批、队列、历史游标、Subagents、Workspace diff/恢复、失败回合重试、任务投影和 BrowserSkill 策略边界均可由 Agent 页或维护脚本重复验收。Execute 与 Plan Review 批准前会创建 checkpoint；旧 `tasks` 表不承载 DSH 活动状态。

Phase 3 已完成：Provider/MCP 凭据隔离、Preset copy/open/remove/restore、MCP preview/apply、mount validation、stdio/HTTP 配置、Skill metadata discover/approve/revoke、Plugin manifest discovery/approval/provider boundary 均已实现。固定 DSH 的组合验收已通过 Plan Review、MCP `initialize/tools/list/tools/call`、Skill discover/load、Subagent 创建/历史读取、Workspace diff 和精确恢复；报告只保留有界布尔值、计数和状态。

固定版 DSH 没有独立 live `mcp.list`、Readonly policy、composition 写入、artifact 或 rollback RPC。Sumika 对这些边界明确返回 `not-exposed` 或由自身 WorkspaceRuntime 补足，不伪造能力，也不进入 Phase 4。

## 接下来的三个动作

1. 模型策略、网页聊天适配器与固定评测器的 Python、前端、Rust、文档和敏感信息回归已通过；保持当前工作树改动可追踪。
2. 在用户明确授权的环境中分别运行 ZCode、智谱和 Ollama 的只读 preflight；只记录健康/额度状态，不恢复或输出凭据。ZCode 自动发现已通过，本机模型目录可读，额度仍为 `unknown`。
3. 用 `tools/fixtures/model-evaluation-v1.json` 收集首批隔离样本并复核 cohort；继续保持推荐后确认，不自动切换生产路由。

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
- 上一次隔离验收中，BrowserSkill CLI `0.1.11`、受管 Edge Agent profile 和 `ext-v0.1.7` 的 protocol 1.1 检查均通过，自动读写 smoke 已通过；人工接管请求因本轮没有用户操作而超时。当前 `8772` 实例的最新 `browser.status` 报告为 CLI 未发现、Provider `phase1-test-ollama-1p7b` 不可用，因此不能把历史验收当作当前就绪状态；真实登录审批和写操作仍需用户在明确任务中授权。
- 隔离 SSE stub 已验证 DSH 协议，但不会替代真实模型；真实模型复杂任务质量仍需用户主动配置 Provider 后单独评估，Sumika 不读取历史密钥或自动安装模型。

## 验证记录

当前工作树已通过：

- Python unittest: 383 tests（含 retry、凭据桥接、WorkspaceRuntime、历史游标、usage/context 投影、turn ledger、Agent observability sink/日聚合、Provider 端点停止后的被动健康刷新、模型策略和 ZCode quota/目录、现代 runtimeModel 校验、网页聊天登录/授权/归档/回复与快照边界，以及 Plan Review 回答/取消协议）；
- Playwright: 47 tests（含 retry、worktree/commit、队列重绘草稿、Session 恢复、会话级控制重载、历史游标翻页、网页聊天配置抽屉、模型策略推荐/确认，以及 Plan Review 三种操作）；
- `node --check frontend/main.js`;
- frontend production build;
- `cargo check --manifest-path src-tauri/Cargo.toml`;
- `python tools/check_docs.py`;
- all `tools/*.ps1` PowerShell parser checks;
- `git diff --check`；
- BrowserSkill 实机：CLI `0.1.11` 与官方 `ext-v0.1.7` 发布包 SHA-256 校验通过；
  daemon、扩展和 browser protocol 检查均通过。Sumika policy companion 已以内容指纹化 tarball
  安装到受管 DSH profile；新启动的固定 DSH `0.1.1-rc.2` 已完成
  `browser-skill` 加载、隔离 session、`example.com` 只读导航、一次导航审批、ARIA snapshot
  和 session stop；另完成本地非敏感表单写入、提交和 3 次审批。`tools/agent_daily_acceptance.py`
  的 `--browser-smoke --browser-write-smoke` 已将两项纳入统一安全报告；测试后无活动 BrowserSkill
  session，隔离 DSH 端口已释放。人工接管、登录和真实账号写操作仍待用户授权。
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

Skills/Subagents 专项：隔离工作区中的 `.agents/skills` fixture 已被 `skill.list` 发现，
`/sumika-smoke` 的正文注入已在 OpenAI-compatible stub 请求中确认；DSH `subagent`
工具已创建 one-shot 子 Agent，`subagent.list` 返回其直接子级及模式，
`subagent.history` 可读取子会话摘要。该专项只使用隔离 Profile 和测试 Provider，
不改变生产会话；可由 `tools/agent_daily_acceptance.py --runtime-smoke --skills-subagents`
重复执行，报告仅保留布尔值和计数。
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
