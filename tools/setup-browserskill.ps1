[CmdletBinding()]
param(
    [string]$Version = '0.1.11',
    [string]$InstallDir = 'D:\Tools\BrowserSkill\0.1.11',
    [string]$DownloadDir = 'D:\Installers',
    [string]$Proxy = [string]$env:SUMIKA_DOWNLOAD_PROXY,
    [switch]$InstallDshPlugin,
    [switch]$InstallSumikaPolicyPlugin,
    [string]$DshHome = '',
    [switch]$InstallExtension,
    [switch]$LaunchAgentBrowser,
    [string]$ExtensionDir = 'D:\Tools\BrowserSkill\extension-0.1.7-official',
    [string]$EdgeUserDataDir = 'D:\Tools\BrowserSkill\sumika-agent-profile'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$targetVersion = $Version.Trim().TrimStart('v')
if ($targetVersion -ne '0.1.11') {
    throw 'This helper is pinned to BrowserSkill CLI 0.1.11. Update the script and its license record before changing the version.'
}

$archiveName = "bsk-v$targetVersion-x86_64-pc-windows-msvc.zip"
$archivePath = Join-Path $DownloadDir $archiveName
$downloadUrl = "https://github.com/Tencent/BrowserSkill/releases/download/cli-v$targetVersion/$archiveName"
$expectedSha256 = '041785147342a704fd576470e63307880043a15ad52e0553f12e6dcf360ccf74'
$extensionVersion = '0.1.7'
$extensionArchiveName = "browser-skill-extension-v$extensionVersion-chrome.zip"
$extensionArchivePath = Join-Path $DownloadDir $extensionArchiveName
$extensionDownloadUrl = "https://github.com/Tencent/BrowserSkill/releases/download/ext-v$extensionVersion/$extensionArchiveName"
$extensionExpectedSha256 = '07de2310a6d4c218e017f788f30acbfe88564b0f466e96528d7411fd5bac9ac9'

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

function Ensure-BrowserSkillProfilePatch {
    param(
        [Parameter(Mandatory = $true)][string]$ProfileRoot,
        [Parameter(Mandatory = $true)][string]$ExecutablePath
    )

    $profileDirectory = Join-Path $ProfileRoot 'profiles\web'
    New-Item -ItemType Directory -Force -Path $profileDirectory | Out-Null
    $patchPath = Join-Path $profileDirectory 'cordis.patch.yml'
    $resolvedExecutable = (Resolve-Path -LiteralPath $ExecutablePath).Path
    $yamlExecutable = $resolvedExecutable.Replace("'", "''")
    $entry = @(
        '# Sumika-managed BrowserSkill executable; edit only after reviewing the pinned hash.',
        '- id: browserskill',
        '  config:',
        "    bskPath: '$yamlExecutable'"
    ) -join [Environment]::NewLine

    $existing = if (Test-Path -LiteralPath $patchPath -PathType Leaf) {
        Get-Content -LiteralPath $patchPath -Raw
    } else {
        ''
    }
    if ($existing -match '(?m)^\s*bskPath\s*:') {
        return [pscustomobject]@{ Path = $patchPath; Written = $false; Existing = $true }
    }

    # The profile template is a top-level YAML list.  Keep comments and any
    # existing entries intact, but refuse to append to an unknown root shape;
    # silently producing invalid YAML would prevent the whole DSH profile from
    # booting.  This also handles the stock template's comment + ``[]`` form.
    $lines = if ([string]::IsNullOrEmpty($existing)) { @() } else { $existing -split "`r?`n" }
    $significant = @(
        $lines | Where-Object {
            $trimmedLine = $_.Trim()
            $trimmedLine -and $trimmedLine -notmatch '^#' -and $trimmedLine -ne '---'
        }
    )
    if ($significant.Count -eq 0) {
        $content = $entry + [Environment]::NewLine
    } elseif ($significant.Count -eq 1 -and $significant[0].Trim() -match '^\[\s*\]\s*(?:#.*)?$') {
        $emptyIndex = -1
        for ($index = 0; $index -lt $lines.Count; $index++) {
            if ($lines[$index].Trim() -match '^\[\s*\]\s*(?:#.*)?$') {
                $emptyIndex = $index
                break
            }
        }
        if ($emptyIndex -lt 0) { throw "Could not locate the empty YAML list in $patchPath." }
        $lines[$emptyIndex] = $entry
        $content = ($lines -join [Environment]::NewLine).TrimEnd() + [Environment]::NewLine
    } elseif ($significant[0].TrimStart().StartsWith('-')) {
        $content = $existing.TrimEnd() + [Environment]::NewLine + $entry + [Environment]::NewLine
    } else {
        throw "Unsupported root shape in $patchPath. Expected a top-level YAML list; no changes were written."
    }
    Set-Content -LiteralPath $patchPath -Value $content -Encoding utf8
    [pscustomobject]@{ Path = $patchPath; Written = $true; Existing = $false }
}

$dshPluginInstalled = $false
$sumikaPolicyInstalled = $false
$profilePatchPath = $null
$profilePatchWritten = $false
if ($InstallDshPlugin -or $InstallSumikaPolicyPlugin) {
    $dshCommand = Get-Command dsh -ErrorAction SilentlyContinue
    if (-not $dshCommand) { throw 'dsh was not found. Install DeepSeek Harness or omit the DSH plugin switches.' }
    $managedHome = if ([string]::IsNullOrWhiteSpace($DshHome)) { Join-Path $repoRoot '.sumika-desktop\dsh-profile' } else { $DshHome }
    New-Item -ItemType Directory -Force -Path $managedHome | Out-Null
    $oldDshHome = $env:DSH_HOME
    try {
        $env:DSH_HOME = (Resolve-Path -LiteralPath $managedHome).Path
        if ($InstallDshPlugin) {
            & $dshCommand.Source plugin --profile web add '@wxg-prc-cpg/browser-skill-dsh-plugin@0.1.1'
            if ($LASTEXITCODE -ne 0) { throw "DSH BrowserSkill plugin installation failed with exit code $LASTEXITCODE." }
            $dshPluginInstalled = $true
        }
        if ($InstallDshPlugin -or $InstallSumikaPolicyPlugin) {
            $policyPath = Join-Path $repoRoot 'plugins\dsh-browser-policy'
            if (-not (Test-Path -LiteralPath (Join-Path $policyPath 'package.json') -PathType Leaf)) {
                throw "Sumika browser policy plugin package was not found at $policyPath."
            }
            $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
            if (-not $pnpmCommand) { throw 'pnpm was not found. Install pnpm before installing the Sumika policy plugin.' }

            # A directory `file:` dependency is materialized as a junction by
            # pnpm.  That makes Node resolve peer imports from the repository
            # source tree, where DSH's peers are not present.  Pack the small
            # plugin first so the managed profile receives a real package copy
            # with peers resolved from its own module tree.
            $policyPackageDir = Join-Path $managedHome 'packages\sumika-browser-policy'
            New-Item -ItemType Directory -Force -Path $policyPackageDir | Out-Null
            Push-Location $policyPath
            try {
                & $pnpmCommand.Source pack --pack-destination $policyPackageDir | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Sumika browser policy package packing failed with exit code $LASTEXITCODE." }
            } finally {
                Pop-Location
            }
            $policyArchive = Get-ChildItem -LiteralPath $policyPackageDir -Filter 'sumika-dsh-browser-policy-*.tgz' -File |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if (-not $policyArchive) { throw "Sumika browser policy package archive was not created in $policyPackageDir." }

            # Use a content fingerprint in the filename.  This prevents pnpm
            # from reusing a stale lock entry when the plugin source changed
            # without a package-version bump.
            $policyHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $policyArchive.FullName).Hash.ToLowerInvariant()
            $fingerprintedArchive = Join-Path $policyPackageDir ("sumika-dsh-browser-policy-0.1.0-$($policyHash.Substring(0, 12)).tgz")
            if (-not (Test-Path -LiteralPath $fingerprintedArchive -PathType Leaf)) {
                Copy-Item -LiteralPath $policyArchive.FullName -Destination $fingerprintedArchive
            }
            $policySpec = 'file:' + ($fingerprintedArchive -replace '\\', '/')

            # Older managed profiles may have a directory `file:` dependency
            # recorded as `link:` in pnpm-lock.yaml.  Remove only that exact
            # stale Sumika entry so pnpm can install the packed artifact.
            $lockPath = Join-Path $managedHome 'profiles\web\pnpm-lock.yaml'
            $needsLinkRepair = $false
            if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
                # Keep this check line-oriented.  A multiline `\s*` regex can
                # backtrack across a large lockfile and make setup appear hung.
                $lockLines = @(Get-Content -LiteralPath $lockPath)
                $policyLineIndex = -1
                for ($lockIndex = 0; $lockIndex -lt $lockLines.Count; $lockIndex++) {
                    if ($lockLines[$lockIndex] -match "^(\s*)'@sumika/dsh-browser-policy':\s*$") {
                        $policyLineIndex = $lockIndex
                        $policyIndent = $Matches[1].Length
                        break
                    }
                }
                if ($policyLineIndex -ge 0) {
                    for ($lockIndex = $policyLineIndex + 1; $lockIndex -lt $lockLines.Count; $lockIndex++) {
                        $lockLine = [string]$lockLines[$lockIndex]
                        $trimmedLockLine = $lockLine.Trim()
                        if ($trimmedLockLine -and $trimmedLockLine -notmatch '^#' -and
                            ($lockLine.Length - $lockLine.TrimStart().Length) -le $policyIndent) {
                            break
                        }
                        if ($lockLine -match '^\s+version:\s*link:') {
                            $needsLinkRepair = $true
                            break
                        }
                    }
                }
            }
            $installedPolicy = Join-Path $managedHome 'profiles\web\node_modules\@sumika\dsh-browser-policy'
            if (Test-Path -LiteralPath $installedPolicy) {
                try { $needsLinkRepair = $needsLinkRepair -or ((Get-Item -LiteralPath $installedPolicy).LinkType -eq 'Junction') } catch { }
            }
            if ($needsLinkRepair) {
                & $dshCommand.Source plugin --profile web remove '@sumika/dsh-browser-policy'
                if ($LASTEXITCODE -ne 0) { throw "Stale Sumika browser policy link removal failed with exit code $LASTEXITCODE." }
            }
            & $dshCommand.Source plugin --profile web add $policySpec --save-exact
            if ($LASTEXITCODE -ne 0) { throw "Sumika browser policy plugin installation failed with exit code $LASTEXITCODE." }
            $sumikaPolicyInstalled = $true
        }
        $profilePatch = Ensure-BrowserSkillProfilePatch -ProfileRoot $managedHome -ExecutablePath $binaryPath
        $profilePatchPath = $profilePatch.Path
        $profilePatchWritten = [bool]$profilePatch.Written
    } finally {
        $env:DSH_HOME = $oldDshHome
    }
}

