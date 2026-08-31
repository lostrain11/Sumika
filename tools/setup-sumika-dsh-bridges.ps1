[CmdletBinding()]
param(
    [string]$DshHome = '',
    [string]$DshExecutable = '',
    [string]$CoreEndpoint = 'http://127.0.0.1:8771/rpc',
    [string]$PackageDir = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pinnedVersion = '0.1.1-rc.2'
$defaultExecutable = "D:\Tools\DeepSeekHarness\$pinnedVersion\node_modules\.bin\dsh.cmd"
$profileRoot = if ([string]::IsNullOrWhiteSpace($DshHome)) {
    Join-Path $repoRoot '.sumika-desktop\dsh-profile'
} else {
    [Environment]::ExpandEnvironmentVariables($DshHome.Trim().Trim('"'))
}
$profileRoot = (New-Item -ItemType Directory -Force -Path $profileRoot).FullName
$profileRoot = (Resolve-Path -LiteralPath $profileRoot).Path

if ([string]::IsNullOrWhiteSpace($DshExecutable)) {
    if (Test-Path -LiteralPath $defaultExecutable -PathType Leaf) {
        $DshExecutable = $defaultExecutable
    } else {
        $command = Get-Command dsh -ErrorAction SilentlyContinue
        if ($command) { $DshExecutable = $command.Source }
    }
}
if ([string]::IsNullOrWhiteSpace($DshExecutable) -or -not (Test-Path -LiteralPath $DshExecutable -PathType Leaf)) {
    throw "Pinned DSH executable was not found. Install DSH $pinnedVersion or pass -DshExecutable explicitly."
}
$DshExecutable = (Resolve-Path -LiteralPath $DshExecutable).Path
$reportedVersion = try { (& $DshExecutable --version 2>$null | Select-Object -First 1).Trim() } catch { '' }
if ($reportedVersion -ne $pinnedVersion) {
    throw "DSH executable reported '$reportedVersion'; expected '$pinnedVersion'."
}

try {
    $parsedEndpoint = [Uri]$CoreEndpoint
    if ($parsedEndpoint.Scheme -notin @('http', 'https') -or
        $parsedEndpoint.Host -notin @('localhost', '127.0.0.1', '::1') -or
        $parsedEndpoint.UserInfo -or $parsedEndpoint.Query -or $parsedEndpoint.Fragment) {
        throw 'CoreEndpoint must be an http(s) loopback URL without credentials or query data.'
    }
} catch [System.UriFormatException] {
    throw 'CoreEndpoint is not a valid URL.'
}

$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpm) { throw 'pnpm was not found. Install pnpm before installing Sumika DSH bridges.' }
$packageRoot = if ([string]::IsNullOrWhiteSpace($PackageDir)) {
    Join-Path $profileRoot 'packages\sumika-bridges'
} else {
    [Environment]::ExpandEnvironmentVariables($PackageDir.Trim().Trim('"'))
}
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null

$pluginDefinitions = @(
    @{ id = 'sumika-route-bridge'; name = '@sumika/dsh-route-bridge'; path = 'plugins\dsh-route-bridge' },
    @{ id = 'sumika-browser-policy'; name = '@sumika/dsh-browser-policy'; path = 'plugins\dsh-browser-policy' },
    @{ id = 'sumika-desktop-automation'; name = '@sumika/dsh-desktop-automation'; path = 'plugins\dsh-desktop-automation' }
)

