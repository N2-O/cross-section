@echo off
title Cross-Section
cd /d "%~dp0"

set PY=python\python.exe
set NEED=0

REM ---- 自检 1：运行时在不在 ----
if not exist "%PY%" set NEED=1

REM ---- 自检 2：解析链能不能全部 import（回放页要 demoparser2，漏了会崩在页面里）----
if %NEED%==0 (
  "%PY%" -c "import awpy, polars, demoparser2, pandas, numpy, pyarrow, tqdm" >nul 2>nul
  if errorlevel 1 set NEED=1
)

REM ---- 缺就自动补：只下缺的包，已装的跳过 ----
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

REM ---- 再验一次：setup 静默失败也要在这里拦住 ----
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

REM 浏览器由 server.py 自己打开——它知道实际绑定的端口（8790 被占用会自动换一个），
REM 这里再 start 一次就会同时开两个标签页。
"%PY%" cs2tool\server.py --port 8790
pause
