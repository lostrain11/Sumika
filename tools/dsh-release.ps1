# Shared reader for the managed DSH release description.
#
# The description under dsh-release/ is the single place a DSH version,
# executable layout, frozen lockfile and own-plugin set are declared.  The
# launcher, the setup helpers and the desktop shell all read it; none of them
# keeps its own copy of the version.
#
# This file is dot-sourced.  It only reads files and returns objects.

$SumikaDshReleaseSchema = 'sumika.dsh-release/v1'
$SumikaDshReleaseChannelSchema = 'sumika.dsh-release-channel/v1'
$SumikaDshAdapterContract = 'dsh-web-api-v1'

function Get-SumikaDshReleaseRoot {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $override = [string]$env:SUMIKA_DSH_RELEASE_ROOT
    if (-not [string]::IsNullOrWhiteSpace($override)) {
        return [Environment]::ExpandEnvironmentVariables($override.Trim().Trim('"'))
    }
    return (Join-Path $RepoRoot 'dsh-release')
}

function Get-SumikaDshReleaseId {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $override = [string]$env:SUMIKA_DSH_RELEASE
    if (-not [string]::IsNullOrWhiteSpace($override)) {
        return $override.Trim()
    }
    $channelPath = Join-Path (Get-SumikaDshReleaseRoot -RepoRoot $RepoRoot) 'channel.json'
    if (-not (Test-Path -LiteralPath $channelPath -PathType Leaf)) {
        throw "Managed DSH release channel file is missing: $channelPath"
    }
    $channel = Get-Content -LiteralPath $channelPath -Raw | ConvertFrom-Json
    if ([string]$channel.schema -ne $SumikaDshReleaseChannelSchema) {
        throw 'Unsupported managed DSH release channel schema.'
    }
    $default = [string]$channel.default_release
    if ([string]::IsNullOrWhiteSpace($default)) {
        throw 'Managed DSH release channel does not name a default release.'
    }
    return $default.Trim()
}

function Get-SumikaDshRelease {
    <#
      Load one release description.  A release the current adapter cannot speak
      (or one marked blocked) throws unless -AllowBlocked is passed, so a
      candidate can be inspected without becoming launchable.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$ReleaseId = '',
        [switch]$AllowBlocked
    )

    if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
        $ReleaseId = Get-SumikaDshReleaseId -RepoRoot $RepoRoot
    }
    if ($ReleaseId -match '[\\/]') { throw 'Managed DSH release id is invalid.' }
    $relative = Join-Path 'releases' (Join-Path $ReleaseId 'release.json')
    $path = Join-Path (Get-SumikaDshReleaseRoot -RepoRoot $RepoRoot) $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Managed DSH release description is missing: $ReleaseId"
    }
    $release = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if ([string]$release.schema -ne $SumikaDshReleaseSchema) { throw 'Unsupported managed DSH release schema.' }
    if ([string]$release.id -ne $ReleaseId) { throw 'Managed DSH release description does not match its directory.' }
    if (-not $AllowBlocked) {
        if ([string]$release.status -ne 'verified-active') {
            $blockers = @($release.verification.blockers) -join '; '
            throw "Managed DSH release $ReleaseId is '$($release.status)' and is not launchable. $blockers"
        }
        if ([string]$release.adapter_contract -ne $SumikaDshAdapterContract) {
            throw "Managed DSH release $ReleaseId exposes '$($release.adapter_contract)'; the adapter implements $SumikaDshAdapterContract."
        }
    }
    return $release
}

function Get-SumikaDshReleaseInstallDir {
    param([Parameter(Mandatory = $true)]$Release)

    $install = $Release.harness.install
    $root = [string]$env:SUMIKA_DSH_INSTALL_ROOT
    if ([string]::IsNullOrWhiteSpace($root)) {
        $root = [string]$install.root
    } else {
        $root = [Environment]::ExpandEnvironmentVariables($root.Trim().Trim('"'))
    }
    $directory = [string]$install.directory
    return (Join-Path $root $directory)
}

function Get-SumikaDshReleaseExecutable {
    param([Parameter(Mandatory = $true)]$Release)

    $executable = [string]$Release.harness.install.executable
    return (Join-Path (Get-SumikaDshReleaseInstallDir -Release $Release) $executable)
}

function Get-SumikaDshReleaseLockfilePath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)]$Release
    )

    $root = Get-SumikaDshReleaseRoot -RepoRoot $RepoRoot
    return (Join-Path (Join-Path $root (Join-Path 'releases' ([string]$Release.id))) ([string]$Release.toolchain.lockfile))
}

function Test-SumikaDshPluginDigest {
    <#
      Verify the checked-in plugin content against the release description.
      Digests are computed by one implementation only
      (sumika_core.agent.dsh_release) so the helper scripts cannot drift from
      Core's notion of the same release.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)]$Release,
        [string]$Python = 'python'
    )

    $pythonPath = @(
        (Join-Path $RepoRoot 'backend\src'),
        (Join-Path $RepoRoot 'packages\quality-routing\src')
    ) -join [IO.Path]::PathSeparator
    $previous = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $pythonPath
        $output = & $Python -m sumika_core.agent.dsh_release verify ([string]$Release.id) 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $previous
    }
    return [pscustomobject]@{
        ok = $exitCode -eq 0
        detail = (($output | ForEach-Object { [string]$_ }) -join ' ').Trim()
    }
}
