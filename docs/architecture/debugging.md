# Debugging and Recovery Signals

Sumika keeps runtime data and diagnostics separate for each front end:

- Browser development uses port `8770` and `.sumika`.
- Tauri development uses port `8771` and `.sumika-desktop`.

The Tauri shell writes a small lifecycle log to
`.sumika-desktop/logs/desktop.log`. It records the shell setup, Python child
process id, HTTP health-check result, unexpected exits, restart attempts and
shutdown attempt. The Python child's
standard output and error use the same file so startup tracebacks remain near
the lifecycle record. The core writes structured operational diagnostics to
`.sumika-desktop/logs/core.log` (or `.sumika/logs/core.log` for the browser
slice). That file is size-rotated and records lifecycle, RPC method names,
durations, event types, HTTP paths, and exception types. API keys, environment
values, chat text, model content, and raw visual/audio data are not written by
the shell or core logger.

The core's SQLite event table remains the authoritative audit stream for module,
permission, task, provider, Avatar, memory, and snapshot changes. Use the
Developer page or `GET /api/events` to inspect it. When a desktop run fails,
check these signals in order:

1. `desktop.log` contains `Python core spawned`.
2. The next line contains `core health check passed` for `127.0.0.1:8771`.
3. If the core crashed, look for `Python core restarted and healthy`; five
   consecutive failures stop automatic retries and remain visible in the log.
4. `GET /api/health` returns `{ "ok": true }`.
5. The event stream shows the operation-specific event rather than only a UI
   notice.

The Developer page exposes the same safe runtime summary as
`GET /api/diagnostics`: process id, uptime, counts, data directory, and the
effective core log path. Use `core.log` for startup and boundary failures;
use SQLite events for user-visible audit and recovery history.

The log is disposable diagnostic output. Do not treat it as a backup or as a
source of truth for recovery; use named SQLite snapshots for recovery.

## 相关文档

- [Desktop shell](desktop-shell.md)
- [Protocol](protocol.md)
- [Security](security.md)
