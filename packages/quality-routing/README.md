# quality-routing

`quality-routing` is a host-neutral coordinator for bounded, quality-first task plans. It does not discover credentials, configure providers, invoke a shell, or grant approval.

## Compatibility boundaries

The SDK relies on host-supplied verifier callback evidence; it does not provide a general proof of quality. It includes no built-in ZCode or workspace executor. Revisions retain the task's original approved quality baselines and allowed file grant, and cannot expand either boundary.

Hosts can set `Candidate.execution_revision` to an opaque, non-secret revision of the endpoint, credential reference revision, model configuration, and price terms. It becomes part of the approved candidate identity, including auxiliary calls and persisted task snapshots. A changed revision cannot reuse an old approval. Candidates that omit it keep the original identity format; old unversioned approvals do not match newly versioned candidates. Create and confirm a new plan when its execution binding changes. Hosts must still recheck current authorization and resource reservations immediately before sending; the SDK does not read provider settings or guarantee account balances.

## Cost quotes and funding

`Candidate.quote(input_tokens, output_tokens, cached_tokens=0)` returns a `RouteQuote`.
Input tokens include cached tokens; the cached count is a subset, not additional input.
Quotes separate provider charge/currency, cash due in CNY, consumed resource acquisition
value, effective cost, availability, and resource allocations. `Candidate.estimate()`
returns effective cost (cash due plus acquisition value), or `None` when unknown.

`FundingLot.kind` is `grant`, `purchased`, or `unknown`. Purchased resources require
an evidenced `value_per_unit_cny` to compare their consumption cost; using an already
purchased pack is not free. Grants consume zero acquisition value. Expired or insufficient
bound resources cannot silently fall back to cash. `cost_order()` ranks only after the
host's quality/permission gates; a cash balance does not make a priced route free.

Legacy `prepaid_tokens`/`prepaid_until` remain supported, but now default to unknown
funding. Explicit `funding_kind="grant"` is required for evidenced grants; purchased
token packs use `resource_value_per_token_cny`. Preserve unknown data during migration.

Hosts may inject `Candidate.quote_provider` for current shared-pool quotes and set
`pricing_revision`. The Sumika adapter includes the pricing revision in its
`execution_revision`; other hosts must do the same. Callbacks are process-local and
are not persisted. Quoting does not reserve resources or report actual paid receipts;
the host must enforce both immediately around execution. See the
[Sumika integration](../../docs/refactor/unified-route-costs.md).

## Local SDK install

From this package root, install the dependency-free SDK into the active environment:

```powershell
python -m pip install .
```

## Offline SDK example

The SDK has no required runtime dependencies. The example uses a local fake executor and sanitized task data only:

```powershell
python examples/offline_sdk.py
```

## Optional MCP stdio adapter

Install the optional extra in the host application's isolated environment:

```powershell
python -m pip install ".[mcp]"
```

`quality-routing-mcp` starts a standalone read-only stdio server, bound to `Scope("local", "default")` with an empty catalog and no executor. It exposes only `quality_catalog`, `quality_status`, and `quality_result`; its catalog explicitly reports execution and submission as unavailable. A host that needs task submission must bind its own `Coordinator`, one fixed `Scope`, and a policy callback:

```python
from quality_routing import BudgetRule, Candidate, Coordinator, Outcome, Quote, Scope, Verification
from quality_routing.mcp_server import SubmissionAuthorization, create_server

scope = Scope("demo-owner", "demo-session")
coordinator = Coordinator(
    [Candidate("demo", "demo-account", "demo-model", "api", authorized=True, available=True, external=False, fixed_cash="0")],
    executor=lambda execution: Outcome("completed", "offline-result", cash_cny="0"),
    verifier=lambda execution, outcome: Verification(True, ("offline-check",)),
    permission=lambda execution: True,
)

def host_policy(action, bound_scope, value):
    if action == "submit":
        return SubmissionAuthorization(Quote("0", "0", "1", 2, 10000), BudgetRule(), frozenset({"demo"}))
    return action in {"revise", "advance"}

server = create_server(coordinator, scope, host_policy)
server.run(transport="stdio")
```

The host owns approval. The MCP surface cannot approve tasks, choose a scope, set account balances, enable providers, read keys, run scripts, or call a provider directly. `quality_advance` calls `Coordinator.advance` only after the host has separately approved the task and the host policy callback accepts the action. The callback receives the current `Plan` for `advance`, while the Coordinator retains the task's original scope, candidate pool, external permission, and budget grant across revisions.

The host-bound server exposes `quality_catalog`, `quality_status`, `quality_result`, `quality_submit`, `quality_revise`, and `quality_advance`.
