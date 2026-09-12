# 阶段 2：DSH 发行锁定与真实能力验收

状态：**部分完成，受 Windows `pwsh` 沙箱路径问题阻塞**。

## 已通过

- 固定 `@deepseek-ai/dsh@0.1.5-rc.2`、冻结 `pnpm-lock.yaml`、独立 profile 和回退说明。
- 核验发行摘要、CLI 版本、子进程 stdout 启动 token、Windows TCP 监听端口 PID 及 DSH 原生 cookie。
- 通过真实隔离 profile 的 session/create、session/follow WebSocket、历史快照和 turn/end 事件。
- DSH 原生 `write`、`read`、`edit`、`grep`、`glob`、本地 `.agents/skills`、subagent、list_agents、stdio MCP 均通过本地确定性模型替身驱动；最终文件内容正确，未调用外部模型。
- HTTP `client-request`、rpcId、payload.args.request、业务 ok/value 均严格校验，HTTP 200 业务错误仍失败。

## 阻塞项

DSH rc.2 Windows `pwsh` 工具在 workspace-write 模式下读取 DSH 创建的 workspace 文件时返回：

```text
[sandbox: file access denied under workspace-write mode]
[exit code: 1]
```

这是真实沙箱拒绝，不能改成 danger-full-access、忽略退出码或把 stderr 当成功。需要先用 DSH 原生配置或上游修复确认工作区路径策略，再重跑终端读写、cwd、退出码、超时、活动取消和恢复。

## 尚未完成

- Windows pwsh 沙箱工作区路径修复。
- 活跃模型 turn 取消、迟到事件和断线重连恢复。
- Plan 模式、权限审批 UI、后台任务的真实交互。
- 完整文件/终端/测试连续闭环以及必要插件组合验收。

证据脚本：`tools/verify_dsh_p2.py`；本地产物位于被忽略的 `.sumika-next/p2-*/`，不提交模型请求或凭据。P2 未完成前不开放新的 prompt/model 入口，不切换日用 profile。
