[CmdletBinding()]
param(
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pinnedDshVersion = '0.1.1-rc.2'
$pinnedDshExecutable = "D:\Tools\DeepSeekHarness\$pinnedDshVersion\node_modules\.bin\dsh.cmd"

function Test-DshEndpoint {
    param([string]$Endpoint)

    try {
        $request = [ordered]@{
            type = 'client-request'
            rpcId = 'sumika-launch-check'
            method = 'host.describe'
            payload = @{}
        } | ConvertTo-Json -Compress
        $requestParameters = @{
            UseBasicParsing = $true
            Uri = $Endpoint.TrimEnd('/') + '/api/host.describe'
            Method = 'Post'
            ContentType = 'application/json'
            Body = $request
            TimeoutSec = 1
        }
        $response = Invoke-WebRequest @requestParameters
        $payload = $response.Content | ConvertFrom-Json
        return $response.StatusCode -eq 200 -and $payload.result.ok -eq $true
    }
    catch {
        return $false
    }
}

function Test-PinnedDshExecutable {
    param([string]$Executable)

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $false
    }
    try {
        $reportedVersion = (& $Executable --version 2>$null | Select-Object -First 1).Trim()
        return $reportedVersion -eq $pinnedDshVersion
    }
    catch {
        return $false
    }
}

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
if (-not (Test-Path -LiteralPath $tauriCli -PathType Leaf)) {
    throw "Tauri CLI not found. Run 'npm install' in frontend first."
}
if (Get-NetTCPConnection -LocalPort 8771 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8771 is already in use. Stop the desktop development instance before starting another one.'
}

$env:SUMIKA_PYTHON = $pythonPath
# Keep the managed BrowserSkill daemon on the pinned release. This applies
# only to the Sumika process tree and does not change the user's environment.
$env:BSK_AUTO_UPDATE = 'off'

# Reuse the explicitly configured BrowserSkill CLI, or the pinned installation
# created by setup-browserskill.ps1. This only discovers an existing binary;
# it never installs, updates, or starts a browser.
$pinnedBrowserSkillExecutable = 'D:\Tools\BrowserSkill\0.1.11\bsk.exe'
$configuredBrowserSkill = [string]$env:SUMIKA_BSK_EXECUTABLE
if ([string]::IsNullOrWhiteSpace($configuredBrowserSkill) -and (Test-Path -LiteralPath $pinnedBrowserSkillExecutable -PathType Leaf)) {
    $env:SUMIKA_BSK_EXECUTABLE = (Resolve-Path -LiteralPath $pinnedBrowserSkillExecutable).Path
    Write-Host "Using BrowserSkill CLI at $env:SUMIKA_BSK_EXECUTABLE."
}

# The official DSH BrowserSkill plugin launches `bsk` by name.  Keep the
# executable override for Sumika Core and add its parent directory only to
# this process tree, so DSH can resolve the same pinned binary without
# changing the user's system PATH.
$browserSkillPath = [string]$env:SUMIKA_BSK_EXECUTABLE
if (-not [string]::IsNullOrWhiteSpace($browserSkillPath)) {
    $browserSkillPath = [Environment]::ExpandEnvironmentVariables($browserSkillPath.Trim().Trim('"'))
    if ([IO.Path]::IsPathRooted($browserSkillPath) -and (Test-Path -LiteralPath $browserSkillPath -PathType Leaf)) {
        $browserSkillDirectory = (Resolve-Path -LiteralPath $browserSkillPath).Path | Split-Path -Parent
        $pathEntries = @([Environment]::GetEnvironmentVariable('PATH', 'Process') -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if (-not ($pathEntries | Where-Object { $_.TrimEnd('\').Equals($browserSkillDirectory.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) })) {
            $env:Path = "$browserSkillDirectory;$env:Path"
            Write-Host "Added BrowserSkill directory to the managed process PATH."
        }
    }
}

$agentRuntime = [string]$env:SUMIKA_AGENT_RUNTIME
if ([string]::IsNullOrWhiteSpace($agentRuntime)) {
    $agentRuntime = 'dsh'
}
if ($agentRuntime.Trim().ToLowerInvariant() -eq 'dsh') {
    $agentEndpoint = [string]$env:SUMIKA_AGENT_ENDPOINT
    if ([string]::IsNullOrWhiteSpace($agentEndpoint)) {
        $agentEndpoint = [string]$env:SUMIKA_DSH_ENDPOINT
    }
    if ([string]::IsNullOrWhiteSpace($agentEndpoint)) {
        $agentEndpoint = 'http://127.0.0.1:3080'
    }

    if (Test-DshEndpoint -Endpoint $agentEndpoint) {
        # Never start a duplicate runtime on an endpoint that already passed
        # the pinned DSH health contract. The existing process stays external.
        $env:SUMIKA_AGENT_AUTOSTART = '0'
        Write-Host "Using existing DSH runtime at $agentEndpoint."
    }
    else {
        $configuredDshExecutable = [string]$env:SUMIKA_AGENT_EXECUTABLE
        if ([string]::IsNullOrWhiteSpace($configuredDshExecutable)) {
            $configuredDshExecutable = [string]$env:SUMIKA_DSH_EXECUTABLE
        }
        if ([string]::IsNullOrWhiteSpace($configuredDshExecutable) -and (Test-PinnedDshExecutable -Executable $pinnedDshExecutable)) {
            $configuredDshExecutable = $pinnedDshExecutable
            $env:SUMIKA_AGENT_EXECUTABLE = $configuredDshExecutable
        }

        $autostartConfigured = -not [string]::IsNullOrWhiteSpace([string]$env:SUMIKA_AGENT_AUTOSTART) -or
            -not [string]::IsNullOrWhiteSpace([string]$env:SUMIKA_DSH_AUTOSTART)
        if (-not $autostartConfigured -and -not [string]::IsNullOrWhiteSpace($configuredDshExecutable)) {
            $env:SUMIKA_AGENT_AUTOSTART = '1'
            Write-Host "Starting managed DSH $pinnedDshVersion from $configuredDshExecutable."
        }
        elseif (-not $autostartConfigured) {
            Write-Warning "Pinned DSH $pinnedDshVersion is not installed at $pinnedDshExecutable. The desktop will start, but Agent remains unavailable until DSH is installed or an endpoint is configured."
        }
    }
}

Push-Location $repoRoot
try {
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