function Get-PluginPackage {
    param([hashtable]$Definition)
    $source = Join-Path $repoRoot $Definition.path
    $manifestPath = Join-Path $source 'package.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Sumika bridge package is missing: $manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ([string]$manifest.name -ne $Definition.name) {
        throw "Unexpected package name in $manifestPath."
    }
    $version = [string]$manifest.version
    if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid package version in $manifestPath." }
    Push-Location $source
    try {
        & $pnpm.Source pack --pack-destination $packageRoot | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Packing $($Definition.name) failed with exit code $LASTEXITCODE." }
    } finally { Pop-Location }
    $archive = Get-ChildItem -LiteralPath $packageRoot -Filter '*.tgz' -File |
        Where-Object { $_.Name -like (($Definition.name -replace '^@', '' -replace '/', '-') + '-*.tgz') } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $archive) { throw "No packed archive was produced for $($Definition.name)." }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive.FullName).Hash.ToLowerInvariant()
    $fingerprint = Join-Path $packageRoot ("$($Definition.id)-$version-$($hash.Substring(0, 12)).tgz")
    if (-not (Test-Path -LiteralPath $fingerprint -PathType Leaf)) {
        Copy-Item -LiteralPath $archive.FullName -Destination $fingerprint
    }
    return [pscustomobject]@{
        id = $Definition.id
        name = $Definition.name
        version = $version
        archive = (Resolve-Path -LiteralPath $fingerprint).Path
        sha256 = $hash
    }
}

$oldDshHome = $env:DSH_HOME
$installed = @()
try {
    $env:DSH_HOME = $profileRoot
    foreach ($definition in $pluginDefinitions) {
        $package = Get-PluginPackage $definition
        $packageSpec = 'file:' + ($package.archive -replace '\\', '/')
        # dsh plugin add is idempotent for an identical spec.  If a previous
        # local archive is registered, remove only that exact Sumika package so
        # the lockfile cannot retain a stale junction.
        $profilePackageJson = Join-Path $profileRoot 'profiles\web\package.json'
        $existingSpec = $null
        if (Test-Path -LiteralPath $profilePackageJson -PathType Leaf) {
            $profileManifest = Get-Content -LiteralPath $profilePackageJson -Raw | ConvertFrom-Json
            $deps = $profileManifest.dependencies
            if ($deps) { $existingSpec = [string]$deps.($definition.name) }
        }
        if ($existingSpec -and $existingSpec -ne $packageSpec) {
            & $DshExecutable plugin --profile web remove $definition.name
            if ($LASTEXITCODE -ne 0) { throw "Removing stale $($definition.name) failed with exit code $LASTEXITCODE." }
        }
        if ($existingSpec -ne $packageSpec) {
            & $DshExecutable plugin --profile web add $packageSpec --save-exact
            if ($LASTEXITCODE -ne 0) { throw "Installing $($definition.name) failed with exit code $LASTEXITCODE." }
        }
        $installed += $package
    }
} finally {
    $env:DSH_HOME = $oldDshHome
}

function Set-PatchEntry {
    param(
        [AllowNull()][AllowEmptyCollection()][string[]]$Lines,
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$PackageName,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$ExtraConfig
    )
    if ($null -eq $Lines -or ($Lines.Count -eq 1 -and [string]::IsNullOrEmpty($Lines[0]))) {
        $Lines = [string[]]@()
    }
    $result = [System.Collections.Generic.List[string]]::new()
    $found = $false
    $index = 0
    while ($index -lt $Lines.Count) {
        $line = [string]$Lines[$index]
        if ($line -match ('^\s*-\s*id:\s*' + [regex]::Escape($Id) + '\s*$')) {
            $found = $true
            $result.Add($line)
            $index++
            $block = [System.Collections.Generic.List[string]]::new()
            while ($index -lt $Lines.Count -and [string]$Lines[$index] -notmatch '^\s*-\s*id:\s*') {
                $block.Add([string]$Lines[$index]); $index++
            }
            $configStart = -1
            for ($j = 0; $j -lt $block.Count; $j++) {
                if ($block[$j] -match '^\s*config:\s*$') { $configStart = $j; break }
            }
            if ($configStart -lt 0) {
                $block.Insert(0, '  config:')
                $configStart = 0
            }
            $endpointWritten = $false
            $kept = [System.Collections.Generic.List[string]]::new()
            for ($j = 0; $j -lt $block.Count; $j++) {
                $blockLine = $block[$j]
                if ($blockLine -match '^\s{4}endpoint:\s*') {
                    if (-not $endpointWritten) { $kept.Add("    endpoint: '$Endpoint'"); $endpointWritten = $true }
                    continue
                }
                if ($blockLine -match '^\s{4}(policyTimeoutMs|helpTimeoutMs|enabled):\s*') { continue }
                $kept.Add($blockLine)
            }
            $insertAt = $kept.Count
            for ($j = 0; $j -lt $kept.Count; $j++) {
                if ($kept[$j] -match '^\s{4}endpoint:\s*') { $insertAt = $j + 1; break }
            }
            if (-not $endpointWritten) { $kept.Insert($insertAt, "    endpoint: '$Endpoint'") }
            foreach ($configLine in ($ExtraConfig -split "`n")) { $kept.Add($configLine.TrimEnd("`r")) }
            foreach ($blockLine in $kept) { $result.Add($blockLine) }
            continue
        }
        $result.Add($line); $index++
    }
    if (-not $found) {
        if ($result.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($result[$result.Count - 1])) { $result.Add('') }
        $result.Add("- id: $Id")
        $result.Add("  name: '$PackageName'")
        $result.Add('  config:')
        $result.Add("    endpoint: '$Endpoint'")
        foreach ($configLine in ($ExtraConfig -split "`n")) { $result.Add($configLine.TrimEnd("`r")) }
    }
    return ,$result.ToArray()
}

