@echo off
rem One-click launcher: starts the local bridge (if needed) and opens the UI.
rem Keep the window open only when something failed, so double-clicking is quiet.
setlocal
set "SCRIPT=%~dp0tools\start_sumika.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
if errorlevel 1 (
  echo.
  echo Launch failed. Copy the messages above when reporting the problem.
  pause
)
endlocal
