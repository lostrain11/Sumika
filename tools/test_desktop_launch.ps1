<# Offline regression fixture for the desktop launcher boundary. #>
$ErrorActionPreference = 'Stop'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcherFiles = @(Get-ChildItem -LiteralPath $repoRoot -File -Filter '*Sumika.bat')
$desktopRunnerPath = Join-Path $PSScriptRoot 'run-desktop.ps1'
Assert-True ($launcherFiles.Count -eq 1) 'expected exactly one Sumika batch launcher'
$launcher = Get-Content -LiteralPath $launcherFiles[0].FullName -Raw
$desktopRunner = Get-Content -LiteralPath $desktopRunnerPath -Raw
$desktopRunnerCommands = ($desktopRunner -split "`r?`n" | Where-Object { $_ -notmatch '^\s*#' }) -join "`n"

Assert-True ($launcher -match '(?im)^\s*powershell\b.*-File\s+"tools\\run-desktop\.ps1"') 'desktop launcher must invoke run-desktop.ps1'
Assert-True ($launcher -notmatch '(?i)setup-browserskill\.ps1\s+-LaunchAgentBrowser') 'desktop launcher must not open the legacy agent browser'
Assert-True ($desktopRunnerCommands -notmatch '(?i)setup-browserskill\.ps1') 'desktop runner must not invoke the browser setup helper'
Assert-True ($desktopRunnerCommands -notmatch '(?i)LaunchAgentBrowser') 'desktop runner must not request the legacy agent browser'

'desktop launch regression: passed'
