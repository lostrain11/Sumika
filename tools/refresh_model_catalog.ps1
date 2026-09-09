[CmdletBinding()]
param(
    [switch]$Resources,
    [switch]$Pricing,
    [switch]$Catalog,
    [switch]$All,
    [switch]$Status,
    [string]$CoreUrl,
    [string]$DataDir,
    [string]$ResourceFile,
    [string]$ModelFile,
    [ValidateSet('resources', 'models', 'pricing', 'catalog', 'all', 'status')][string]$Kind,
    [string]$InputJson,
    [string]$ProviderProfileId = '',
    [switch]$Force,
    [switch]$NonInteractive,
    [switch]$DryRun,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script = Join-Path $root 'tools\refresh_model_catalog.py'
$pythonPath = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$arguments = @('-B', $script)
foreach ($entry in @(@('resources', $Resources), @('pricing', $Pricing), @('catalog', $Catalog), @('all', $All), @('status', $Status))) {
    if ($entry[1]) { $arguments += '--' + $entry[0] }
}
if ($InputJson) {
    switch ($Kind) {
        'resources' { $arguments += @('--resource-file', $InputJson) }
        'models' { $arguments += @('--model-file', $InputJson) }
        'pricing' { $arguments += @('--pricing-url', $InputJson) }
        default { throw 'InputJson requires legacy Kind resources, models, or pricing.' }
    }
} elseif ($Kind) {
    if ($Kind -eq 'models') { $arguments += '--catalog' } else { $arguments += '--' + $Kind }
}
if ($CoreUrl) { $arguments += @('--core-url', $CoreUrl) }
if ($DataDir) { $arguments += @('--data-dir', $DataDir) }
if ($ResourceFile) { $arguments += @('--resource-file', $ResourceFile) }
if ($ModelFile) { $arguments += @('--model-file', $ModelFile) }
if ($ProviderProfileId) { $arguments += @('--provider-profile-id', $ProviderProfileId) }
if ($Force) { $arguments += '--force' }
if ($NonInteractive) { $arguments += '--noninteractive' }
if ($DryRun) { $arguments += '--dry-run' }
& $pythonPath @arguments
exit $LASTEXITCODE
