@echo off
title Cross-Section
cd /d "%~dp0"

REM ---- portable build: bundled Python, no system Python / no pip / no network needed ----
if not exist "python\python.exe" (
  echo [ERROR] Bundled Python missing: python\python.exe not found.
  echo Re-extract the whole zip, do not copy partial folders.
  pause
  exit /b 1
)

set PY=python\python.exe

REM ---- sanity check: the bundled runtime can import the parsing engine ----
"%PY%" -c "import awpy" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Bundled Python cannot import awpy.
  echo The package may be incomplete. Re-extract the zip to a clean folder.
  echo Diagnostic:
  "%PY%" -c "import sys; print('python', sys.version); print('exe', sys.executable)"
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
