[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Session,
    [Parameter(Mandatory = $true)][int]$TabId,
    [Parameter(Mandatory = $true)][string]$Report,
    [string]$Bsk = 'D:\Tools\BrowserSkill\0.1.11\bsk.exe'
)

$ErrorActionPreference = 'Stop'
$path = [IO.Path]::GetFullPath($Report)
if ([IO.File]::Exists($path)) { throw 'Report already exists; no overwrite.' }
$expression = @'
JSON.stringify((() => {
    if (location.origin !== 'https://modelscope.cn' || location.pathname !== '/magicube/usage') {
        return {ok: false, reason: 'wrong-page'};
    }
    const tab = document.querySelector('.acss-zav6uu > .acss-10mpfo8');
    if (tab?.textContent.trim() !== '\u53d1\u653e\u8bb0\u5f55') {
        return {ok: false, reason: 'select-grant-records'};
    }
    const balances = Array.from(document.querySelectorAll('button[aria-label]'))
        .filter(element => element.getAttribute('aria-label') === 'Magic Cube');
    const balance = balances[0]?.textContent.trim();
    if (balances.length !== 1 || !/^(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?$/.test(balance || '')) {
        return {ok: false, reason: 'missing-or-invalid-balance'};
    }
    const cards = Array.from(document.querySelectorAll('.acss-g3ph6'));
    if (!cards.length || cards.length > 100) return {ok: false, reason: 'empty-or-unbounded-grants'};
    const kinds = new Map([
        ['\u6ce8\u518c\u5e76\u767b\u5f55', 'daily-login'],
        ['\u7ed1\u5b9a\u963f\u91cc\u4e91\u8d26\u53f7', 'aliyun-binding'],
    ]);
    const grants = [];
    const seen = new Set();
    for (const card of cards) {
        const title = card.querySelector('.acss-k9j1zc')?.innerText.split('\n')[0].trim();
        if (!kinds.has(title)) continue;
        const lines = card.querySelector('.acss-1woe9tu')?.innerText.split('\n').map(value => value.trim()).filter(Boolean);
        const date = lines?.[0]?.match(/^(\d{4}-\d{2}-\d{2})\u83b7\u5f97\uff0c\u6709\u6548\u671f([1-9][0-9]{0,2})\u5929$/);
        if (!date || lines.length !== 2 || !/^[1-9][0-9]{0,8}(\.[0-9]{1,2})?$/.test(lines[1])) {
            return {ok: false, reason: 'invalid-grant-row'};
        }
        const instant = new Date(date[1] + 'T00:00:00Z');
        if (!Number.isFinite(instant.getTime()) || instant.toISOString().slice(0, 10) !== date[1]) {
            return {ok: false, reason: 'invalid-grant-date'};
        }
        const identity = kinds.get(title) + ':' + date[1];
        if (seen.has(identity)) return {ok: false, reason: 'duplicate-grant'};
        seen.add(identity);
        grants.push({kind: kinds.get(title), amount: Number(lines[1]), granted_date_display: date[1],
                     validity_days_display: Number(date[2]), expires_at: null});
    }
    if (!grants.length) return {ok: false, reason: 'no-daily-grant-evidence'};
    return {ok: true, schema: 'modelscope-magicube-page-observation/v1', observed_at: new Date().toISOString(),
            source_url: location.origin + location.pathname, source: 'authenticated-page-dom',
            available_balance: Number(balance), unit: 'magicube', grants,
            account_binding_verified: false, automatic_routing_authorized: false,
            exact_expiry_verified: false, billing_reconciliation: 'unverified',
            model_calls: 0, login_or_claim_submitted: false};
})())
'@
$raw = & $Bsk evaluate --session $Session --tab-id $TabId $expression --json
if ($LASTEXITCODE -ne 0) { throw 'Browser query failed; no report saved.' }
$result = ($raw -join "`n") | ConvertFrom-Json
if ($result.ok -ne $true) { throw 'Browser evaluation failed; no report saved.' }
$observation = $result.value | ConvertFrom-Json
if ($observation.ok -ne $true) { throw "Quota observation unavailable: $($observation.reason)" }
$json = $observation | ConvertTo-Json -Depth 8
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
$stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json + [Environment]::NewLine)
    $stream.Write($bytes, 0, $bytes.Length)
} finally {
    $stream.Dispose()
}
$json
