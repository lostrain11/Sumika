# Launcher pre-clean: kill stale Sumika processes from a previous run.
# - stale managed DSH listening on 3080 (blocks fail-closed relaunch)
# - stale Python core listening on 8771
# - lingering desktop shell processes
foreach ($port in @(3080, 8771)) {
    $connection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($connection) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "cleaned stale process on port $port"
    }
}
Get-Process -Name sumika-desktop -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
