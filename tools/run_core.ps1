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
# Keep BrowserSkill updates explicit and user-controlled for this process.
$env:BSK_AUTO_UPDATE = 'off'
if ([string]::IsNullOrWhiteSpace([string]$env:SUMIKA_BSK_EXECUTABLE)) {
    $pinnedBrowserSkillExecutable = 'D:\Tools\BrowserSkill\0.1.11\bsk.exe'
    if (Test-Path -LiteralPath $pinnedBrowserSkillExecutable -PathType Leaf) {
        $env:SUMIKA_BSK_EXECUTABLE = (Resolve-Path -LiteralPath $pinnedBrowserSkillExecutable).Path
    }
}
$browserSkillPath = [string]$env:SUMIKA_BSK_EXECUTABLE
if (-not [string]::IsNullOrWhiteSpace($browserSkillPath)) {
    $browserSkillPath = [Environment]::ExpandEnvironmentVariables($browserSkillPath.Trim().Trim('"'))
    if ([IO.Path]::IsPathRooted($browserSkillPath) -and (Test-Path -LiteralPath $browserSkillPath -PathType Leaf)) {
        $browserSkillDirectory = (Resolve-Path -LiteralPath $browserSkillPath).Path | Split-Path -Parent
        $pathEntries = @([Environment]::GetEnvironmentVariable('PATH', 'Process') -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if (-not ($pathEntries | Where-Object { $_.TrimEnd('\').Equals($browserSkillDirectory.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) })) {
            $env:Path = "$browserSkillDirectory;$env:Path"
        }
    }
}
& $pythonPath -m sumika_core --host 127.0.0.1 --port $Port --data-dir $dataPath
