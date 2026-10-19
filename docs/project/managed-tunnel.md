# 可管理 SSH 隧道（2026-10-19）

用于把笔记本上的 Ollama（或 llama.cpp）通过 OpenSSH 本地端口转发到 Sumika 的 loopback 地址，供辅助模型/提示词优化使用。隧道是显式传输层，不是第二个模型 provider；不保存密码或私钥，不绕过 loopback 校验。

## 使用位置

设置 → 模型与连接 → 辅助模型：

- 服务地址：`http://127.0.0.1:18114`（示例；必须是未占用的本机端口）。
- 启用 SSH 隧道：勾选。
- SSH 主机：`192.168.31.227`；SSH 用户：`lostrain`；SSH 端口：`22`；远端 Ollama 端口：`11434`。
- 可选「连接后预加载模型」：隧道健康后向 Ollama `/api/generate` 发空请求并设置 `keep_alive=30m`，状态显示预加载中/已预加载/失败；不阻塞隧道状态。
- 保存后隧道按配置异步启动；面板下方显示真实状态，可手动「启动隧道」「停止隧道」「刷新状态」。
- Provider 选 `Ollama` 时健康检查为 `/api/tags`；`openai-compatible-local` 时为 `/v1/models`。

## 行为

- 只有 `auxiliary.enabled` 与 `tunnel.enabled` 同时为真才启动；否则停止。
- 启动前检查本机端口是否被占用；绝不杀占用者，只报告冲突。
- 使用 `ssh -N -L 127.0.0.1:<本地>:127.0.0.1:<远端>`，BatchMode、ExitOnForwardFailure、ServerAlive；不绑定 LAN。
- 子进程退出后指数退避重启（2/5/10/30 秒上限），状态报告 `restarts`、`last_error`、`last_check`。
- Bridge 关闭时终止本轮 SSH 子进程；不会留下孤儿。
- 日志只写 `.sumika-next/.../tunnel/tunnel.log`，超过 1MB 轮转，状态只返回最后一行短错误。
- 主机键使用 `StrictHostKeyChecking=accept-new`（首次信任并记录）；密码/交互式认证被禁用，必须预先配好公钥或 agent。

## 实测

隔离设置、真实笔记本：

- `LocalTunnel.start()` 启动后 `running=true, healthy=true`，`/api/tags` 返回 Qwen2.5；`stop()` 后端口关闭。
- Bridge 启动时自动拉起隧道，`status` 为 healthy；`server.shutdown()/server_close()` 后 `running=false`、端口关闭。
- 手动杀掉 SSH 子进程后，supervisor 在约 2 秒后重启新 PID，`restarts=1`、健康恢复。
- 预加载实测：`preload=warming` 约 67 秒后转 `ready`，Ollama 模型已加载；测试后已 `ollama stop` 卸载。
- 未做真实工作台 UI 点击；设置页字段/状态为代码接通，尚未跑浏览器验收。

## 边界

- 需要 Windows OpenSSH 客户端、已配置的免密公钥/agent、known_hosts 可写；没有密码输入框。
- 隧道只保证传输；Ollama 模型是否加载、冷启动耗时、模型质量仍按模型验收。
- 预加载是可选项，默认关闭；开启后用 30 分钟 keep_alive，空闲过期后仍可能冷启动。
- 本地提示词优化候选未通过质量门，按用户决定暂不由本地模型负责；隧道/预加载默认关闭，不改变该结论。
- 未启用日用配置；未自动修改用户现有设置。
