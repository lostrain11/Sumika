<# Regression fixture for the managed DSH executable boundary. #>
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dsh-launch.ps1')

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

$result = ConvertTo-SumikaDshVersionValidation -Path 'correct.cmd' -OutputLines @($SumikaPinnedDshVersion) -ExitCode 0
Assert-True $result.valid 'exact pinned version should be accepted'

$result = ConvertTo-SumikaDshVersionValidation -Path 'wrong.cmd' -OutputLines @('0.1.0-rc.6') -ExitCode 0
Assert-True (-not $result.valid -and $result.error_category -eq 'version-mismatch') 'old global version should be rejected'

$result = ConvertTo-SumikaDshVersionValidation -Path 'failed.cmd' -OutputLines @($SumikaPinnedDshVersion) -ExitCode 7
Assert-True (-not $result.valid -and $result.error_category -eq 'version-command-failed') 'abnormal version command should fail closed'

$result = ConvertTo-SumikaDshVersionValidation -Path 'empty.cmd' -OutputLines @() -ExitCode 0
Assert-True (-not $result.valid -and $result.error_category -eq 'version-output-empty') 'empty version output should fail closed'

$result = Get-SumikaDshExecutableValidation -Executable (Join-Path $PSScriptRoot 'missing-dsh.cmd')
Assert-True (-not $result.valid -and $result.error_category -eq 'path-not-found') 'missing executable should fail closed'

$result = Get-SumikaDshExecutableValidation -Executable 'dsh.cmd'
Assert-True (-not $result.valid -and $result.error_category -eq 'path-not-absolute') 'PATH names must never be implicit candidates'

if (Test-Path -LiteralPath $SumikaPinnedDshExecutable -PathType Leaf) {
    $result = Get-SumikaDshExecutableValidation -Executable $SumikaPinnedDshExecutable
    Assert-True $result.valid 'the installed pinned executable should pass'
    $custom = Get-SumikaDshExecutableValidation -Executable $result.path
    Assert-True $custom.valid 'an explicitly supplied correct path should pass'
}
$globalDsh = Get-Command dsh -ErrorAction SilentlyContinue
if ($globalDsh -and $globalDsh.Source) {
    $result = Get-SumikaDshExecutableValidation -Executable $globalDsh.Source
    Assert-True (-not $result.valid) 'the globally installed DSH must not silently pass when its version differs'
}

'dsh-launch regression: passed'
