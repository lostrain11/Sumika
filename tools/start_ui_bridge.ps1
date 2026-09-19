param(
    [int]$Port = 8765,
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$DataDirectory
)
$ErrorActionPreference = 'Stop'
if ($DataDirectory) { $env:SUMIKA_DATA_DIR = [IO.Path]::GetFullPath($DataDirectory) }
$userDir = if ($env:SUMIKA_DATA_DIR) { $env:SUMIKA_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'Sumika' }
if (Test-Path -LiteralPath (Join-Path $Root 'runtime\python')) { $env:SUMIKA_DATA_DIR = $userDir }
$settings = Join-Path $userDir 'role-model-settings.json'
# The bridge creates disabled defaults on first launch; role setup is optional.
# Optional capability registry; an absent file simply yields an empty list.
$capabilities = Join-Path $userDir 'capabilities.db'
$schedules = Join-Path $userDir 'schedules'
$env:PYTHONUTF8 = '1'
$logDirectory = Join-Path $userDir 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
# The bridge inherits this shell's environment, so the provider key never
# appears in the command line or in any project file.
$bundledPython = Join-Path $Root 'runtime\python'
if (Test-Path -LiteralPath $bundledPython) {
    $python = Join-Path $bundledPython 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Bundled Python runtime is incomplete' }
} else { $python = (Get-Command python -ErrorAction Stop).Source }
$process = Start-Process -FilePath $python -ArgumentList '-B', '-m', 'ui.server', '--port', $Port, '--settings', ('"' + $settings + '"'), '--capabilities', ('"' + $capabilities + '"'), '--schedules', ('"' + $schedules + '"') `
    -WindowStyle Hidden -WorkingDirectory $Root -PassThru `
    -RedirectStandardOutput (Join-Path $logDirectory 'sumika-ui-bridge.out.log') `
    -RedirectStandardError (Join-Path $logDirectory 'sumika-ui-bridge.err.log')
Start-Sleep -Seconds 2
if ($process.HasExited) { throw 'Sumika bridge exited during startup; inspect user data logs' }
[pscustomobject]@{
    pid = $process.Id
    url = "http://127.0.0.1:$Port/"
    settings = $settings
    provider_key_present = [bool]$env:DEEPSEEK_API_KEY
} | ConvertTo-Json
