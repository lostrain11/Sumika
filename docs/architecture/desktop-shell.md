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
- dynamic per-site web portal windows with isolated persistent logins (desktop shell only, see below);
- a native Avatar file picker through `tauri-plugin-dialog`;
- a supervised Python child process on `127.0.0.1:8771`;
- an optional Agent Runtime child supervised through a runtime-specific launcher config;
- isolated `.sumika-desktop` data and lifecycle logs.

Provider and managed MCP secrets are stored by the Python core through the
credential-store boundary; Windows currently uses Credential Manager. Before
starting managed DSH, the shell invokes a private versioned helper protocol,
validates every environment name plus the total binding count/size, and injects
the values only into that child process. The Python core receives only the
non-sensitive names of MCP bindings loaded for the launch. macOS Keychain and
Linux Secret Service adapters are not implemented, so those platforms fail
closed for profiles that need a persisted secret. The desktop shell does not
persist, print, or return credential values.

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

## Web portals

Besides `main` and `overlay`, the shell can create dynamic portal windows:
one Tauri `WebviewWindow` per chat site (Kimi, ChatGPT, 智谱清言, DeepSeek,
通义千问, 豆包, plus user-added entries). Each portal loads the raw provider
website and keeps its own persistent WebView2 data directory under
`.sumika-desktop/portals/<site-id>/`, so a login survives restarts and sites
never share cookies. Opening an already-running portal focuses it.

Portals are the user's own browsing surface: no persona is injected, no Agent
or web-chat route touches them, and they do not read or migrate the
BrowserSkill named-profile logins (those belong to the managed Edge Agent
Window used by [web chat routes](../integrations/browser-runtime.md)). Commands:
`open_portal` / `focus_portal` / `close_portal` / `portal_list`; site ids are
restricted to ASCII letters/digits/dash/underscore and URLs to http(s).
The entry is the fifth dock icon in the scene shell, rendered only in the
desktop shell — the browser preview cannot create Tauri windows and shows no
portal entry. Custom portal entries stay in that desktop window's local
storage only.

Next form (user-confirmed direction, not yet implemented): embed portals as
child webviews inside the main window instead of separate windows. This
requires the Tauri `unstable` feature (`Window::add_child`/`WebviewBuilder`
are unstable-gated in 2.11.5), per-webview `data_directory` (supported by
wry/WebView2), async commands (synchronous webview creation deadlocks on
Windows), and moving the site switcher next to the chat composer's send
button. iframe and OS-window embedding were evaluated and rejected (site CSP
and the lack of window reparenting respectively).

Controlled automation of a separate desktop application is deliberately not
implemented by the overlay. It is exposed through the runtime-neutral
[desktop automation toolkit](desktop-automation.md): an approved application
is opened under an exclusive profile lease, then observed or controlled through
an application protocol, Electron CDP, or Windows UIA adapter. Foreground input
is a separate disabled-by-default takeover path and never affects the user's
other windows.

The following desktop capabilities remain deferred:

- tray integration;
- global shortcuts;
- low-priority background scheduling.

The shell waits for the Python `/api/health` response before presenting the
window. If a managed child exits unexpectedly, Rust records the exit and retries
with bounded backoff. A normal shutdown, window lifecycle exit, or Rust process
drop kills and waits only for children created by that Sumika instance. The
current Core and Agent Runtime IDs, PIDs, endpoints and restart counts are
available through the `core_status` command in the Developer page.

Agent process supervision is runtime-neutral. `AgentLaunchConfig` contains the
executable, arguments, environment, isolated profile, endpoint and health probe;
currently only the real DSH launcher is registered. `SUMIKA_AGENT_*` selects the
runtime and launcher settings, while existing `SUMIKA_DSH_*` names remain DSH
compatibility aliases. An unknown runtime cannot enable managed autostart and
must run externally until its real launcher is implemented.

On Windows, `tools/run-desktop.ps1` first probes the configured DSH endpoint.
It reuses a healthy external process without supervising or stopping it. When
the endpoint is unavailable, it may auto-start only the already installed,
version-matched executable at
`D:\Tools\DeepSeekHarness\0.1.1-rc.2\node_modules\.bin\dsh.cmd`. This discovery
does not install, update, or download DSH; an absent runtime leaves Agent in an
explicit unavailable state while the rest of the desktop still starts.

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

- [Agent Runtime](agent-runtime.md)
- [本地模型](local-model.md)
- [调试与恢复](debugging.md)
- [Protocol](protocol.md)
