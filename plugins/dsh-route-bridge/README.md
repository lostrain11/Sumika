# Sumika DSH Route Bridge

This optional plugin exposes Sumika's runtime-neutral route supervisor to a
managed DSH profile.  It adds route catalog/replan/dispatch/status/cancel/retry
tools and the consultation start/status tools.  DSH remains the owner of the
parent Agent turn; the Core only validates, schedules, and returns bounded
worker results.  The bridge exposes the full route lifecycle, including
explicit turn arming and the pending-result mailbox used when a Harness cannot
inject a result into an active turn.

Install only in a managed, reviewed DSH profile:

```powershell
dsh plugin --profile <profile> add file:<repo>\plugins\dsh-route-bridge
```

The bridge talks only to a loopback Core JSON-RPC endpoint.  At plugin load it
performs an explicit `sumika.route.bridge_tools` handshake.  Core reports the
bridge as registered only when the selected Runtime is reachable and the
allow-listed tool set is valid; a file being present is not treated as a
successful mount.  Core restart clears the registration and the plugin will
handshake again.

The plugin rejects credential-shaped values, cookies, JWT/Bearer strings,
credential files, and oversized/deep context before sending anything to Core.
Web answers remain labelled `UNTRUSTED_WEB_RESULT`; they are advice and are
never converted into tool calls by this bridge.

This package does not read DSH/ZCode credentials, start external processes, or
write a workspace.  Worker-side write access still requires the Core's
isolated-worktree and approval gates.

## Tool names

`sumika_route_catalog`, `sumika_route_replan`, `sumika_route_dispatch`,
`sumika_route_status`, `sumika_consultation_start`,
`sumika_consultation_status`, `sumika_route_cancel`, `sumika_route_retry`,
`sumika_route_arm`, `sumika_route_pending`, and `sumika_route_ack`.

The normal turn-boundary sequence is:

1. The parent Agent calls `sumika_route_arm` with an explicit request.
2. The bridge receives a `turn.started`, `tool.completed`, `approval.resolved`,
   `turn.completed`, or `turn.failed` boundary from the Runtime.
3. The parent Agent reads `sumika_route_pending` when the Runtime cannot inject
   a child result directly, then calls `sumika_route_ack` exactly once per
   result.

`sumika_route_dispatch` and `sumika_consultation_start` can still be used
directly for work that should begin immediately.  The Core, rather than the
plugin, enforces concurrency, budget, consent, and retry rules.

Parent session/turn identifiers are taken from explicit arguments when given,
otherwise from the DSH execution context.  The bridge never forwards the
execution context wholesale.
