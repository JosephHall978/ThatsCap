@echo off
setlocal
cd /d "%~dp0"
title ThatsCap

if not exist ".venv\Scripts\python.exe" (
    echo ThatsCap has not been set up on this PC yet.
    echo Please double-click "setup_windows.bat" first.
    echo.
    pause
    exit /b 1
)

echo Starting ThatsCap... a web page will open in your browser.
echo You can minimise this window, but do not close it
echo while ThatsCap is running.
echo.
".venv\Scripts\python.exe" app.py
echo.
echo ThatsCap closed.
pause