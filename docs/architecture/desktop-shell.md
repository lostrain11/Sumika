# Desktop shell boundary

The browser preview remains an executable client. The first Tauri development
shell now wraps the same UI and local core, with:

- a main window;
- an opt-in, always-on-top desktop pet overlay window;
- a native Avatar file picker through `tauri-plugin-dialog`;
- a supervised Python child process on `127.0.0.1:8771`;
- isolated `.sumika-desktop` data and lifecycle logs.

Provider secrets are stored by the Python core through the Windows Credential
Manager boundary; the desktop shell does not duplicate or expose them.

The overlay keeps only high-frequency actions (open the main window and hide
the overlay), a compact chat composer, and a draggable Avatar area. Dragging
the model area moves the Tauri window; the input stays interactive and is not
part of the drag region. Chat requests use the current character, session and
provider from the same local core as the main window. Provider, module,
permission and task configuration stays in the main window. It is hidden by
default and is opened from the main window's `桌宠模式` action.

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
