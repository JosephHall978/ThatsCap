@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ThatsCap - one-click setup

REM PyTorch CUDA build used when an NVIDIA GPU is found.
REM cu128 supports GTX 10-series through RTX 50-series cards.
set "TORCH_CUDA_INDEX=https://download.pytorch.org/whl/cu128"
set "VPY=.venv\Scripts\python.exe"

echo ==========================================================
echo   ThatsCap - one-click setup
echo   (first run only - next time use "dailystart.bat")
echo ==========================================================
echo.

if not exist "..\ThatsCap.py" (
    echo  Could not find ThatsCap.py in the folder above this one.
    echo  Please keep the "EasyInstall" folder inside the main
    echo  ThatsCap folder, then run this file again.
    echo.
    pause
    exit /b 1
)

call :refresh_path

REM ---- 1/4  Python ------------------------------------------------
call :find_python
if defined PYCMD goto :have_python

echo [1/4] Installing Python ^(this can take a few minutes^)...
where winget >nul 2>&1
if errorlevel 1 goto :no_winget
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
call :refresh_path
call :find_python
if not defined PYCMD goto :python_restart
goto :python_done

:have_python
echo [1/4] Python: already installed
:python_done

REM ---- 2/4  FFmpeg ------------------------------------------------
call :check_ffmpeg
if not errorlevel 1 goto :have_ffmpeg

echo [2/4] Installing FFmpeg ^(video tools^)...
where winget >nul 2>&1
if errorlevel 1 goto :no_winget
winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
call :refresh_path
call :check_ffmpeg
if errorlevel 1 (
    echo.
    echo  FFmpeg was installed but Windows has not picked it up yet.
    echo  Setup will continue. If ThatsCap later says FFmpeg is missing,
    echo  restart your PC and open dailystart.bat.
    echo.
)
goto :ffmpeg_done

:have_ffmpeg
echo [2/4] FFmpeg: already installed
:ffmpeg_done

REM ---- 3/4  ThatsCap packages -------------------------------------
echo [3/4] Installing ThatsCap packages...
echo        This downloads around 1-3 GB ^(the AI caption model tools^).
echo        It can take 5-15 minutes. Please wait.
if exist "%VPY%" goto :venv_ready
%PYCMD% -m venv .venv
if errorlevel 1 goto :failed
:venv_ready
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip >nul 2>&1

REM NVIDIA GPU? Then make sure torch is the CUDA build, not the CPU one.
nvidia-smi >nul 2>&1
if errorlevel 1 goto :torch_done
"%VPY%" -c "import torch,sys;sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1
if not errorlevel 1 goto :torch_done
echo        NVIDIA graphics card found - installing GPU support...
"%VPY%" -m pip install --disable-pip-version-check --force-reinstall torch --index-url %TORCH_CUDA_INDEX%
if errorlevel 1 (
    echo        GPU build could not be installed - using the CPU version instead.
)
:torch_done

"%VPY%" -m pip install --disable-pip-version-check -r ..\requirements.txt flask
if errorlevel 1 goto :failed

REM ---- 4/4  Start the app ----------------------------------------
echo [4/4] All done! Starting ThatsCap...
echo      A web page will open in your browser in a moment.
echo      You can minimise this window, but do not close it
echo      while ThatsCap is running.
echo.
"%VPY%" app.py
echo.
echo ThatsCap closed.
pause
exit /b 0

:no_winget
echo.
echo  Could not find "winget" ^(included with Windows 10/11^).
echo  Please update Windows, or install Python 3.12 from python.org
echo  and FFmpeg from gyan.dev yourself, then run this file again.
echo.
pause
exit /b 1

:python_restart
echo.
echo  Python was installed but Windows cannot find it yet.
echo  Please RESTART YOUR PC, then run this file again.
echo.
pause
exit /b 1

:failed
echo.
echo  Something went wrong during setup. Check the messages above.
echo  Common fixes: make sure you are connected to the internet,
echo  then run this file again.
echo.
pause
exit /b 1

REM ---------------------------------------------------------------
:find_python
set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto :eof
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYCMD="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
goto :eof

:check_ffmpeg
where ffmpeg >nul 2>&1
if errorlevel 1 exit /b 1
where ffprobe >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:refresh_path
REM Append the current machine/user PATH from the registry so tools that were
REM just installed are found. (Appends - never replaces - the existing PATH.)
set "_MPATH="
set "_UPATH="
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul ^| findstr /i "REG_"') do set "_MPATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul ^| findstr /i "REG_"') do set "_UPATH=%%b"
if defined _MPATH set "PATH=%PATH%;%_MPATH%"
if defined _UPATH set "PATH=%PATH%;%_UPATH%"
goto :eof