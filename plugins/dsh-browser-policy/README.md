# Sumika DSH Browser Policy

This package is Sumika's small, replaceable policy companion for the official
Tencent BrowserSkill DSH plugin. BrowserSkill remains responsible for the
browser, extension, DOM/CDP commands, and Agent Window. DeepSeek Harness remains
responsible for tool registration and its approval UI. This package asks the
Sumika Core loopback RPC whether a call may proceed, and fails closed when Core
is unavailable.

The policy request contains only the tool name, action, normalized hostname,
session ownership bit, target kind, and value length. It never sends a selector,
page body, form value, cookie, screenshot, or credential. Sensitive `browser_fill`
calls are denied and the `browser_request_help` tool directs the user to enter
credentials in the isolated browser window.

Install it in the managed DSH profile after the official BrowserSkill plugin:

```powershell
dsh plugin --profile web add file:<repo>/plugins/dsh-browser-policy
```

Use the `file:` form (or `tools/setup-browserskill.ps1
-InstallSumikaPolicyPlugin`) so pnpm copies the package into the managed
profile.  A development `link:` leaves the module rooted in the repository,
where DSH's peer dependencies are not resolvable.

The package does not modify global DSH configuration and does not register a
system URL protocol. It is MIT-licensed Sumika code; it copies no BrowserSkill
or DSH source.