$extensionInstalled = $false
$resolvedExtensionDir = $null
if ($InstallExtension -or $LaunchAgentBrowser) {
    if (-not (Test-Path -LiteralPath $extensionArchivePath -PathType Leaf)) {
        $request = @{ Uri = $extensionDownloadUrl; OutFile = $extensionArchivePath; UseBasicParsing = $true }
        if (-not [string]::IsNullOrWhiteSpace($Proxy)) { $request.Proxy = $Proxy }
        Write-Host "Downloading BrowserSkill extension $extensionVersion to $extensionArchivePath"
        Invoke-WebRequest @request
    }

    $extensionActualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $extensionArchivePath).Hash.ToLowerInvariant()
    if ($extensionActualSha256 -ne $extensionExpectedSha256) {
        throw "BrowserSkill extension archive SHA-256 mismatch. Expected $extensionExpectedSha256, got $extensionActualSha256."
    }

    if (Test-Path -LiteralPath $ExtensionDir -PathType Container) {
        $manifestPath = Join-Path $ExtensionDir 'manifest.json'
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            throw "The configured extension directory exists but has no manifest.json: $ExtensionDir"
        }
        try { $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } catch { throw "The configured extension manifest is invalid: $ExtensionDir" }
        if ([string]$manifest.version -ne $extensionVersion) {
            throw "A different BrowserSkill extension already exists at $ExtensionDir. Choose another -ExtensionDir or replace it after review."
        }
    } else {
        $staging = Join-Path ([IO.Path]::GetTempPath()) ("Sumika-BrowserSkill-extension-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $staging | Out-Null
        try {
            Expand-Archive -LiteralPath $extensionArchivePath -DestinationPath $staging -Force
            $stagedManifest = Join-Path $staging 'manifest.json'
            if (-not (Test-Path -LiteralPath $stagedManifest -PathType Leaf)) { throw 'The BrowserSkill extension archive did not contain manifest.json.' }
            $manifest = Get-Content -LiteralPath $stagedManifest -Raw | ConvertFrom-Json
            if ([string]$manifest.version -ne $extensionVersion) { throw "The extension archive reported unexpected version $($manifest.version)." }
            $parent = Split-Path -Parent $ExtensionDir
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
            Move-Item -LiteralPath $staging -Destination $ExtensionDir
        } finally {
            if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
        }
    }
    $resolvedExtensionDir = (Resolve-Path -LiteralPath $ExtensionDir).Path
    $extensionInstalled = $true
}