$patchPath = Join-Path $profileRoot 'profiles\web\cordis.patch.yml'
$patchDirectory = Split-Path -Parent $patchPath
New-Item -ItemType Directory -Force -Path $patchDirectory | Out-Null
if (Test-Path -LiteralPath $patchPath -PathType Leaf) {
    $patchLines = @(Get-Content -LiteralPath $patchPath)
} else {
    # PowerShell unwraps an empty array in a conditional assignment. Keep a
    # harmless comment so the line-oriented patch builder receives a string[].
    $patchLines = @('# Sumika-managed bridge patch entries')
}
$emptyListIndex = -1
$significantPatchLines = @(
    for ($patchIndex = 0; $patchIndex -lt $patchLines.Count; $patchIndex++) {
        $trimmedPatchLine = ([string]$patchLines[$patchIndex]).Trim()
        if ($trimmedPatchLine -and $trimmedPatchLine -notmatch '^#' -and $trimmedPatchLine -ne '---') {
            if ($trimmedPatchLine -match '^\[\s*\]$') { $emptyListIndex = $patchIndex }
            $trimmedPatchLine
        }
    }
)
if ($emptyListIndex -ge 0 -and $significantPatchLines.Count -eq 1) {
    # dsh initializes a fresh patch with an empty YAML list. Replace that
    # placeholder before appending entries; two top-level list documents would
    # make the composed profile invalid.
    $patchLines[$emptyListIndex] = '# Sumika-managed bridge patch entries'
}
$patchLines = Set-PatchEntry -Lines $patchLines -Id 'sumika-route-bridge' -PackageName '@sumika/dsh-route-bridge' -Endpoint $CoreEndpoint -ExtraConfig "    policyTimeoutMs: 1500`n    enabled: true"
$patchLines = Set-PatchEntry -Lines $patchLines -Id 'sumika-browser-policy' -PackageName '@sumika/dsh-browser-policy' -Endpoint $CoreEndpoint -ExtraConfig "    policyTimeoutMs: 1500`n    helpTimeoutMs: 300000"
$patchLines = Set-PatchEntry -Lines $patchLines -Id 'sumika-desktop-automation' -PackageName '@sumika/dsh-desktop-automation' -Endpoint $CoreEndpoint -ExtraConfig "    policyTimeoutMs: 1500`n    enabled: true"
Set-Content -LiteralPath $patchPath -Value (($patchLines -join [Environment]::NewLine).TrimEnd() + [Environment]::NewLine) -Encoding utf8

[ordered]@{
    ok = $true
    dsh_version = $reportedVersion
    dsh_executable = $DshExecutable
    dsh_home = $profileRoot
    core_endpoint = $CoreEndpoint
    packages = @($installed | ForEach-Object {
        [ordered]@{ id = $_.id; name = $_.name; version = $_.version; sha256 = $_.sha256 }
    })
    patch = (Resolve-Path -LiteralPath $patchPath).Path
    next = 'Restart the managed DSH profile, then call sumika.route.bridge_tools and inspect the Agent tool catalog.'
} | ConvertTo-Json -Depth 5 -Compress
