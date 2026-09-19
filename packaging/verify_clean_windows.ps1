param(
    [string]$InputRoot = 'C:\SumikaAcceptanceInput',
    [string]$OutputRoot = 'C:\SumikaAcceptanceResults',
    [string]$WorkRoot = $env:LOCALAPPDATA
)
$ErrorActionPreference = 'Stop'
$work = Join-Path $WorkRoot ('SumikaAcceptance-' + [guid]::NewGuid().ToString('N'))
$report = @{ passed=$false; scope='Install and EXE lifecycle; clean-guest provenance must be checked separately'; work=$work }
# A dedicated output directory is single-use. An interrupted run is unknown,
# never a reason to overwrite evidence or silently replay installation.
foreach ($name in @('report.json','inventory.txt','exe.txt','exe-report.json')) {
    if (Test-Path -LiteralPath (Join-Path $OutputRoot $name)) { throw 'Existing acceptance evidence; use a new output directory' }
}
$progressPath = Join-Path $OutputRoot 'progress.json'
$progressStream = [IO.File]::Open($progressPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
function Write-Stage([string]$Stage, [string]$Status = 'running') {
    $report.stage = $Stage
    $state = @{ stage=$Stage; status=$Status; pid=$PID; work=$work; observed=(Get-Date).ToString('o') }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($state | ConvertTo-Json -Depth 4))
    $progressStream.Position = 0
    $progressStream.Write($bytes, 0, $bytes.Length)
    $progressStream.SetLength($bytes.Length)
    $progressStream.Flush($true)
}
try {
    Write-Stage 'input-validation'
    [IO.Directory]::CreateDirectory($work) | Out-Null
    $spec = Get-Content -LiteralPath (Join-Path $inputRoot 'input.json') -Raw | ConvertFrom-Json
    $report.archive_sha256 = $spec.archive_sha256
    $report.machine = @{ os=[Environment]::OSVersion.VersionString; computer=$env:COMPUTERNAME }
    $product = Join-Path $work 'installed product'
    Write-Stage 'install'
    & (Join-Path $inputRoot 'install_sumika.ps1') -Archive (Join-Path $inputRoot 'Sumika-internal.zip') -Destination $product -Sha256 $spec.archive_sha256
    $python = Join-Path $product 'runtime\python\python.exe'
    Write-Stage 'inventory'
    $inventoryProcess = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', '-B', ('"' + (Join-Path $inputRoot 'verify_portable_staging.py') + '"'), ('"' + $product + '"')) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $outputRoot 'inventory.txt') -RedirectStandardError (Join-Path $outputRoot 'inventory-error.txt')
    if ($inventoryProcess.ExitCode -ne 0) { throw 'Installed inventory verification failed; see inventory-error.txt' }
    Write-Stage 'exe-lifecycle'
    $exeProcess = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', '-B', ('"' + (Join-Path $inputRoot 'verify_portable_exe.py') + '"'), ('"' + $product + '"')) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $outputRoot 'exe.txt') -RedirectStandardError (Join-Path $outputRoot 'exe-error.txt')
    if ($exeProcess.ExitCode -ne 0) { throw 'Installed EXE lifecycle verification failed; see exe-error.txt' }
    $evidence = @(Get-ChildItem -LiteralPath $work -Directory -Filter 'exe-startup-*')
    if ($evidence.Count -ne 1) { throw 'Ambiguous EXE evidence' }
    $result = Get-Content -LiteralPath (Join-Path $evidence[0].FullName 'report.json') -Raw | ConvertFrom-Json
    if (-not $result.passed -or -not $result.test_bridge_stopped) { throw 'EXE lifecycle incomplete' }
    # Export only reports, never the synthetic profile or its request tokens.
    Copy-Item -LiteralPath (Join-Path $evidence[0].FullName 'report.json') -Destination (Join-Path $outputRoot 'exe-report.json')
    $report.checks = $result.checks
    $report.passed = $true
} catch {
    $report.error = $_.Exception.Message
} finally {
    try {
        $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputRoot 'report.json') -Encoding UTF8
        if ($report.passed) { Write-Stage 'complete' 'passed' }
        else { Write-Stage $report.stage 'failed' }
    } finally { $progressStream.Dispose() }
}
if (-not $report.passed) { exit 1 }
