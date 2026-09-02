# Shared, side-effect-free helpers for the managed DSH launch chain.
# This file is dot-sourced by run-desktop.ps1 and by its regression fixture.

$SumikaPinnedDshVersion = '0.1.1-rc.2'
$SumikaPinnedDshExecutable = "D:\Tools\DeepSeekHarness\$SumikaPinnedDshVersion\node_modules\.bin\dsh.cmd"

function Get-SumikaDshDisplayName {
    param([AllowEmptyString()][string]$Executable)

    if ([string]::IsNullOrWhiteSpace($Executable)) {
        return '<unset>'
    }
    try {
        return [IO.Path]::GetFileName($Executable)
    }
    catch {
        return '<invalid-path>'
    }
}

function New-SumikaDshValidationResult {
    param(
        [bool]$Valid,
        [string]$Path,
        [string]$ActualVersion,
        [string]$ErrorCategory,
        [string]$Detail
    )

    [pscustomobject]@{
        valid = $Valid
        path = $Path
        display_name = Get-SumikaDshDisplayName -Executable $Path
        actual_version = $ActualVersion
        error_category = $ErrorCategory
        detail = $Detail
    }
}

function ConvertTo-SumikaDshVersionValidation {
    param(
        [string]$Path,
        [string[]]$OutputLines,
        [int]$ExitCode,
        [string]$ExpectedVersion = $SumikaPinnedDshVersion
    )

    $firstLine = ($OutputLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1)
    $actual = if ($null -eq $firstLine) { '' } else { ([string]$firstLine).Trim() }
    if ($actual.Length -gt 128) {
        $actual = $actual.Substring(0, 128)
    }
    if ($ExitCode -ne 0) {
        return New-SumikaDshValidationResult $false $Path $actual 'version-command-failed' 'the DSH version command returned a non-zero exit code'
    }
    if ([string]::IsNullOrWhiteSpace($actual)) {
        return New-SumikaDshValidationResult $false $Path '' 'version-output-empty' 'the DSH version command returned no version'
    }
    if ($actual -cne $ExpectedVersion) {
        return New-SumikaDshValidationResult $false $Path $actual 'version-mismatch' 'the DSH executable version does not match the pinned release'
    }
    New-SumikaDshValidationResult $true $Path $actual '' 'the DSH executable matches the pinned release'
}

function Get-SumikaDshExecutableValidation {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$Executable,
        [string]$ExpectedVersion = $SumikaPinnedDshVersion
    )

    $candidate = [string]$Executable
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        return New-SumikaDshValidationResult $false '' '' 'path-missing' 'no executable path was supplied'
    }
    try {
        $candidate = [Environment]::ExpandEnvironmentVariables($candidate.Trim().Trim('"'))
    }
    catch {
        return New-SumikaDshValidationResult $false $candidate '' 'path-invalid' 'path expansion failed'
    }
    if ([string]::IsNullOrWhiteSpace($candidate) -or -not [IO.Path]::IsPathRooted($candidate)) {
        return New-SumikaDshValidationResult $false $candidate '' 'path-not-absolute' 'DSH executable must be an absolute path; PATH discovery is disabled'
    }

    try {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return New-SumikaDshValidationResult $false $candidate '' 'path-not-found' 'the configured DSH executable does not exist'
        }
        $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
    }
    catch {
        return New-SumikaDshValidationResult $false $candidate '' 'path-not-found' 'the configured DSH executable could not be resolved'
    }

    try {
        # DSH's npm launcher is a .cmd file. PowerShell invokes it directly and
        # preserves the native exit code while keeping stdout/stderr bounded to
        # the first non-empty line below.
        $outputLines = @(& $resolved --version 2>&1 | ForEach-Object { [string]$_ })
        $exitCode = $LASTEXITCODE
    }
    catch {
        return New-SumikaDshValidationResult $false $resolved '' 'version-command-failed' 'the DSH version command could not be started'
    }
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
    ConvertTo-SumikaDshVersionValidation -Path $resolved -OutputLines $outputLines -ExitCode $exitCode -ExpectedVersion $ExpectedVersion
}

function Assert-SumikaDshExecutable {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$Executable,
        [string]$ExpectedVersion = $SumikaPinnedDshVersion
    )

    $result = Get-SumikaDshExecutableValidation -Executable $Executable -ExpectedVersion $ExpectedVersion
    if (-not $result.valid) {
        $actual = if ([string]::IsNullOrWhiteSpace($result.actual_version)) { '<unavailable>' } else { "'$($result.actual_version)'" }
        throw "DSH executable '$($result.display_name)' rejected [$($result.error_category)]: expected '$ExpectedVersion', actual $actual. Install the pinned DSH release or set SUMIKA_DSH_EXECUTABLE to an absolute path for that exact version."
    }
    $result
}

function Test-PinnedDshExecutable {
    param([string]$Executable)

    return (Get-SumikaDshExecutableValidation -Executable $Executable -ExpectedVersion $SumikaPinnedDshVersion).valid
}
