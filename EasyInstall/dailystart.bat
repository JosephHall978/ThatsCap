@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ThatsCap

REM Pick up PATH changes (e.g. a freshly installed FFmpeg) without a reboot.
set "_MPATH="
set "_UPATH="
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul ^| findstr /i "REG_"') do set "_MPATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul ^| findstr /i "REG_"') do set "_UPATH=%%b"
if defined _MPATH set "PATH=%PATH%;%_MPATH%"
if defined _UPATH set "PATH=%PATH%;%_UPATH%"

if not exist ".venv\Scripts\python.exe" (
    echo ThatsCap has not been set up on this PC yet.
    echo Please double-click "quickinstall.bat" first.
    echo.
    pause
    exit /b 1
)

if not exist "..\ThatsCap.py" (
    echo Could not find ThatsCap.py in the folder above this one.
    echo Please keep the "EasyInstall" folder inside the main ThatsCap folder.
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