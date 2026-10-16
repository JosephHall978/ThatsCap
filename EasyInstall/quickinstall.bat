@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ThatsCap - one-click setup

echo ==========================================================
echo   ThatsCap - one-click setup
echo   (first run only - next time use "Start ThatsCap.bat")
echo ==========================================================
echo.

call :refresh_path

REM ---- 1/4  Python ------------------------------------------------
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo [1/4] Installing Python ^(this can take a few minutes^)...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  Could not find "winget" ^(included with Windows 10/11^).
        echo  Please update Windows, or install Python from python.org
        echo  yourself, then run this file again.
        echo.
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :failed
    call :refresh_path
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  Python was installed but not found yet.
        echo  Please RESTART YOUR PC, then run this file again.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Python: already installed
)

REM ---- 2/4  FFmpeg ------------------------------------------------
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [2/4] Installing FFmpeg ^(video tools^)...
    winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :failed
    call :refresh_path
) else (
    echo [2/4] FFmpeg: already installed
)

REM ---- 3/4  ThatsCap packages -------------------------------------
echo [3/4] Installing ThatsCap packages...
echo        This downloads around 1-2 GB ^(the AI caption model tools^).
echo        It can take 5-15 minutes. Please wait.
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r ../requirements.txt flask
if errorlevel 1 goto :failed

REM ---- 4/4  Start the app ----------------------------------------
echo [4/4] All done! Starting ThatsCap...
echo      A web page will open in your browser in a moment.
echo      You can minimise this window, but do not close it
echo      while ThatsCap is running.
".venv\Scripts\python.exe" app.py
pause
exit /b 0

:failed
echo.
echo  Something went wrong during setup. Check the messages above.
echo  Common fixes: make sure you are connected to the internet,
echo  then run this file again.
echo.
pause
exit /b 1

:refresh_path
for /f "skip=2 tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "_MPATH=%%b"
for /f "skip=2 tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "_UPATH=%%b"
if defined _MPATH if defined _UPATH set "PATH=%_MPATH%;%_UPATH%"
if defined _MPATH if not defined _UPATH set "PATH=%_MPATH%"
if not defined _MPATH if defined _UPATH set "PATH=%_UPATH%"
goto :eof
Start-Sleep -Seconds 5
