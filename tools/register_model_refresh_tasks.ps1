[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$CoreUrl,
    [string]$Python = 'python',
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$taskName = 'ModelPricingRefresh'
$taskPath = '\Sumika\'
if ($Unregister) {
    if ($PSCmdlet.ShouldProcess("$taskPath$taskName", 'Unregister model refresh task')) {
        Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false -ErrorAction Stop
    }
    return
}

$uri = $null
if ([string]::IsNullOrWhiteSpace($CoreUrl) -or $CoreUrl -match '[\s\\"?#]' -or
    -not [Uri]::TryCreate($CoreUrl, [UriKind]::Absolute, [ref]$uri)) {
    throw 'CoreUrl must be an explicit loopback origin with a port.'
}
$address = $null
$hostName = $uri.DnsSafeHost.Trim('[', ']')
$loopback = $hostName -eq 'localhost' -or ([Net.IPAddress]::TryParse($hostName, [ref]$address) -and [Net.IPAddress]::IsLoopback($address))
if (-not $loopback -or $uri.Scheme -notin @('http', 'https') -or $uri.UserInfo -or
    $uri.AbsolutePath -ne '/' -or $uri.Port -le 0 -or $CoreUrl -notmatch ':\d+/?$') {
    throw 'CoreUrl must be a credential-free loopback HTTP(S) origin with an explicit port.'
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script = Join-Path $root 'tools\refresh_model_catalog.py'
$pythonPath = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$pythonWindowless = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless -PathType Leaf)) {
    throw 'A resolved Python installation with pythonw.exe is required for hidden scheduling.'
}
foreach ($value in @($script, $pythonWindowless)) {
    if ($value -match '["\r\n]') { throw 'Task executable and script paths cannot contain quotes or newlines.' }
}
$arguments = "-B `"$script`" --all --noninteractive --core-url `"$CoreUrl`""
if ($PSCmdlet.ShouldProcess("$taskPath$taskName", "Register hidden 12-hour refresh using $pythonWindowless $arguments")) {
    $existing = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
    if ($existing) { throw 'Task already exists; explicitly unregister it before replacing it.' }
    $action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $arguments -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 12)
    $settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Delegate zero-AI refresh to an already-running Sumika Core; stop offline.' -ErrorAction Stop | Out-Null
    Write-Output "Registered $taskPath$taskName. No Core is started; offline runs make no upstream requests."
}
