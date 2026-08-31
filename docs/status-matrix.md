# Sumika 状态矩阵

本表是项目功能状态的唯一事实源。`已实现` 表示当前首版有可验证入口，
`部分实现` 表示协议或参考实现存在但默认能力、真实后端或隔离边界仍缺失，
`规划中` 表示只保留架构位置或设计方向。

| ID | 状态 | 当前入口 | 主文档 | 验证证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `local-llm` | 已实现 | Modules > 自定义连接（默认关闭）；隔离测试可选 `qwen3:1.7b`，日常默认保持用户选择 | [local-model](architecture/local-model.md) | [setup script](../tools/setup-ollama.ps1)、[provider tests](../backend/tests/test_providers.py)、[DSH smoke](../tools/smoke_dsh_round.py) | 原生 macOS/Linux 启动器与更多本地运行时验证 |
| `provider-profiles` | 已实现 | Modules > 实现方式 | [provider profiles](architecture/provider-profiles.md) | [profile tests](../backend/tests/test_provider_profiles.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 增加更多已测试协议适配器 |
| `ccswitch-import` | 已实现 | Modules > 自定义连接、Developer | [CC Switch](integrations/cc-switch.md) | [compatibility tests](../backend/tests/test_ccswitch_compatibility.py)、[checker](../tools/check_ccswitch_compatibility.py) | 按固定基线人工审查上游更新 |
| `chat` | 已实现 | Chat | [protocol](architecture/protocol.md) | [server tests](../backend/tests/test_server.py)、[frontend shell](../frontend/main.js) | 持续完善流式状态与错误呈现 |
| `characters` | 已实现 | Characters（身份 / 人格 / 高级设置） | [characters](architecture/characters.md) | [persona tests](../backend/tests/test_persona.py)、[server tests](../backend/tests/test_server.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 角色导入，以及真实音频/立绘运行时完成后的对应配置 |
| `modules` | 已实现 | Modules | [modules](architecture/modules.md) | [module tests](../backend/tests/test_modules.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 继续增加真实可替换实现 |
| `capability-catalog` | 已实现 | Modules > 统一能力目录、Developer > 统一能力目录 | [modules](architecture/modules.md) | [catalog implementation](../backend/src/sumika_core/capabilities.py)、[catalog tests](../backend/tests/test_capabilities.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 接入第二个真实 Harness/插件后继续验证跨运行时和同类实现对比 |
| `desktop-automation` | 部分实现 | Developer > capability catalog；DSH 可选 `desktop_app_*` bridge；显式 `enable_cdp` 后可连接 loopback Electron CDP | [desktop automation](architecture/desktop-automation.md) | [contracts](../backend/src/sumika_core/desktop_automation/contracts.py)、[runtime](../backend/src/sumika_core/desktop_automation/runtime.py)、[adapter tests](../backend/tests/test_desktop_automation.py)、[CDP transport tests](../backend/tests/test_cdp_transport.py)、[DSH bridge](../plugins/dsh-desktop-automation/README.md)、[policy tests](../plugins/dsh-desktop-automation/test/policy.test.mjs)；2026-08-31 用户启动的 ZCode Electron `9222` 已通过 `health`、已有 page target `open` 和不读正文的 `observe` smoke | 继续在明确动作审批下验证受限 click/fill/send；保持应用登记、租约、敏感输入隔离和前台接管默认关闭，不把只读 smoke 扩大为登录或真实消息发送 |
| `model-policy` | 部分实现 | Agent > 模型策略；`model.policy.*` RPC | [model policy](requirements/model-policy.md) | [policy implementation](../backend/src/sumika_core/model_policy.py)、[evaluation implementation](../backend/src/sumika_core/model_evaluation.py)、[policy tests](../backend/tests/test_model_policy.py)、[evaluation tests](../backend/tests/test_model_evaluation.py)、[Agent route tests](../backend/tests/test_agent_server.py)、[ZCode tests](../backend/tests/test_zcode_runtime.py)、[UI smoke](../frontend/tests/smoke.spec.js)；ZCode modern wire fixture 覆盖 `session/list`、workspace model catalog、MCP 和事件；Windows 自动发现实测读取 2 个 Z.AI 模型，公开额度仍为 `unknown` | 接入真实 ZCode/Provider 额度来源、积累固定评测样本并校准质量评分；保持推荐后确认与禁止静默付费切换 |
| `tasks` | 部分实现 | Tasks、Agent > Workspace 安全与回滚 | [tasks](architecture/tasks.md) | [task tests](../backend/tests/test_tasks.py)、[runner tests](../backend/tests/test_task_runner.py)、[WorkspaceRuntime tests](../backend/tests/test_workspace_runtime.py)、[Agent server tests](../backend/tests/test_agent_server.py)、[Playwright smoke](../frontend/tests/smoke.spec.js)、[daily acceptance](../tools/agent_daily_acceptance.py) | Execute 与 Plan Review 批准前 checkpoint、独立 worktree、patch 审阅、审批式本地 commit、turn/产物只读投影和 Sumika 自修改/恢复已闭环；真实 Provider 结果已进入重复验收，继续完成小型实际改动和浏览器人工接管 |
| `avatar-vrm-desktop` | 已实现 | Chat、Characters、透明桌宠模式 | [Avatar](architecture/avatar.md)、[desktop shell](architecture/desktop-shell.md) | [avatar tests](../backend/tests/test_avatar.py)、[UI smoke](../frontend/tests/smoke.spec.js) | Live2D 驱动与更多动作资源审计 |
| `plugins-manifest` | 部分实现 | Developer | [manifest](architecture/manifest.md) | [plugin tests](../backend/tests/test_plugins.py) | 隔离 Runner、签名与依赖管理 |
| `audio` | 部分实现 | Modules（默认关闭） | [audio](architecture/audio.md) | [audio tests](../backend/tests/test_audio.py) | 接入真实 ASR/TTS/VAD 软件并完善权限 UI |
| `memory` | 部分实现 | History / Modules（默认关闭） | [memory](architecture/memory.md) | [memory tests](../backend/tests/test_memory.py) | 检索策略、合并确认与更多外部后端 |
| `vision` | 部分实现 | Modules（默认关闭） | [vision](architecture/vision.md) | [vision tests](../backend/tests/test_vision.py) | Tauri 捕获桥与敏感性路由策略 |
| `snapshots` | 已实现 | Developer / History | [architecture](architecture/README.md) | [storage tests](../backend/tests/test_storage.py)、[server tests](../backend/tests/test_server.py) | 加密备份与更细的恢复预览 |
| `live2d` | 规划中 | 暂无 | [Avatar](architecture/avatar.md) | [reference map](ui/reference-map.md) | 选择运行时、资源导入和许可证边界 |
| `virtual-world` | 规划中 | 暂无 | [architecture](architecture/README.md) | [architecture index](architecture/README.md) | 先定义场景状态与时间结算模型 |
| `life-agent` | 规划中 | 暂无 | [tasks](architecture/tasks.md) | [tasks design](architecture/tasks.md) | 与 VirtualWorld 分离设计日程和主动性 |
| `remote-runner` | 规划中 | 暂无 | [security](architecture/security.md) | [tools boundary](architecture/tools.md) | 隔离执行、权限和回滚协议 |
| `android-client` | 规划中 | 暂无 | [desktop shell](architecture/desktop-shell.md) | [protocol](architecture/protocol.md) | 配对、认证和远程事件通道 |
| `agent-runtime-portability` | 已实现 | Agent / Developer | [Agent Runtime](architecture/agent-runtime.md) | [contracts](../backend/src/sumika_core/agent/contracts.py)、[registry](../backend/src/sumika_core/agent/registry.py)、[contract tests](../backend/tests/test_agent_portability.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 接入第二个真实 Harness adapter 后验证跨 Runtime 会话迁移与能力差异 |
| `dsh-agent-runtime` | 已实现 | Agent / Tasks / Developer | [DSH Agent](integrations/dsh-agent.md) | [DSH adapter](../backend/src/sumika_core/agent/adapters/dsh/runtime.py)、[credential bridge](../backend/src/sumika_core/agent/credential_binding.py)、[MCP managed writer](../backend/src/sumika_core/agent/adapters/dsh/mcp_config.py)、[protocol/MCP smoke](../tools/smoke_dsh_round.py)、[daily acceptance](../tools/agent_daily_acceptance.py)、[MCP stdio fixture](../backend/tests/fixtures/mcp_stdio_server.py)、[skill catalog](../backend/src/sumika_core/agent/skill_catalog.py)、[task projection](../backend/src/sumika_core/tasks/agent_projection.py)、[Agent tests](../backend/tests/test_agent_runtime.py)、[Playwright smoke](../frontend/tests/smoke.spec.js)、[desktop launcher](../src-tauri/src/main.rs) | Phase 0–3 已完成：Workspace 绑定、Execute/Plan Review checkpoint、独立 worktree/本地 commit、Session 恢复、刷新/重连状态重同步、失败或取消文本回合的审批门控重试、长会话 `beforeSeq` 翻页、Windows Provider 与 MCP 安全启动注入、Preset 生命周期、MCP preview/apply/mount validation、Skill discover/approve/revoke、Subagent 和 Plugin manifest 边界均已闭环；隔离固定 DSH 的 Plan→Execute、MCP `tools/call`、审批、diff、精确恢复、Skills 和 Subagents 组合验收于 2026-08-29 通过。固定版 DSH 仍不暴露独立 Readonly policy、composition 写入、live `mcp.list`、artifact 或 rollback RPC；Phase 4（更广泛任务/浏览器人工接管/真实第三方 MCP）等待明确恢复 |
| `agent-observability` | 部分实现 | `GET /api/agent/observability`；`python tools/aggregate_agent_day.py`；`python tools/evaluate_models.py`；`python tools/agent_daily_acceptance.py --real-session`（维护工具） | [Agent observability](architecture/agent-observability.md) | [observability sink](../backend/src/sumika_core/observability.py)、[model evaluator](../backend/src/sumika_core/model_evaluation.py)、[fixed task set](../tools/fixtures/model-evaluation-v1.json)、[evaluation tests](../backend/tests/test_model_evaluation.py)、[acceptance RPC tests](../backend/tests/test_agent_server.py)、[daily report tests](../tools/test_agent_daily_acceptance.py)、[server tests](../backend/tests/test_observability_server.py) | 累积真实隔离评测样本、固定 manifest 并审查诊断推荐；保持安装/启用/路由改变需批准 |
| `browser-runtime` | 部分实现 | Agent > 隔离浏览器 | [Browser runtime](integrations/browser-runtime.md) | [BrowserSkill bridge](../backend/src/sumika_core/browser/runtime.py)、[policy evaluator](../backend/src/sumika_core/browser/policy.py)、[DSH policy plugin](../plugins/dsh-browser-policy/README.md)、[browser tests](../backend/tests/test_browser_runtime.py)、[policy tests](../backend/tests/test_browser_policy.py)、[Playwright smoke](../frontend/tests/smoke.spec.js)、[license ledger](ui/license-ledger.md)、`bsk doctor --json` daemon/protocol 检查、[`smoke_dsh_browser.py`](../tools/smoke_dsh_browser.py)、[`smoke_dsh_browser_write.py`](../tools/smoke_dsh_browser_write.py)、[daily acceptance](../tools/agent_daily_acceptance.py) | 会话、观察、审批门控 DOM 操作、下载 quarantine、命名 Profile 与单写租约已具备；CLI `0.1.11` 与 extension `0.1.7` 的 protocol 1.1 已在隔离 Edge 通过 doctor；固定 DSH 的真实只读导航、导航审批、snapshot、session stop，以及本地非敏感表单写入和 3 次审批已通过统一日用验收；真实人工接管、登录审批、24 小时清理和更细 CDP 事件仍待用户授权或上游能力，再提升状态 |
| `web-chat-runtime` | 部分实现 | Modules > 实现方式、Developer > 网页连接 | [Web Chat](integrations/browser-runtime.md#网页聊天档案web-chat) | [web-chat adapter](../backend/src/sumika_core/browser/web_chat.py)、[runtime tests](../backend/tests/test_web_chat.py)、[RPC tests](../backend/tests/test_web_chat_server.py)、[Playwright smoke](../frontend/tests/smoke.spec.js) | 继续用真实账号验证人工登录、DOM 变化和人工接管；补充长期网页端额度来源前保持 `unknown`，不静默路由 |
| `evolution-registry` | 已实现 | Developer > Evolution Knowledge Registry | [Registry](integrations/evolution-registry.md) | [registry data](integrations/evolution-knowledge-registry.json)、[registry tests](../backend/tests/test_evolution_registry.py) | 增加隔离评测报告和用户批准工作流 |

## 需求基线映射

长期产品意图和验收标准记录在[需求基线](requirements/README.md)。本表仍是当前完成度的
唯一事实源；下列映射只建立追踪关系，不复制状态。

| 状态 ID | 需求 ID |
| --- | --- |
| `local-llm` | `PLATFORM-001`, `PROVIDER-002`, `MODEL-008` |
| `provider-profiles` | `PROVIDER-001`, `PROVIDER-003`, `PROVIDER-005`, `MODEL-004` |
| `ccswitch-import` | `PROVIDER-004` |
| `chat` | `UX-001`, `CHAT-001` |
| `characters` | `CHARACTER-001`, `CHARACTER-002` |
| `modules` | `PROVIDER-001`, `PLUGIN-001` |
| `capability-catalog` | `CAPABILITY-001`, `AGENT-001`, `PLUGIN-001`, `MODEL-002` |
| `desktop-automation` | `DESKTOP-001`, `DESKTOP-002`, `CAPABILITY-001`, `SEC-001` |
| `model-policy` | `MODEL-001`, `MODEL-002`, `MODEL-003`, `MODEL-004`, `MODEL-005`, `MODEL-006`, `MODEL-007`, `MODEL-008`, `MODEL-009` |
| `tasks` | `CORE-001`, `TASK-001`, `WORKSPACE-001` |
| `avatar-vrm-desktop` | `AVATAR-001`, `AVATAR-002` |
| `plugins-manifest` | `PLUGIN-001` |
| `audio` | `DEFERRED-001` |
| `memory` | `MEMORY-001`, `MULTI-001`, `DEFERRED-001` |
| `vision` | `DEFERRED-001` |
| `snapshots` | `SEC-001`, `WORKSPACE-001` |
| `live2d` | `DEFERRED-001` |
| `virtual-world` | `DEFERRED-001`, `MULTI-001` |
| `life-agent` | `DEFERRED-001`, `MULTI-001` |
| `remote-runner` | `DEFERRED-001` |
| `android-client` | `DEFERRED-001` |
| `agent-runtime-portability` | `AGENT-001`, `MODEL-002`, `MODEL-003` |
| `dsh-agent-runtime` | `AGENT-001`, `AGENT-002`, `MCP-001`, `SKILL-001`, `TASK-001`, `STARTUP-001`, `MODEL-002`, `MODEL-003` |
| `agent-observability` | `OBS-001`, `EVOLUTION-001`, `MODEL-010` |
| `browser-runtime` | `BROWSER-001`, `MODEL-009` |
| `web-chat-runtime` | `CAPABILITY-001`, `BROWSER-001`, `MODEL-002` |
| `evolution-registry` | `EVOLUTION-001` |

## 更新规则

完成一个可验证的用户入口、协议边界或测试夹具后，先更新对应行的状态、入口
和证据，再在专题文档中补充设计细节。没有实现证据时，不得把状态写成
`已实现`。
