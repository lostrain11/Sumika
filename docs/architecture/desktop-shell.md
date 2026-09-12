# Desktop shell boundary

> 2026-09-08：用户正式确认网页交互统一到Sumika内置浏览器，见[正式需求](../requirements/embedded-browser.md)（`BROWSER-003`）。本文的BrowserSkill、独立门户及原生咨询描述是当前实现边界，不能视为已完成统一。旧咨询五来源3+2不再规定默认策略，当前要求见 `BROWSER-004`。

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

- one main window with mutually exclusive workspace and pet display modes;
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

The A+ pet mode paints a fixed room, Avatar, short reply and compact composer.
The optional transparent background hides the room, not the character. Controls
appear on hover or keyboard focus. `set_display_mode` transforms the same main
window instead of loading another WebView, preserving session, draft and renderer.
Workspace bounds and maximized state are restored on return. `hide_pet` restores
workspace then minimizes to the taskbar; it does not leave an unreachable hidden
window. Hidden/minimized scenes stop continuous rendering.

The interaction boundary follows N.E.K.O's desktop-pet behavior as a reference;
Sumika uses a main-window-only `start_pet_drag` command around Tauri's native drag API and does
not copy N.E.K.O source code, models or animation assets. Transparent means the
window has no decorative panel background; it remains hit-testable so the model
can be dragged and the chat composer can receive input.

## Web portals

Besides `main`, the shell can create dynamic portal windows:
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
The entry is the portal button in the chat toolbar, rendered only in the
desktop shell — the browser preview cannot create Tauri windows and shows no
portal entry. The main navigation has five text entries. Custom portal entries stay in that desktop window's local
storage only.

The [A+ client contract](../ui/a-plus-client.md) records native mode behavior and
the isolated `node tools/native-ui-smoke.mjs` check. `SUMIKA_DESKTOP_DATA_DIR` accepts
an explicit absolute test data directory; otherwise `.sumika-desktop` remains the
default. Browser layout tests do not substitute for native window validation.

Next form (user-confirmed direction, not yet implemented): embed portals as
child webviews inside the main window instead of separate windows. This
requires the Tauri `unstable` feature (`Window::add_child`/`WebviewBuilder`
are unstable-gated in 2.11.5), per-webview `data_directory` (supported by
wry/WebView2), async commands (synchronous webview creation deadlocks on
Windows), and upgrading the existing chat-toolbar portal button to a site
switcher. iframe and OS-window embedding were evaluated and rejected (site CSP
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
version-matched executable whose path comes from the managed release description
under `dsh-release/`. This discovery does not install, update, or download DSH;
an absent runtime leaves Agent in an
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

## Native ChatGPT Consultation

The quality-routing workbench adds a separate ChatGPT child WebView inside
the unified browser workspace. The child uses an isolated local
profile and a single-writer lease; existing browser cookies are not imported.
Only `https://chatgpt.com` and `https://auth.openai.com` can navigate within
this view. DOM automation is restricted to `chatgpt.com`; social login, SSO,
and popup authentication are not yet supported.

Fixed asynchronous commands open, resize, hide, close, observe, fill, submit,
read, and transfer manual control. The model cannot provide JavaScript.
Each submission has an attempt ID and a bounded journal without message text;
ambiguous submissions are never automatically replayed. Only the trusted main
WebView may call management commands. The Core also rejects remote HTTP
Origins and mismatched Host headers, preventing a remote page from bypassing
the native command boundary through loopback HTTP.

`node src-tauri/scripts/consultation-smoke.mjs` uses isolated data and a
debug-only fixed probe to check native loading, origin restrictions, bounds,
takeover and lease recovery. It does not log in or submit messages. The probe
is excluded from release builds. Real login and conversation acceptance remain
separate from this smoke test; see [quality routing](../refactor/quality-routing.md).

## Unified Browser Workspace

`embedded_browser.rs` hosts managed tabs inside the main window. Portal commands
no longer create separate windows. Existing portal folders are reused only with
the same account identifier; BrowserSkill profiles and the consultation profile
remain separate. WebView2's actual user-data directory is checked before network
navigation, preventing a global WebView environment override from collapsing
account isolation. Navigation accepts public HTTPS addresses, denies popups,
and offers only fixed chat/account commands, not arbitrary JavaScript.

The Core's `EmbeddedBrowserBridge` carries bounded, one-shot work to the trusted
frontend. Explicit `native` web-chat profiles use this bridge; desktop mode never
falls back to BrowserSkill for chat or scheduled account/benefit maintenance.
Old maintenance bindings require explicit native rebinding and login; no cookies
are copied. Non-desktop compatibility and general BrowserSkill tooling remain
separate, not claimed as migrated native automation.

Manual takeover pauses automatic work per account. Hidden or pet viewports cannot
submit; cancelled queued work cannot submit after a late fill result. Restarted
unknown submissions require original-request reconciliation, not resubmission.
Only open views count toward the 32-tab capacity; closed metadata does not consume
live slots. Journals contain bounded identity/state, never message text or cookies.

`node src-tauri/scripts/embedded-browser-smoke.mjs <cache-directory>` runs the native
checks without model calls. First build the frontend and `cargo build --features
custom-protocol`; a plain debug build otherwise expects the development server.
The debug-only `SUMIKA_SMOKE_MAIN_DATA_DIR` isolates main-view preferences without
the global `WEBVIEW2_USER_DATA_FOLDER` override. Real login, account readings and
web consultation still require separate per-site acceptance.

## 相关文档

- [Agent Runtime](agent-runtime.md)
- [本地模型](local-model.md)
- [调试与恢复](debugging.md)
- [Protocol](protocol.md)
