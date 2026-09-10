# Independent quality-routing DSH adapter

This DSH 0.1.1-rc.2 plugin starts the `quality-routing` Python SDK as a managed
stdio helper. It does not connect to Sumika Core, read Sumika configuration, or
copy provider credentials. The helper child receives a minimal environment and
must be configured with an absolute Python executable and an absolute private
data directory.

The exposed tools are `quality_routing_component_status` and
`quality_routing_offline_fixture`. There is no approve, confirm, provider, or
credential tool. The fixture is deterministic local code; it demonstrates SDK
and process lifecycle only and is not a real model quality evaluation.

Install the SDK in an isolated Python environment, then add this plugin to a
reviewed DSH profile:

```powershell
python -m venv D:\isolated\quality-routing-venv
D:\isolated\quality-routing-venv\Scripts\python.exe -m pip install D:\Code\Sumika\packages\quality-routing
$env:DSH_HOME = 'D:\isolated\dsh-home'
dsh plugin --profile quality-routing add file:D:\Code\Sumika\plugins\dsh-quality-routing
```

Keep the installed profile patch disabled until the absolute paths are set:

```yaml
- id: sumika-quality-routing
  config:
    enabled: true
    pythonExecutable: "D:\\isolated\\quality-routing-venv\\Scripts\\python.exe"
    dataDirectory: "D:\\isolated\\quality-routing-data"
```

Booting the profile starts the helper. Cordis disposal sends a private
`shutdown` request and waits before terminating it. `lifecycle.json` in the
configured data directory records `ready` and `stopped` for local operational
inspection; it contains only the schema, process ID, and lifecycle state.

Remove the profile layer with:

```powershell
dsh plugin --profile quality-routing remove @sumika/dsh-quality-routing
```

Removal does not delete the explicitly configured data directory. After the
profile is stopped and `lifecycle.json` reports `stopped`, the host may archive
or delete that directory according to its own retention policy.

DSH 0.1.1-rc.2 provides `ctx.approval.request` as a one-shot, turn-scoped,
fail-closed approval seam. This offline-only adapter does not request approval
because it cannot execute a real model. A future real executor must inject that
service, require `allowed-once`, and call the SDK approval API privately; it
must not expose approval as a model tool.

