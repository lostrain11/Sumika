[CmdletBinding()]
param(
    [string]$Version = '0.1.1-rc.2',
    [string]$InstallDir = 'D:\Tools\DeepSeekHarness\0.1.1-rc.2',
    [string]$Proxy = [string]$env:SUMIKA_DOWNLOAD_PROXY
)

$ErrorActionPreference = 'Stop'
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

[ordered]@{
    ok = $true
    executable = (Resolve-Path -LiteralPath $executable).Path
    version = $targetVersion
    install_dir = (Resolve-Path -LiteralPath $InstallDir).Path
    global_path_changed = $false
    next = "Set `$env:SUMIKA_DSH_EXECUTABLE to the executable above and `$env:SUMIKA_DSH_AUTOSTART = '1' before starting the Sumika desktop shell."
} | ConvertTo-Json -Compress
