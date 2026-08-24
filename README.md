# Sumika

A local-first, modular desktop companion foundation.

## Run the browser slice

From the repository root (the script uses `SUMIKA_PYTHON` when provided and
otherwise resolves `python` from `PATH`):

```powershell
.\tools\run_core.ps1
```

The startup wrapper checks the official Ollama installation and ensures the
configured local model is present before starting Sumika. The default is
`qwen3:4b`; an already-running Ollama service is reused. Pass
`-OllamaModelsDir` or set `SUMIKA_OLLAMA_MODELS` when using a custom model
cache. Use `-SkipModel` when you intentionally manage Ollama yourself. Git
Bash can use `./tools/run_core.sh` or `./tools/run-desktop.sh`; the wrappers
translate common `--skip-model` and `--model=...` options without changing the
system proxy.

Use the Git Bash executable installed on your system if `bash` resolves to the
Windows Subsystem for Linux shim.

To use another Python runtime:

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run_core.ps1
```

Then open [http://127.0.0.1:8770/](http://127.0.0.1:8770/). The browser slice
keeps its data in `.sumika`.

## Run the desktop development shell

Install dependencies once with `npm install` in `frontend`, then from the
repository root run:

```powershell
.\tools\run-desktop.ps1
```

默认从 `PATH` 查找 `python`。如果 Python 位于其他位置，启动前设置
`SUMIKA_PYTHON`；脚本会保留调用方提供的配置：

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run-desktop.ps1
```

Git Bash 也可以调用同一个脚本：

```bash
cd /path/to/Sumika
export SUMIKA_PYTHON='C:/Path/To/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/run-desktop.ps1
```

The script builds the frontend, starts the Tauri 2 window, and lets the window
manage its Python core child on `127.0.0.1:8771`. Desktop data is isolated in
`.sumika-desktop`; it can run independently of the browser slice. Use
`-NoBuild` for a faster repeat launch after a frontend build. The first local
run requires the Rust MSVC toolchain and Windows C++ build tools. The main
window can open an optional always-on-top `桌宠模式` overlay. The model area is
a Tauri drag region, so the floating pet can be moved around the desktop; a
compact chat input sits below the model and uses the same selected character,
session and provider as the main window. Provider, module, permission and task
configuration stays in the main window.

Desktop lifecycle and Python startup diagnostics are written to
`.sumika-desktop/logs/desktop.log`; core boundary diagnostics are written to
`.sumika-desktop/logs/core.log`. The Developer page and `GET /api/diagnostics`
show the safe log location and runtime counters. In the Tauri shell, the same
page also shows the supervised core PID, endpoint and restart count; see
`docs/architecture/debugging.md`. Logs never contain API keys, chat text, or
raw visual/audio data.

桌面端核心默认监听 `127.0.0.1:8771`，浏览器预览默认使用 `127.0.0.1:8770`。
首次构建后可用 `-NoBuild` 快速重复启动；日志仍写入
`.sumika-desktop/logs/desktop.log` 和 `.sumika-desktop/logs/core.log`。

The core uses only the Python standard library in this bootstrap. It provides
an OpenAI-compatible provider backed by Ollama or another real endpoint, an
external JSONL process boundary,
SQLite sessions/events/snapshots, JSON-RPC commands and a WebSocket event
stream. It also includes an approval-gated external tool JSONL boundary. Set
`SUMIKA_OPENAI_BASE_URL`, `SUMIKA_OPENAI_MODEL` and
`SUMIKA_OPENAI_API_KEY` to configure an OpenAI-compatible endpoint. Set
`SUMIKA_COMMAND_PROVIDER` to expose an explicitly configured executable as the
external provider. The production catalog never registers Fake providers;
deterministic doubles live only in `backend/tests/fixtures` and are injected
explicitly by tests.

顶部的 `LLM` 入口只显示当前状态并跳转到“模块”页；启用或关闭 LLM 只由
模块卡片右侧的开关负责，实现下拉框只选择真实 provider。关闭后聊天发送按钮会
显示为不可用，核心也会拒绝 `chat.send`，不会生成演示或 Fake 回复。

The first run registers the bundled `AvatarSample_A.vrm` VRoid sample as the
default Avatar. Its source and license record live in `assets/avatars/README.md`.
The browser loads the registered `.vrm` through the local-only file endpoint and renders
it with the bundled Three.js/VRM adapter; a verified thumbnail remains as the
fallback when WebGL is unavailable.

VRM viewer 的自然站姿和鼠标视线/头部跟随都是运行时效果，不会写回模型文件。
跟随和姿态可在“角色”页按角色关闭或调节。VRMA 适配器已预留，但首版不内置
动画素材；未来必须通过本地 manifest、独立许可证记录和用户确认后加载。

## Documentation

- [文档总入口](docs/README.md)：按用户使用、架构、开发接口和外部集成导航。
- [状态矩阵](docs/status-matrix.md)：唯一维护已实现、部分实现和规划中状态的地方。
- [架构索引](docs/architecture/README.md)：协议、模块、Provider、Avatar、任务和安全边界。
- [UI 参考与许可证台账](docs/ui/reference-map.md)：交互参考、来源和复用限制。
- [第三方声明](THIRD_PARTY_NOTICES.md)：已纳入或允许复用的外部组件说明。

代码目录仍按边界组织：`backend/src/sumika_core` 是核心服务，`frontend` 是
浏览器/Tauri 客户端，`plugins/examples` 是最小外部进程示例。新增或完成一项
能力后，先更新状态矩阵，再补对应专题文档；可运行
`python tools/check_docs.py` 检查文档链接和索引覆盖。
