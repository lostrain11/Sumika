# CC Switch compatibility boundary

Sumika follows the public CC Switch provider deep-link format as a removable
import adapter. It does not register the `ccswitch://` system protocol, run CC
Switch, or depend on its UI and internal database schema.

## Supported import

The versioned importer accepts:

- `ccswitch://v1/import?...` provider links for the `codex` application;
- pasted or selected JSON/TOML configurations that expose a Base URL, model,
  and optional API key;
- embedded JSON/TOML configuration carried by a CC Switch link.

The minimum useful mapping is `name`, one or more `endpoint` values, `model`,
and (for authenticated remote services) `apiKey`. Multiple endpoints are
stored, while the first or user-selected endpoint is the current one. Sumika
does not silently fail over between them.

The import preview shows field mappings, unsupported fields, warnings and
masked secrets. Confirmation creates a Sumika draft; it never enables a
module. Unknown fields are retained as bounded source metadata. Values that
look sensitive are moved to Credential Manager references and are not shown in
the preview, SQLite, events or compatibility reports.

CC Switch usage scripts are treated as untrusted JavaScript. Sumika never
executes them. It records only a hash, size and disabled status. A future
declarative usage-query adapter must be reviewed separately.

Unknown protocol versions such as `ccswitch://v2/import` are rejected instead
of being guessed. The current compatibility baseline is CC Switch `v3.20.0`,
commit `5ca9459d50ea4beea6a81bbc509de6ec5b6b09ca`; monitored paths and hashes
are in `docs/integrations/cc-switch-compatibility.json`.

## Updates

Developer > 外部导入兼容性 performs a read-only check on demand. The checker
queries releases, tags and the monitored upstream files, then runs local
fixtures for the importer. It reports:

- `up_to_date` when the pinned protocol and fixtures still match;
- `release_only` when only a release/tag changed;
- `review_required` when monitored implementation or UI files changed;
- `protocol_incompatible` when the v1 parser markers no longer match;
- `check_failed` when the network or response cannot be verified.

The check never changes the importer, existing profiles or user data. GitHub
Actions has the same checker on a weekly schedule and on manual dispatch. It
uses the workflow token to avoid shared-IP API limits; local runs may set
`GITHUB_TOKEN` or `SUMIKA_GITHUB_TOKEN`. A token is sent only as an HTTP
authorization header and is never printed.

Upgrading the compatibility layer requires a human review of the pinned
commit, parser/provider/import-dialog changes, upstream tests, hashes, fixture
coverage and the license ledger. Existing profiles retain their import
snapshot until the user explicitly re-imports and reviews a diff.

## 相关文档

- [Provider profiles](../architecture/provider-profiles.md)
- [状态矩阵](../status-matrix.md)
- [来源与许可证台账](../ui/license-ledger.md)
