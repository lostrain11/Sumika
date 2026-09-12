[CmdletBinding()]
param(
    [string]$Version = '',
    [string]$InstallDir = '',
    [string]$Proxy = [string]$env:SUMIKA_DOWNLOAD_PROXY,
    [switch]$InstallSumikaBridges,
    [string]$DshHome = '',
    [switch]$AllowCandidate
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'dsh-release.ps1')

$release = Get-SumikaDshRelease -RepoRoot $repoRoot -ReleaseId $Version.Trim().TrimStart('v') -AllowBlocked:$AllowCandidate
if ([string]$release.status -ne 'verified-active' -and -not $AllowCandidate) {
    throw "Release $($release.id) is '$($release.status)' and will not be installed as the default. Pass -AllowCandidate with -Version to stage it for isolated review."
}
$targetVersion = [string]$release.harness.version
# The description, not this script, decides where the release lives.
$installDir = if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    Get-SumikaDshReleaseInstallDir -Release $release
} else {
    [Environment]::ExpandEnvironmentVariables($InstallDir.Trim().Trim('"'))
}
$executable = Join-Path $installDir ([string]$release.harness.install.executable)
$lockfile = Get-SumikaDshReleaseLockfilePath -RepoRoot $repoRoot -Release $release
$declaredLockfileDigest = ([string]$release.toolchain.lockfile_sha256).ToLowerInvariant()

if (-not (Test-Path -LiteralPath $lockfile -PathType Leaf)) {
    throw "Frozen lockfile is missing: $lockfile"
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $lockfile).Hash.ToLowerInvariant() -ne $declaredLockfileDigest) {
    throw "Frozen lockfile does not match release $($release.id); installation stopped before changing the target."
}

$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpm) {
    throw 'pnpm was not found. Install pnpm, then run this explicit setup helper again.'
}

$existingVersion = ''
if (Test-Path -LiteralPath $executable -PathType Leaf) {
    $existingVersion = try { (& $executable --version 2>$null | Select-Object -First 1).Trim() } catch { '' }
    if ($existingVersion -ne $targetVersion) {
        throw "A different DSH version already exists at $executable. Choose another -InstallDir or replace it manually after review."
    }
}

if ($existingVersion -ne $targetVersion) {
    if (Test-Path -LiteralPath $installDir -PathType Container) {
        $existingItems = @(Get-ChildItem -LiteralPath $installDir -Force)
        if ($existingItems.Count -gt 0) {
            throw "Install directory is non-empty and has no verified managed executable: $installDir"
        }
    }
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    # Install from the frozen lockfile the description pins.  Nothing is
    # resolved from ranges, so the installed tree is reproducible and its
    # virtual-store lockfile can be compared byte for byte afterwards.
    Copy-Item -LiteralPath $lockfile -Destination (Join-Path $installDir 'pnpm-lock.yaml') -Force
    $dependencies = @{}
    $dependencies[[string]$release.harness.package] = $targetVersion
    Set-Content -LiteralPath (Join-Path $installDir 'package.json') -Encoding utf8 `
        -Value (@{ private = $true; dependencies = $dependencies } | ConvertTo-Json)
    $oldHttpProxy = $env:HTTP_PROXY
    $oldHttpsProxy = $env:HTTPS_PROXY
    try {
        if (-not [string]::IsNullOrWhiteSpace($Proxy)) {
            $env:HTTP_PROXY = $Proxy
            $env:HTTPS_PROXY = $Proxy
        }
        & $pnpm.Source install --dir $installDir --frozen-lockfile --ignore-scripts
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

# The install identity is only claimed when the installed virtual-store
# lockfile is the frozen one the description pins.
$installEvidence = 'declared-unverified'
$installedLockfile = Join-Path $installDir 'node_modules\.pnpm\lock.yaml'
if (Test-Path -LiteralPath $installedLockfile -PathType Leaf) {
    $installedDigest = (Get-FileHash -Algorithm SHA256 -LiteralPath $installedLockfile).Hash.ToLowerInvariant()
    if ($installedDigest -ne $declaredLockfileDigest) {
        throw @"
The DSH tree at $installDir was resolved without the frozen lockfile, so it is not the combination release $($release.id) describes.
  declared  $declaredLockfileDigest
  installed $installedDigest
Nothing was changed. Either keep using this tree as an unpinned install, or move it aside and re-run this helper to adopt the frozen combination.
"@
    }
    $installEvidence = 'frozen-lockfile-verified'
}

$pluginCheck = Test-SumikaDshPluginDigest -RepoRoot $repoRoot -Release $release
if (-not $pluginCheck.ok) {
    throw "Own-plugin content no longer matches release $($release.id): $($pluginCheck.detail)"
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
    $bridgeArgs.Version = $release.id
    if (-not [string]::IsNullOrWhiteSpace($InstallDir)) { $bridgeArgs.InstallDir = $installDir }
    if ($AllowCandidate) { $bridgeArgs.AllowCandidate = $true }
    $bridgeResult = & $bridgeScript @bridgeArgs | Select-Object -Last 1
}

[ordered]@{
    ok = $true
    executable = (Resolve-Path -LiteralPath $executable).Path
    version = $targetVersion
    release = [string]$release.id
    install_dir = (Resolve-Path -LiteralPath $installDir).Path
    install_evidence = $installEvidence
    frozen_lockfile_sha256 = $declaredLockfileDigest
    global_path_changed = $false
    bridges = if ($InstallSumikaBridges) { $bridgeResult } else { $null }
    next = if ($InstallSumikaBridges) { "Restart the managed DSH profile and verify sumika.route.bridge_tools before running the desktop." } else { "Run tools\setup-dsh.ps1 -InstallSumikaBridges, then tools\run-desktop.ps1. The Windows launcher will discover this pinned executable and start it only when no healthy DSH endpoint already exists." }
} | ConvertTo-Json -Compress
