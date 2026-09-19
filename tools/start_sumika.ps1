param(
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [string]$DataDirectory
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($DataDirectory) { $env:SUMIKA_DATA_DIR = [IO.Path]::GetFullPath($DataDirectory) }
$userDir = if ($env:SUMIKA_DATA_DIR) { $env:SUMIKA_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'Sumika' }
if (Test-Path -LiteralPath (Join-Path $root 'runtime\python')) { $env:SUMIKA_DATA_DIR = $userDir }
$settings = Join-Path $userDir 'role-model-settings.json'
$envFile = Join-Path $userDir 'env.ps1'

# The provider key lives in the user's environment or in a user-profile file;
# it is never stored in the repository.
if (Test-Path -LiteralPath $envFile) { . $envFile }

$bundledPython = Join-Path $root 'runtime\python'
if (Test-Path -LiteralPath $bundledPython) {
    $python = Join-Path $bundledPython 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Bundled Python runtime is incomplete' }
} else { $python = (Get-Command python -ErrorAction Stop).Source }
function Get-BridgeStatus {
    Push-Location $root
    try {
        & $python -B -m ui.bridge_probe --root $root --settings $settings --port $Port
        return $LASTEXITCODE
    } finally { Pop-Location }
}

$bridgeStatus = Get-BridgeStatus
if ($bridgeStatus -eq 0) {
    Write-Host "Sumika 已在运行： http://127.0.0.1:$Port/"
} else {
    if ($bridgeStatus -ne 2) { throw "端口 $Port 的实例归属无法确认；未启动或停止任何服务。" }
    # Start the bridge as a detached hidden process: piping its output here would
    # keep this launcher waiting for the child's redirected handles.
    Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + (Join-Path $PSScriptRoot 'start_ui_bridge.ps1') + '"'),
        '-Port', "$Port", '-Root', ('"' + $root + '"')) | Out-Null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 700
        $bridgeStatus = Get-BridgeStatus
        if ($bridgeStatus -eq 0) { break }
    }
    if ($bridgeStatus -ne 0) { throw "桥接启动失败：端口 $Port 未通过实例身份核验" }
    Write-Host "Sumika 已启动： http://127.0.0.1:$Port/"
}

$keyName = 'DEEPSEEK_API_KEY'
$hasKey = [bool](Get-Item -Path "Env:$keyName" -ErrorAction SilentlyContinue)
if (-not $hasKey) {
    Write-Host ""
    Write-Host "提示：未检测到 $keyName，角色对话会失败关闭（不会回退其他模型）。" -ForegroundColor Yellow
    Write-Host "设置方式（任选其一）："
    Write-Host "  1) 系统环境变量里新增 $keyName"
    Write-Host "  2) 在 $envFile 写入： `$env:$keyName = '你的密钥'"
}

if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
