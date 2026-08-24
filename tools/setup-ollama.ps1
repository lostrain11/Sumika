[CmdletBinding()]
param(
    [string]$Model = 'qwen3:4b',
    [string]$ModelsDir = [string]$env:SUMIKA_OLLAMA_MODELS,
    [int]$Port = 11434,
    [switch]$InstallIfMissing,
    [switch]$SkipPull,
    [switch]$NoWarmup,
    [string]$Proxy = [string]$env:SUMIKA_DOWNLOAD_PROXY
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $repoRoot '.sumika-desktop\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$serviceLog = Join-Path $logDir 'ollama.log'
$serviceStdoutLog = Join-Path $logDir 'ollama.stdout.log'

function Find-Ollama {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:SUMIKA_OLLAMA)) { $candidates += $env:SUMIKA_OLLAMA }
    $command = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe')
    $candidates += 'C:\Program Files\Ollama\ollama.exe'
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Test-OllamaService {
    param([string]$BaseUrl)
    try {
        $null = Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

function Get-OllamaTags {
    param([string]$BaseUrl)
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 5
        return @($response.models | ForEach-Object { [string]$_.name })
    } catch {
        return @()
    }
}

function Install-Ollama {
    $installerDir = Join-Path ([IO.Path]::GetTempPath()) 'Sumika'
    New-Item -ItemType Directory -Force -Path $installerDir | Out-Null
    $installer = Join-Path $installerDir 'OllamaSetup.exe'
    $curlArgs = @('--fail', '--location', '--retry', '2', '--output', $installer, 'https://ollama.com/download/OllamaSetup.exe')
    if (-not [string]::IsNullOrWhiteSpace($Proxy)) { $curlArgs = @('--proxy', $Proxy) + $curlArgs }
    Write-Host "Downloading the official Ollama installer to $installer"
    & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw 'Ollama installer download failed. Check the configured local network helper or install Ollama manually.'
    }
    Start-Process -FilePath $installer -ArgumentList '/SILENT' -Wait -WindowStyle Hidden
}

$baseUrl = "http://127.0.0.1:$Port"
$ollama = Find-Ollama
if (-not $ollama -and $InstallIfMissing) {
    Install-Ollama
    $ollama = Find-Ollama
}
if (-not $ollama) {
    throw 'Ollama was not found. Install the official Windows package or set SUMIKA_OLLAMA to ollama.exe.'
}

if (-not [string]::IsNullOrWhiteSpace($ModelsDir) -and -not (Test-Path -LiteralPath $ModelsDir -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
}

$oldModels = $env:OLLAMA_MODELS
$oldHost = $env:OLLAMA_HOST
if (-not [string]::IsNullOrWhiteSpace($ModelsDir)) { $env:OLLAMA_MODELS = $ModelsDir }
$env:OLLAMA_HOST = "127.0.0.1:$Port"
try {
    if (-not (Test-OllamaService $baseUrl)) {
        Write-Host "Starting Ollama on $baseUrl"
        Start-Process -FilePath $ollama -ArgumentList 'serve' -WorkingDirectory (Split-Path -Parent $ollama) -WindowStyle Hidden -RedirectStandardOutput $serviceStdoutLog -RedirectStandardError $serviceLog | Out-Null
        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 250
            if (Test-OllamaService $baseUrl) { break }
        } while ((Get-Date) -lt $deadline)
    }
    if (-not (Test-OllamaService $baseUrl)) {
        throw "Ollama did not become ready at $baseUrl. See $serviceLog."
    }

    $tags = Get-OllamaTags $baseUrl
    if ($tags -notcontains $Model) {
        if ($SkipPull) {
            throw "Ollama is ready, but model '$Model' is not installed. Run this script without -SkipPull."
        }
        $oldHttpProxy = $env:HTTP_PROXY
        $oldHttpsProxy = $env:HTTPS_PROXY
        try {
            if (-not [string]::IsNullOrWhiteSpace($Proxy)) {
                $env:HTTP_PROXY = $Proxy
                $env:HTTPS_PROXY = $Proxy
            }
            Write-Host "Pulling Ollama model $Model"
            & $ollama pull $Model
            if ($LASTEXITCODE -ne 0) { throw "ollama pull failed for $Model" }
        } finally {
            $env:HTTP_PROXY = $oldHttpProxy
            $env:HTTPS_PROXY = $oldHttpsProxy
        }
    }

    $tags = Get-OllamaTags $baseUrl
    if ($tags -notcontains $Model) { throw "Model '$Model' is still unavailable after pull." }
    if (-not $NoWarmup) {
        try {
            $warmupBody = @{ model = $Model; prompt = 'ping'; stream = $false; options = @{ num_predict = 1 } } | ConvertTo-Json -Depth 5
            $null = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/generate" -ContentType 'application/json' -Body $warmupBody -TimeoutSec 30
            Write-Verbose "Ollama model warmup completed"
        } catch {
            Write-Warning "Ollama is reachable and the model is installed, but warmup failed: $($_.Exception.Message)"
        }
    }
    Write-Output ([ordered]@{ ok = $true; executable = $ollama; base_url = "$baseUrl/v1"; model = $Model; models_dir = $ModelsDir; model_ready = $true } | ConvertTo-Json -Compress)
} finally {
    if (-not [string]::IsNullOrWhiteSpace($ModelsDir)) { $env:OLLAMA_MODELS = $oldModels }
    $env:OLLAMA_HOST = $oldHost
}
