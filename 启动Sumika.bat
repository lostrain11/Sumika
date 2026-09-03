@echo off
title Sumika Launcher
cd /d "%~dp0"

echo [1/3] Cleaning stale processes (DSH 3080 / Core 8771)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\launcher-cleanup.ps1"

echo [2/3] Starting Sumika desktop (Core 8771 + managed DSH)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\run-desktop.ps1" -NoBuild
if errorlevel 1 (
  echo.
  echo Start FAILED - see the error above. This window stays open.
  pause
  exit /b 1
)

echo [3/3] Opening managed Edge Agent Window (needed for web-route chat)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\setup-browserskill.ps1" -LaunchAgentBrowser >nul 2>&1

echo.
echo Sumika is running. Closing this window does NOT stop the client.
timeout /t 4 >nul
