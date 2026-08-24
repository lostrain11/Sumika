param(
    [int]$Port = 8770,
    [string]$DataDir = $null,
    [switch]$SkipModel,
    [string]$Model = 'qwen3:4b',
    [string]$OllamaModelsDir = [string]$env:SUMIKA_OLLAMA_MODELS
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
$ollamaSetup = Join-Path $repoRoot 'tools\setup-ollama.ps1'

$env:PYTHONPATH = Join-Path $repoRoot 'backend/src'
if (-not $SkipModel) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ollamaSetup -Model $Model -ModelsDir $OllamaModelsDir -InstallIfMissing
    if ($LASTEXITCODE -ne 0) { throw "Ollama setup failed with exit code $LASTEXITCODE." }
}
& $pythonPath -m sumika_core --host 127.0.0.1 --port $Port --data-dir $dataPath
