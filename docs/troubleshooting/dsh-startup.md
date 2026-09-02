# 固定 DSH 启动故障手册

本手册适用于 Sumika 固定 DSH `0.1.1-rc.2`、Windows `run-desktop.ps1` 和 Tauri
启动器。当前完成度仍以[状态矩阵](../status-matrix.md)为准。

## 证据顺序

1. 检查 Git 工作树和启动脚本输出，确认本次入口是 `tools/run-desktop.ps1`。
2. 用 `tools/dsh-launch.ps1` 的版本验证结果确认路径、实际版本和错误类别。
3. 用进程/端口检查确认 `sumika-desktop` → `dsh.cmd` → Node 与 Python Core 的父子关系。
4. 用 `/api/health`、`/api/agent/status`、`/api/agent/diagnostics` 和 DSH
   `host.describe` 交叉确认协议就绪。

不要把全局 `dsh --version` 当作 Sumika Runtime 证据；也不要把 `host.describe` 的协议版本
当作 npm/CLI 发行版本。日志只应包含路径文件名、版本、端口、PID、状态和错误类别。

## 常见症状

### `path-not-found`

固定安装不存在，或显式路径拼写错误。先运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/test_dsh_launch.ps1
```

需要安装时，使用项目已有的 `tools/setup-dsh.ps1`，不要把全局 DSH 放入 PATH 候选。

### `version-mismatch`

实际 `--version` 不是 `0.1.1-rc.2`。不要自动回退或升级；安装固定版本，或设置指向同一
版本的绝对 `SUMIKA_AGENT_EXECUTABLE`。版本验证失败时 Tauri 不会启动错误 Runtime。

### 默认 `3080` 已被占用

默认 endpoint 上的 `host.describe` 只能证明协议健康，无法证明它是固定发行包。停止由
本次 Sumika 启动的实例后再运行 launcher；若确实要复用外部实例，显式设置
`SUMIKA_AGENT_ENDPOINT`，并接受状态中的 `version_verified=false`。

### Core-only 显示全局 DSH

这是不应出现的状态。确认 `tools/run_core.ps1` 没有继承旧的 executable 环境；DSH adapter
在 Core-only 模式不调用 `PATH` 发现。重新读取 `/api/agent/status`，应看到
`executable=null` 和 `version_source=unverified external/Core-only`。

### 启动后马上退出

先看 `.sumika-desktop\logs\dsh.log` 和 `desktop.log` 中的错误类别，再分别检查：

```powershell
netstat -ano | Select-String '127.0.0.1:(3080|8771).*LISTENING'
Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('sumika-desktop.exe','node.exe','python.exe') } |
  Select-Object ProcessId,ParentProcessId,Name
```

不要直接杀掉用户已有的 DSH、Ollama 或 BrowserSkill。关闭客户端后再次运行相同端口检查；
`3080` 和 `8771` 都应释放。

## 验证命令

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/test_dsh_launch.ps1
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend\src')
python -m unittest backend.tests.test_agent_runtime
python tools/check_docs.py
git diff --check
```

固定协议闭环使用 `tools/agent_daily_acceptance.py --runtime-smoke`。它只在临时 Git
workspace 中运行测试 Provider，不读取或输出用户凭据、Prompt、模型回答或完整路径。
