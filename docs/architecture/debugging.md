# Debugging and Recovery Signals

Sumika keeps runtime data and diagnostics separate for each front end:

- Browser development uses port `8770` and `.sumika`.
- Tauri development uses port `8771` and `.sumika-desktop`.
- The optional DSH Agent endpoint defaults to port `3080`; its fixed version,
  endpoint and isolated profile are reported by `GET /api/agent/status`.
- On Windows, `run-desktop.ps1` reuses a healthy configured DSH endpoint or
  discovers the already installed pinned runtime. Tauri supervises only the
  child it created and writes `.sumika-desktop/logs/dsh.log`; an existing DSH
  process remains external and is never stopped by Sumika.

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

When Agent is enabled, check the Agent page or `GET /api/agent/status`. A
`ready` state means the independently managed DSH Web API answered health
checks; `unavailable` is an expected fail-closed state and does not trigger a
Fake or offline reply. Browser policy state is available from
`GET /api/browser/status`.

For a capability-level view, use the Developer page's “DSH 能力探针” or
`GET /api/agent/diagnostics`. The probe uses only read-only DSH RPCs and keeps
the response bounded to endpoint names, statuses and counts. In particular,
an HTTP 404 for `mcp.list` is reported as `not-exposed`, while a network
failure is `unavailable`; neither state is presented as a working MCP catalog.
The probe checks both the managed web manifest and the fixed
`profiles/node_modules/@deepseek-ai/dsh-mcp-client/package.json` path. A pnpm
junction is accepted because the lexical path is still inside the managed
 profile; the package is never imported or executed. “已安装” and “目录 RPC
 可用” remain separate facts.

For a repeatable daily coding check, run the isolated acceptance harness:

```powershell
python tools/agent_daily_acceptance.py --runtime-smoke --profile-dir <isolated-profile>
```

It creates a temporary Git repository, runs a real DSH Plan review followed by
Execute, and verifies the Workspace diff and exact restore path. Add `--mcp` to
include the checked-in stdio fixture or `--full-tests` to run the full local
regression commands. The harness deliberately keeps raw subprocess output out
of its report; a failed run contains only phase status, exit code, and error
class so secrets and chat content cannot enter diagnostics.

Session search, rename, and image attachment reads are deliberately absent from
the audit stream's payloads. Search queries and titles are bounded at the Core
boundary; attachment responses are returned only to the requesting UI after DSH
has verified session ownership. If a deployment disables `session.search`, the
result is surfaced as an unavailable capability rather than replaced with a
local scan. Image bytes are kept out of SQLite and log files.
The HTTP boundary keeps ordinary JSON requests at about 2 MB and permits up to
18 MiB for `/rpc`, which is needed for a base64-encoded image prompt; the Agent
adapter still caps each image at 12 MiB and rejects unsupported media types.

For a model mismatch, inspect `GET /api/agent/provider` and the Agent page's
Provider panel. `not-synced` means the active Sumika profile has not been
projected to its isolated DSH route; use “同步当前档案” and verify the route
before creating a new Agent session. `restart-required` means the remote key is
still only in Windows Credential Manager, but the running DSH process does not
have the current read-only environment reference; stop an external DSH if one
is being reused, then restart Sumika. The panel distinguishes secure storage,
the observed DSH credential source, and restart state. The bridge records only
profile/route/model identifiers, never API keys or prompt content.

For an authenticated MCP connection, inspect the Agent Preset panel. “凭据已保存”
means Credential Manager contains a value; “凭据待重启” means the current DSH
process did not receive that revision at launch. New and rotated credentials are
saved with the connection disabled. Restart Sumika, reopen the same user Preset,
then enable and mount-validate it. The composition contains a generated
`!!js process.env...` expression but never the value. A malformed managed marker,
changed expression, missing enabled credential, or mount failure is reported
without logging the target value or request secret.

The Developer page exposes the same safe runtime summary as
`GET /api/diagnostics`: process id, uptime, counts, data directory, and the
effective core log path. Use `core.log` for startup and boundary failures;
use SQLite events for user-visible audit and recovery history.

The log is disposable diagnostic output. Do not treat it as a backup or as a
source of truth for recovery; use named SQLite snapshots for recovery.

For Agent-only maintenance analysis, Core also writes content-independent
receipts under `.sumika-desktop/logs/agent-observability/` (or
`.sumika/logs/agent-observability/` for the browser slice). Each JSONL line
contains bounded lifecycle dimensions, opaque correlation hashes, timings,
outcomes, and optional numeric usage counters. It deliberately excludes
prompts, model output, tool arguments/results, file contents, DOM, cookies,
credentials, and raw exception messages. Files are disposable and size-rotated.
Generate a UTC-day summary with:

```powershell
python tools/aggregate_agent_day.py --write
```

The same report is available from `agent.observability.daily` or
`GET /api/agent/observability`. Missing or malformed lines are counted as
invalid instead of stopping the rest of the day's aggregation. This stream is
intended for the maintenance Agent to compare bounded cohorts; it must not be
used to auto-enable a plugin or alter a Provider without the existing approval
gate. The schema, privacy exclusions, and cohort rules are defined in
[Agent observability](agent-observability.md).

## 相关文档

- [Desktop shell](desktop-shell.md)
- [Protocol](protocol.md)
- [Security](security.md)
- [Agent observability](agent-observability.md)
