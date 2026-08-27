# Sumika 当前执行契约

本页只用于恢复当前开发目标和下一步，不是功能状态或完整架构的事实源。
功能状态以 [状态矩阵](status-matrix.md) 为准，接口和约束以对应专题文档为准。

## 目标

在当前 Windows 开发环境中，把 Sumika 完成到可以一键启动并承担日常代码仓库
工作的程度，同时保留首版角色、Avatar、桌宠和本地数据能力。

## Definition of Done

- 从一个明确入口检查并启动 Agent Runtime、Python Core 和 Tauri 客户端；
- 可选择真实仓库并使用 Plan、Execute、Readonly、工具、审批、MCP、Skills 和 Subagents；
- 每次正式文件修改前可创建 checkpoint，之后可查看 diff 并精确恢复；
- 隔离浏览器支持真实连接、人工接管、敏感动作审批和下载 quarantine；
- DSH、Provider、工具或浏览器不可用时明确失败，不生成 Fake 结果；
- 使用独立 worktree 由 Sumika 完成一次 Sumika 自身改动并通过完整回归；
- 关闭客户端后不遗留由本次实例启动的受管进程。

## 当前基线

- Branch: `codex/dsh-agent-runtime`
- Baseline commit: `b005c3f41cf712a2183bb0c9d711f1638f63d2f0`
- Last verified commit: `b005c3f41cf712a2183bb0c9d711f1638f63d2f0`
- Runtime: DSH `0.1.1-rc.2` through the runtime-neutral `AgentRuntime` adapter
- Status source: [status-matrix.md](status-matrix.md)
- Runtime design: [Agent Runtime](architecture/agent-runtime.md)
- DSH integration: [DSH Agent](integrations/dsh-agent.md)

Existing untracked `example.txt`, `output/`, and `test-results/` are outside the
approved development scope and must not be staged, moved, overwritten, or removed.

## 当前里程碑

**Phase 1 - 真实运行基线（进行中）**

目标是启动固定版本的受管 DSH，连接一个已经由用户配置并测试的真实 Provider，
再从 Sumika 完成 Session 创建、Plan、工具调用、审批和最终回答的端到端验证。

Phase 0 已完成的设计结果：本执行契约、固定恢复顺序和文档检查边界。

## 接下来的三个动作

1. 验证固定 DSH CLI、隔离 Profile、受管启动参数和 `host.describe` 健康响应。
2. 通过现有 Provider bridge 检查真实档案、凭据隔离和 DSH route/model 选择。
3. 创建真实 Agent Session，执行只读任务并核对 Plan、工具、审批、事件和最终投影。

## 固定决策

- DSH 是默认 Harness，但不是 Core、UI、角色、Avatar、任务或 Workspace 的基类。
- DSH Session、Plan、Skills、Subagents 和审批是活动状态的事实源。
- MCP 使用用户 Preset 和 `dsh-mcp-client`；配置、凭据和启停仍由 Sumika 审批。
- DSH 没有可靠 rollback RPC，因此 checkpoint、diff 和恢复由独立
  `WorkspaceRuntime` 负责，并通过工具暴露给 Harness。
- 社区插件必须在隔离 Profile 中验证许可证、API、权限和卸载恢复后才能启用。
- 一键启动只复用和检查用户已安装的固定 Runtime，不自动安装或更新软件。
- 正式文件修改只发生在独立 worktree、分支或等价的可恢复 Workspace 中。

## 明确暂缓

- 音频、视觉、Live2D 新驱动；
- 多角色自动互聊、VirtualWorld 和 LifeAgent；
- RemoteRunner、Android、macOS/Linux 正式桌面发布；
- 正式安装器、自动更新和代码签名；
- 自动安装、升级或启用第三方插件。

## 当前阻塞

- 当前没有需要用户立即处理的阻塞。
- 真实 Provider 若缺少可用凭据，必须暂停并请用户在凭据界面重新输入；不得从
  SQLite、日志或聊天中恢复密钥。
- BrowserSkill 扩展连接和登录态只在 Phase 5 实机验证，不作为 Phase 1 的伪前提。

## 验证记录

基线提交已通过：

- Python unittest: 202 tests;
- Playwright: 32 tests;
- `node --check frontend/main.js`;
- frontend production build;
- `cargo check --manifest-path src-tauri/Cargo.toml`;
- `python tools/check_docs.py`;
- `git diff --check`.

未执行：`cargo fmt --check`，因为当前工具链没有 `rustfmt`；不得为此静默安装组件。

## 恢复顺序

1. 完整读取本页；
2. 读取状态矩阵中当前里程碑涉及的条目；
3. 检查 Git root、branch、HEAD、remote 和工作树；
4. 读取当前里程碑链接的专题文档和相邻测试；
5. 从“接下来的三个动作”继续，并用仓库和运行时证据校验本页内容。

若本页与 Git、测试、状态矩阵或真实运行时冲突，以可复现证据为准，并在继续
实现前修正本页。

## 更新规则

- 只在里程碑开始、完成、出现阻塞或切换分支时更新；
- 保持在 150 行以内，不复制专题文档或聊天过程；
- 不记录 API Key、Token、聊天正文、用户目录、临时日志或认证信息；
- 每次更新都同步当前里程碑、三个动作、阻塞和验证记录；
- 功能完成度只更新状态矩阵，本页不得创建第二套状态定义。
