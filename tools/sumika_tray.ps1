# Tray companion: keeps the local bridge alive and offers open / quit.
# Started hidden at login when the user enables auto-start in settings.
param(
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $env:LOCALAPPDATA 'Sumika\env.ps1'
if (Test-Path -LiteralPath $envFile) { . $envFile }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$bridge = Join-Path $PSScriptRoot 'start_sumika.ps1'
& powershell -NoProfile -ExecutionPolicy Bypass -File $bridge -Port $Port -NoBrowser
# Pin the session of the bridge we attached to. Never acquire replacement
# authority from a different process which later occupies this port.
$bridgeSession = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/manage/session"
$bridgeToken = $bridgeSession.csrf

$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = [System.Drawing.SystemIcons]::Application
$icon.Text = 'Sumika'
$icon.Visible = $true

$open = New-Object System.Windows.Forms.MenuItem('打开 Sumika')
$open.add_Click({ Start-Process "http://127.0.0.1:$Port/" })
$quit = New-Object System.Windows.Forms.MenuItem('退出（停止桥接）')
$quit.add_Click({
    try {
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/lifecycle/shutdown" `
            -ContentType 'application/json' -Body '{}' -Headers @{ 'X-Sumika-CSRF' = $bridgeToken } | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show('无法确认安全退出。服务和托盘保持运行，请检查连接后重试。', 'Sumika') | Out-Null
        return
    }
    $icon.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})
$menu = New-Object System.Windows.Forms.ContextMenu
$menu.MenuItems.Add($open) | Out-Null
$menu.MenuItems.Add($quit) | Out-Null
$icon.ContextMenu = $menu
$icon.add_DoubleClick({ Start-Process "http://127.0.0.1:$Port/" })

[System.Windows.Forms.Application]::Run()
$icon.Visible = $false
