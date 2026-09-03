$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = $ws.CreateShortcut("$desktop\Sumika.lnk")
$shortcut.TargetPath = 'D:\Code\Sumika\启动Sumika.bat'
$shortcut.WorkingDirectory = 'D:\Code\Sumika'
$shortcut.Description = '一键清理残留并启动 Sumika 桌面版'
$shortcut.WindowStyle = 1
$shortcut.Save()
Write-Host "shortcut created: $desktop\Sumika.lnk"
