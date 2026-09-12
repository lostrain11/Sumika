# Regression fixture for the shared managed-DSH release description.
#
# It proves that the launcher-facing helpers read one description, that the
# executable comes from that description rather than a copied constant, and
# that a candidate the adapter cannot speak is described but not launchable.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dsh-release.ps1')

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

$releaseId = Get-SumikaDshReleaseId -RepoRoot $repoRoot
Assert-True ($releaseId -eq '0.1.1-rc.2') "the channel default must be the reviewed active release, got '$releaseId'"

$release = Get-SumikaDshRelease -RepoRoot $repoRoot
Assert-True ([string]$release.harness.package -eq '@deepseek-ai/dsh') 'the description must name the harness package'
Assert-True ([string]$release.adapter_contract -eq 'dsh-web-api-v1') 'the active release must expose the implemented contract'

$executable = Get-SumikaDshReleaseExecutable -Release $release
Assert-True ($executable -like '*0.1.1-rc.2*node_modules\.bin\dsh.cmd') "executable must come from the description, got '$executable'"
Assert-True (-not ($executable -like "*$releaseId*$releaseId*")) 'the release id must not be duplicated into the path'

# The install root can be relocated without editing the description.
$env:SUMIKA_DSH_INSTALL_ROOT = 'E:\Relocated\Harness'
try {
    $moved = Get-SumikaDshReleaseExecutable -Release $release
} finally {
    Remove-Item Env:\SUMIKA_DSH_INSTALL_ROOT -ErrorAction SilentlyContinue
}
Assert-True ($moved -like 'E:\Relocated\Harness\0.1.1-rc.2\node_modules\.bin\dsh.cmd') "an install root override must be honoured, got '$moved'"

# A described candidate is inspectable but must not become the default.
$candidate = Get-SumikaDshRelease -RepoRoot $repoRoot -ReleaseId '0.1.5-rc.1' -AllowBlocked
Assert-True ([string]$candidate.status -eq 'blocked') 'the candidate must be described as blocked'
Assert-True (@($candidate.verification.blockers).Count -gt 0) 'a blocked release must record its blockers'
$refused = $false
try {
    Get-SumikaDshRelease -RepoRoot $repoRoot -ReleaseId '0.1.5-rc.1' | Out-Null
} catch {
    $refused = $true
}
Assert-True $refused 'a blocked release must not be launchable'

$lockfile = Get-SumikaDshReleaseLockfilePath -RepoRoot $repoRoot -Release $release
Assert-True (Test-Path -LiteralPath $lockfile -PathType Leaf) 'the frozen lockfile must exist next to the description'
$declaredLock = ([string]$release.toolchain.lockfile_sha256).ToLowerInvariant()
$actualLock = (Get-FileHash -Algorithm SHA256 -LiteralPath $lockfile).Hash.ToLowerInvariant()
Assert-True ($declaredLock -eq $actualLock) 'the frozen lockfile digest must match the description'

$selectable = $false
try {
    Get-SumikaDshRelease -RepoRoot $repoRoot -ReleaseId 'no-such-release' | Out-Null
} catch {
    $selectable = $true
}
Assert-True $selectable 'an unknown release id must fail closed'

'dsh-release regression: passed'
