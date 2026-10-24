@echo off
title Cross-Section
cd /d "%~dp0"

set PY=python\python.exe
set NEED=0

REM ---- check 1: is the python runtime there? ----
if not exist "%PY%" set NEED=1

REM ---- check 2: can the whole parsing chain import? (replay page needs demoparser2) ----
if %NEED%==0 (
  "%PY%" -c "import awpy, polars, demoparser2, pandas, numpy, pyarrow, tqdm" >nul 2>nul
  if errorlevel 1 set NEED=1
)

REM ---- missing anything -> fetch only what is absent (installed ones are skipped) ----
if %NEED%==1 (
  echo.
  echo [SETUP] Runtime incomplete - installing the missing pieces now, one time only.
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 (
    echo.
    echo [ERROR] Setup failed. See the messages above.
    pause
    exit /b 1
  )
)

REM ---- verify again: catch a silent setup failure here ----
"%PY%" -c "import awpy, polars, demoparser2, pandas, numpy, pyarrow, tqdm" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Environment still incomplete. Diagnostic:
  "%PY%" -c "import awpy, polars, demoparser2, pandas, numpy, pyarrow, tqdm"
  pause
  exit /b 1
)

REM ---- stop old instance still holding the port ----
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*cs2tool*server.py*' } | ForEach-Object { Write-Host ('  kill old PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

REM server.py opens the browser itself - it knows the real bound port
REM (8790 may already be taken), so starting it here again would open a second tab.
"%PY%" cs2tool\server.py --port 8790
pause