$edgeLaunched = $false
$edgePath = $null
if ($LaunchAgentBrowser) {
    $oldAutoUpdate = $env:BSK_AUTO_UPDATE
    try {
        $env:BSK_AUTO_UPDATE = 'off'
        & $binaryPath daemon start --json | Out-Null
    } finally {
        $env:BSK_AUTO_UPDATE = $oldAutoUpdate
    }
    if ($LASTEXITCODE -ne 0) { throw "BrowserSkill daemon failed to start with exit code $LASTEXITCODE." }
    $edgePath = @(
        'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace([string]$edgePath)) { throw 'Microsoft Edge was not found. Install Edge or use -InstallExtension without -LaunchAgentBrowser.' }
    if (-not $resolvedExtensionDir) { throw 'The BrowserSkill extension directory was not prepared.' }
    New-Item -ItemType Directory -Force -Path $EdgeUserDataDir | Out-Null
    $edgeArguments = @(
        "--user-data-dir=$EdgeUserDataDir",
        "--disable-extensions-except=$resolvedExtensionDir",
        "--load-extension=$resolvedExtensionDir",
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-sync',
        'about:blank'
    )
    Start-Process -FilePath $edgePath -ArgumentList $edgeArguments -WindowStyle Normal | Out-Null
    $edgeLaunched = $true
}

$next = if ($LaunchAgentBrowser) {
    'Run bsk doctor --json and verify extension_version 0.1.7.'
} elseif ($InstallExtension) {
    "Run .\tools\setup-browserskill.ps1 -LaunchAgentBrowser to open the managed Edge Agent Window."
} else {
    "Run .\tools\setup-browserskill.ps1 -InstallExtension to prepare the managed Edge extension."
}

[ordered]@{
    ok = $true
    executable = (Resolve-Path -LiteralPath $binaryPath).Path
    version = $targetVersion
    archive = $archivePath
    sha256 = $actualSha256
    dsh_plugin_installed = $dshPluginInstalled
    sumika_policy_plugin_installed = $sumikaPolicyInstalled
    dsh_profile_patch = $profilePatchPath
    dsh_profile_patch_written = $profilePatchWritten
    extension_version = if ($extensionInstalled) { $extensionVersion } else { $null }
    extension_dir = $resolvedExtensionDir
    extension_sha256 = if ($extensionInstalled) { $extensionExpectedSha256 } else { $null }
    edge_launched = $edgeLaunched
    edge_user_data_dir = if ($edgeLaunched) { (Resolve-Path -LiteralPath $EdgeUserDataDir).Path } else { $null }
    next = "Set `$env:SUMIKA_BSK_EXECUTABLE = '$((Resolve-Path -LiteralPath $binaryPath).Path)' before starting Sumika. $next"
} | ConvertTo-Json -Compress
