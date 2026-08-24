[CmdletBinding()]
param(
    [switch]$NoBuild,
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
$tauriCli = Join-Path $repoRoot 'frontend\node_modules\.bin\tauri.cmd'
$ollamaSetup = Join-Path $repoRoot 'tools\setup-ollama.ps1'

if (-not (Test-Path -LiteralPath $tauriCli -PathType Leaf)) {
    throw "Tauri CLI not found. Run 'npm install' in frontend first."
}
if (Get-NetTCPConnection -LocalPort 8771 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8771 is already in use. Stop the desktop development instance before starting another one.'
}

$env:SUMIKA_PYTHON = $pythonPath

Push-Location $repoRoot
try {
    if (-not $SkipModel) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ollamaSetup -Model $Model -ModelsDir $OllamaModelsDir -InstallIfMissing
        if ($LASTEXITCODE -ne 0) { throw "Ollama setup failed with exit code $LASTEXITCODE." }
    }
    if (-not $NoBuild) {
        npm --prefix frontend run build
    }
    & $tauriCli dev --no-dev-server-wait
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri development shell exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
