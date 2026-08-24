param(
    [int]$Port = 8770,
    [string]$DataDir = $null
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configuredPythonPath = [string]$env:SUMIKA_PYTHON
if ([string]::IsNullOrWhiteSpace($configuredPythonPath)) {
    $configuredPythonPath = 'python'
} else {
    $configuredPythonPath = [Environment]::ExpandEnvironmentVariables($configuredPythonPath.Trim().Trim('"'))
}
$pythonCommand = Get-Command $configuredPythonPath -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonPath = $pythonCommand.Source
} elseif ([IO.Path]::IsPathRooted($configuredPythonPath) -and (Test-Path -LiteralPath $configuredPythonPath -PathType Leaf)) {
    $pythonPath = (Resolve-Path -LiteralPath $configuredPythonPath).Path
} else {
    throw "Python was not found. Install Python or set SUMIKA_PYTHON to an executable path."
}
$dataPath = if ([string]::IsNullOrWhiteSpace($DataDir)) {
    Join-Path $repoRoot '.sumika'
} else {
    $DataDir
}
$env:PYTHONPATH = Join-Path $repoRoot 'backend/src'
& $pythonPath -m sumika_core --host 127.0.0.1 --port $Port --data-dir $dataPath
