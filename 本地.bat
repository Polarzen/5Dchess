@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
if not exist "%~dp0scripts\launch_windows.ps1" (
    echo Please extract the ENTIRE ZIP first. Do not run inside the ZIP.
    pause
    exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_windows.ps1" -Mode Local
set "launcherExit=%errorlevel%"
echo.
echo Press any key to close this window.
pause >nul
exit /b %launcherExit%
