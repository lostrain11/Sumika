[CmdletBinding()]
param(
    [string]$Version = '0.1.1-rc.2',
    [string]$InstallDir = 'D:\Tools\DeepSeekHarness\0.1.1-rc.2',
    [string]$Proxy = [string]$env:SUMIKA_DOWNLOAD_PROXY,
    [switch]$InstallSumikaBridges,
    [string]$DshHome = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$targetVersion = $Version.Trim().TrimStart('v')
if ($targetVersion -ne '0.1.1-rc.2') {
    throw 'This helper is pinned to DSH 0.1.1-rc.2. Update the script and its license record before changing the version.'
}

$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpm) {
    throw 'pnpm was not found. Install pnpm, then run this explicit setup helper again.'
}

$executable = Join-Path $InstallDir 'node_modules\.bin\dsh.cmd'
$existingVersion = ''
if (Test-Path -LiteralPath $executable -PathType Leaf) {
    $existingVersion = try { (& $executable --version 2>$null | Select-Object -First 1).Trim() } catch { '' }
    if ($existingVersion -ne $targetVersion) {
        throw "A different DSH version already exists at $executable. Choose another -InstallDir or replace it manually after review."
    }
}

if ($existingVersion -ne $targetVersion) {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $oldHttpProxy = $env:HTTP_PROXY
    $oldHttpsProxy = $env:HTTPS_PROXY
    try {
        if (-not [string]::IsNullOrWhiteSpace($Proxy)) {
            $env:HTTP_PROXY = $Proxy
            $env:HTTPS_PROXY = $Proxy
        }
        & $pnpm.Source add --dir $InstallDir --lockfile=false --ignore-scripts "@deepseek-ai/dsh@$targetVersion"
        if ($LASTEXITCODE -ne 0) {
            throw "DSH installation failed with exit code $LASTEXITCODE."
        }
    } finally {
        $env:HTTP_PROXY = $oldHttpProxy
        $env:HTTPS_PROXY = $oldHttpsProxy
    }
}

if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "DSH executable was not found after installation: $executable"
}
$reportedVersion = (& $executable --version 2>$null | Select-Object -First 1).Trim()
if ($reportedVersion -ne $targetVersion) {
    throw "Installed DSH reported '$reportedVersion', expected '$targetVersion'."
}

$bridgeResult = $null
if ($InstallSumikaBridges) {
    $bridgeScript = Join-Path $repoRoot 'tools\setup-sumika-dsh-bridges.ps1'
    if (-not (Test-Path -LiteralPath $bridgeScript -PathType Leaf)) {
        throw "Sumika DSH bridge installer was not found: $bridgeScript"
    }
    $bridgeArgs = @{
        DshExecutable = $executable
    }
    if (-not [string]::IsNullOrWhiteSpace($DshHome)) { $bridgeArgs.DshHome = $DshHome }
    $bridgeResult = & $bridgeScript @bridgeArgs | Select-Object -Last 1
}

[ordered]@{
    ok = $true
    executable = (Resolve-Path -LiteralPath $executable).Path
    version = $targetVersion
    install_dir = (Resolve-Path -LiteralPath $InstallDir).Path
    global_path_changed = $false
    bridges = if ($InstallSumikaBridges) { $bridgeResult } else { $null }
    next = if ($InstallSumikaBridges) { "Restart the managed DSH profile and verify sumika.route.bridge_tools before running the desktop." } else { "Run tools\setup-dsh.ps1 -InstallSumikaBridges, then tools\run-desktop.ps1. The Windows launcher will discover this pinned executable and start it only when no healthy DSH endpoint already exists." }
} | ConvertTo-Json -Compress
