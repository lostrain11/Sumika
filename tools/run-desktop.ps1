[CmdletBinding()]
param(
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'dsh-launch.ps1')
$pinnedDshVersion = $SumikaPinnedDshVersion
$pinnedDshExecutable = $SumikaPinnedDshExecutable

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
    $configuredAgentEndpoint = [string]$env:SUMIKA_AGENT_ENDPOINT
    $configuredDshEndpoint = [string]$env:SUMIKA_DSH_ENDPOINT
    $endpointWasExplicit = -not [string]::IsNullOrWhiteSpace($configuredAgentEndpoint) -or
        -not [string]::IsNullOrWhiteSpace($configuredDshEndpoint)
    $agentEndpoint = $configuredAgentEndpoint
    if ([string]::IsNullOrWhiteSpace($agentEndpoint)) {
        $agentEndpoint = $configuredDshEndpoint
    }
    if ([string]::IsNullOrWhiteSpace($agentEndpoint)) {
        $agentEndpoint = 'http://127.0.0.1:3080'
    }

    $configuredDshExecutable = [string]$env:SUMIKA_AGENT_EXECUTABLE
    if ([string]::IsNullOrWhiteSpace($configuredDshExecutable)) {
        $configuredDshExecutable = [string]$env:SUMIKA_DSH_EXECUTABLE
    }
    $autostartConfigured = -not [string]::IsNullOrWhiteSpace([string]$env:SUMIKA_AGENT_AUTOSTART) -or
        -not [string]::IsNullOrWhiteSpace([string]$env:SUMIKA_DSH_AUTOSTART)
    $autostartValue = [string]$env:SUMIKA_AGENT_AUTOSTART
    if ([string]::IsNullOrWhiteSpace($autostartValue)) {
        $autostartValue = [string]$env:SUMIKA_DSH_AUTOSTART
    }
    if ($autostartConfigured -and $autostartValue.Trim().ToLowerInvariant() -notin @('0', '1', 'true', 'false', 'yes', 'no')) {
        throw "DSH autostart setting '$autostartValue' is invalid; use 0/1 or true/false."
    }
    $autostartDisabled = $autostartConfigured -and $autostartValue.Trim().ToLowerInvariant() -in @('0', 'false', 'no')
    $validated = $null
    if (-not [string]::IsNullOrWhiteSpace($configuredDshExecutable)) {
        # An explicit path is always checked, even when an external endpoint
        # happens to be healthy, so a wrong version cannot hide in the env.
        $validated = Assert-SumikaDshExecutable -Executable $configuredDshExecutable -ExpectedVersion $pinnedDshVersion
        $configuredDshExecutable = $validated.path
        $env:SUMIKA_AGENT_EXECUTABLE = $configuredDshExecutable
        Write-Host "Validated DSH executable $($validated.display_name) version $($validated.actual_version)."
    }

    if (Test-DshEndpoint -Endpoint $agentEndpoint) {
        if (-not $endpointWasExplicit -and -not $autostartDisabled) {
            throw "Default DSH endpoint $agentEndpoint is healthy, but its package version cannot be verified from host.describe. Set SUMIKA_AGENT_ENDPOINT explicitly to opt into external protocol-only reuse, or stop that endpoint so Sumika can start the pinned DSH $pinnedDshVersion."
        }
        # host.describe proves only that an external protocol endpoint is alive;
        # it does not prove the npm/CLI release. Explicit configuration is the
        # opt-in required to reuse such a process.
        $env:SUMIKA_AGENT_AUTOSTART = '0'
        $env:SUMIKA_DSH_VERSION_VERIFIED = '0'
        Write-Host "Using explicitly allowed external DSH endpoint at $agentEndpoint (protocol health only; package version unknown)."
    }
    else {
        if ($null -eq $validated -and -not $autostartDisabled) {
            $validated = Assert-SumikaDshExecutable -Executable $pinnedDshExecutable -ExpectedVersion $pinnedDshVersion
            $configuredDshExecutable = $validated.path
            $env:SUMIKA_AGENT_EXECUTABLE = $configuredDshExecutable
            Write-Host "Validated pinned DSH executable $($validated.display_name) version $($validated.actual_version)."
        }

        if (-not $autostartConfigured -and -not [string]::IsNullOrWhiteSpace($configuredDshExecutable)) {
            $env:SUMIKA_AGENT_AUTOSTART = '1'
            $env:SUMIKA_DSH_VERSION_VERIFIED = '1'
            Write-Host "Starting managed DSH $pinnedDshVersion from $($validated.display_name)."
        }
        elseif ($autostartConfigured -and -not $autostartDisabled -and -not [string]::IsNullOrWhiteSpace($configuredDshExecutable)) {
            $env:SUMIKA_DSH_VERSION_VERIFIED = '1'
            Write-Host "Starting configured managed DSH $pinnedDshVersion from $($validated.display_name)."
        }
        elseif ($autostartDisabled) {
            $env:SUMIKA_DSH_VERSION_VERIFIED = '0'
            Write-Host 'Managed DSH autostart is explicitly disabled; Core will report an external/unavailable runtime.'
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
