[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Session,
    [Parameter(Mandatory = $true)][int]$TabId,
    [Parameter(Mandatory = $true)][string]$Report,
    [string]$Bsk = 'D:\Tools\BrowserSkill\0.1.11\bsk.exe'
)

$ErrorActionPreference = 'Stop'
$expression = @'
JSON.stringify((() => {
    const allowedPaths = ['/finance/resourcepack', '/finance-center/resource-package/package-mgmt'];
    if (location.hostname !== 'open.bigmodel.cn' || !allowedPaths.includes(location.pathname)) {
        return {ok: false, reason: 'wrong-page'};
    }
    if (document.querySelector('#tab-my')?.getAttribute('aria-selected') !== 'true') {
        return {ok: false, reason: 'select-my-resource-packs-after-login'};
    }
    const labels = ['资源包名称', '资源包类型', '资源包状态', '适用场景', '当前余额', '当前可用余额', '购买时间', '生效时间', '到期时间'];
    const headers = Array.from(document.querySelectorAll('.el-table__header-wrapper th')).map(cell => cell.textContent.trim());
    if (labels.some((label, index) => headers[index] !== label)) {
        return {ok: false, reason: 'table-schema-changed'};
    }
    const rows = Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr'));
    if (!rows.length || rows.length > 100) return {ok: false, reason: 'empty-or-unbounded-table'};
    const fields = ['name', 'type', 'status', 'applicability', 'balance', 'available_balance', 'purchased_at_display', 'starts_at_display', 'expires_at_display'];
    const packs = [];
    for (const row of rows) {
        const cells = Array.from(row.querySelectorAll('td')).map(cell => cell.textContent.trim());
        if (cells.length < labels.length || cells.slice(0, labels.length).some(text => !text || text.length > 2000)) {
            return {ok: false, reason: 'incomplete-row'};
        }
        packs.push(Object.fromEntries(fields.map((field, index) => [field, cells[index]])));
    }
    return {
        ok: true,
        schema: 'zhipu-resource-pack-page-observation/v1',
        observed_at: new Date().toISOString(),
        source_url: location.origin + location.pathname,
        source: 'authenticated-page-dom',
        account_binding_verified: false,
        automatic_routing_authorized: false,
        billing_reconciliation: 'unverified',
        displayed_timezone: 'unspecified-by-page',
        scope: 'current-rendered-table-only',
        pagination_display: Array.from(document.querySelectorAll('.el-pagination')).map(element => element.innerText),
        packs
    };
})())
'@
$raw = & $Bsk evaluate --session $Session --tab-id $TabId $expression --json
if ($LASTEXITCODE -ne 0) { throw 'Browser query failed; no observation was saved.' }
$result = ($raw -join "`n") | ConvertFrom-Json
if ($result.ok -ne $true) { throw 'Browser evaluation failed; no observation was saved.' }
$observation = $result.value | ConvertFrom-Json
if ($observation.ok -ne $true) { throw "Resource query unavailable: $($observation.reason)" }
$json = $observation | ConvertTo-Json -Depth 8
$path = [IO.Path]::GetFullPath($Report)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
[IO.File]::WriteAllText($path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
$json
