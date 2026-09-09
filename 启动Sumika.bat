@echo off
title Sumika Launcher
cd /d "%~dp0"

echo [1/2] Cleaning stale processes (DSH 3080 / Core 8771)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\launcher-cleanup.ps1"

echo [2/2] Starting Sumika desktop (Core 8771 + managed DSH)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\run-desktop.ps1" -NoBuild
if errorlevel 1 (
  echo.
  echo Start FAILED - see the error above. This window stays open.
  pause
  exit /b 1
)

echo.
echo Sumika is running. Closing this window does NOT stop the client.
timeout /t 4 >nul
