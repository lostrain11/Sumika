# Desktop shell boundary

## Platform status

- Windows：当前受支持的 Tauri 开发入口是
  `.\tools\run-desktop.ps1`。
- macOS/Linux：Python 核心与浏览器界面可使用根 README 中的直接命令；Tauri
  桌面端属于实验性能力。
- 原生 `tools/run_core.sh` 和 `tools/run-desktop.sh` 只预留路径，尚未实现。
  仓库中的现有 `.sh` 文件是旧的 Windows Git Bash 兼容包装器，不是 POSIX
  启动器。

所有平台的正常启动都不管理 Ollama 或模型权重。Provider 配置与启动生命周期
保持独立。

The browser preview remains an executable client. The first Tauri development
shell now wraps the same UI and local core, with:

- a main window;
- an opt-in, always-on-top desktop pet overlay window;
- a native Avatar file picker through `tauri-plugin-dialog`;
- a supervised Python child process on `127.0.0.1:8771`;
- isolated `.sumika-desktop` data and lifecycle logs.

Provider secrets are stored by the Python core through the credential-store
boundary; Windows currently uses Credential Manager. macOS Keychain and Linux
Secret Service adapters are not implemented, so those platforms fail closed
for profiles that need a persisted secret. The desktop shell does not
duplicate or expose credentials.

The overlay is a transparent desktop-pet surface: it paints only the Avatar and
a compact chat composer. Open-main-window and hide-overlay controls are
transparent until the pointer hovers the surface or keyboard focus enters it.
Holding the model area starts Tauri's native window drag; the input, send button
and overlay controls are explicitly excluded from the drag surface. Chat
requests use the current character, session and provider from the same local
core as the main window. Provider, module, permission and task configuration
stays in the main window. It is hidden by default and is opened from the main
window's `桌宠模式` action.

The interaction boundary follows N.E.K.O's desktop-pet behavior as a reference;
Sumika uses Tauri's official `getCurrentWindow().startDragging()` API and does
not copy N.E.K.O source code, models or animation assets. Transparent means the
window has no decorative panel background; it remains hit-testable so the model
can be dragged and the chat composer can receive input.

The following desktop capabilities remain deferred:

- tray integration;
- global shortcuts;
- low-priority background scheduling.

The shell waits for the Python `/api/health` response before presenting the
window. If the child exits unexpectedly, Rust records the exit and retries with
bounded backoff (up to five consecutive restart attempts). A normal shutdown,
window lifecycle exit, or Rust process drop kills and waits for the child so a
Python core is not left behind. The current child PID, endpoint, restart count
and desktop log path are available through the `core_status` command in the
Developer page.

It does not move provider orchestration into Rust or frontend components. The
browser client continues to use `127.0.0.1:8770` and `.sumika`. In a packaged
Tauri build the frontend uses the same local core over an explicit
`http://127.0.0.1:8771` URL; the core enables the narrow local CORS preflight
needed by that `tauri://` origin.

Those capabilities must call the existing core protocol instead of moving
provider orchestration into Rust or frontend components. Android is a future
remote client and should use the same command/event contracts after pairing and
authentication are designed.

## 相关文档

- [本地模型](local-model.md)
- [调试与恢复](debugging.md)
- [Protocol](protocol.md)
