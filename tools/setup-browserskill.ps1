[CmdletBinding()]
param(
    [string]$Version = '0.1.10',
    [string]$InstallDir = 'D:\Tools\BrowserSkill\0.1.10',
    [string]$DownloadDir = 'D:\Installers',
    [string]$Proxy = [string]$env:SUMIKA_DOWNLOAD_PROXY,
    [switch]$InstallDshPlugin,
    [string]$DshHome = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$targetVersion = $Version.Trim().TrimStart('v')
if ($targetVersion -ne '0.1.10') {
    throw 'This helper is pinned to BrowserSkill CLI 0.1.10. Update the script and its license record before changing the version.'
}

$archiveName = "bsk-v$targetVersion-x86_64-pc-windows-msvc.zip"
$archivePath = Join-Path $DownloadDir $archiveName
$downloadUrl = "https://github.com/Tencent/BrowserSkill/releases/download/cli-v$targetVersion/$archiveName"
$expectedSha256 = '83c1332686f448a8568d25d8528bba92e2fb53fcbaf0ed6b5e36a452dfa88360'

New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    $request = @{ Uri = $downloadUrl; OutFile = $archivePath; UseBasicParsing = $true }
    if (-not [string]::IsNullOrWhiteSpace($Proxy)) { $request.Proxy = $Proxy }
    Write-Host "Downloading BrowserSkill CLI $targetVersion to $archivePath"
    Invoke-WebRequest @request
}

$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
if ($actualSha256 -ne $expectedSha256) {
    throw "BrowserSkill archive SHA-256 mismatch. Expected $expectedSha256, got $actualSha256."
}

$binaryPath = Join-Path $InstallDir 'bsk.exe'
if (Test-Path -LiteralPath $binaryPath -PathType Leaf) {
    # The release archive hash covers the archive, not an extracted binary.
    # Do not silently overwrite a user-managed installation.
    $existingVersion = try { (& $binaryPath --version 2>$null | Select-Object -First 1) } catch { '' }
    if ([string]$existingVersion -notmatch "bsk $targetVersion(?:\s|$)") {
        throw "A different BrowserSkill binary already exists at $binaryPath. Choose another -InstallDir or replace it manually after review."
    }
} else {
    $staging = Join-Path ([IO.Path]::GetTempPath()) "Sumika-BrowserSkill-$targetVersion"
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    try {
        Expand-Archive -LiteralPath $archivePath -DestinationPath $staging -Force
        $stagedBinary = Join-Path $staging 'bsk.exe'
        if (-not (Test-Path -LiteralPath $stagedBinary -PathType Leaf)) { throw 'The BrowserSkill archive did not contain bsk.exe.' }
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        Copy-Item -LiteralPath $stagedBinary -Destination $binaryPath
    } finally {
        if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    }
}

$versionOutput = & $binaryPath --version
if ([string]$versionOutput -notmatch "bsk $targetVersion(?:\s|$)") {
    throw "Installed BrowserSkill CLI did not report version $targetVersion."
}

if ($InstallDshPlugin) {
    $dshCommand = Get-Command dsh -ErrorAction SilentlyContinue
    if (-not $dshCommand) { throw 'dsh was not found. Install DeepSeek Harness or omit -InstallDshPlugin.' }
    $managedHome = if ([string]::IsNullOrWhiteSpace($DshHome)) { Join-Path $repoRoot '.sumika-desktop\dsh-profile' } else { $DshHome }
    New-Item -ItemType Directory -Force -Path $managedHome | Out-Null
    $oldDshHome = $env:DSH_HOME
    try {
        $env:DSH_HOME = (Resolve-Path -LiteralPath $managedHome).Path
        & $dshCommand.Source plugin --profile web add '@wxg-prc-cpg/browser-skill-dsh-plugin'
        if ($LASTEXITCODE -ne 0) { throw "DSH BrowserSkill plugin installation failed with exit code $LASTEXITCODE." }
    } finally {
        $env:DSH_HOME = $oldDshHome
    }
}

[ordered]@{
    ok = $true
    executable = (Resolve-Path -LiteralPath $binaryPath).Path
    version = $targetVersion
    archive = $archivePath
    sha256 = $actualSha256
    dsh_plugin_installed = [bool]$InstallDshPlugin
    next = "Set `$env:SUMIKA_BSK_EXECUTABLE = '$((Resolve-Path -LiteralPath $binaryPath).Path)' before starting Sumika. Install and connect the Chrome/Edge extension manually."
} | ConvertTo-Json -Compress
