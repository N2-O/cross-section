@echo off
title Cross-Section
cd /d "%~dp0"

set PY=python\python.exe
set NEED=0

REM ---- check 1: is the python runtime there? ----
if not exist "%PY%" set NEED=1
if %NEED%==1 goto setup

REM ---- check 2: are the parsing-chain packages present? (replay page needs demoparser2) ----
REM Only look for the files, don't import them: pulling up awpy/polars/pandas native
REM DLLs costs 5-10 s on Windows, and server.py now loads them lazily when it really
REM parses a demo. This check used to run twice with a real import - 10-20 s per launch.
"%PY%" -c "import importlib.util as u,sys;m='awpy polars demoparser2 pandas numpy pyarrow tqdm'.split();sys.exit(0 if all(u.find_spec(x) for x in m) else 1)" >nul 2>nul
if errorlevel 1 set NEED=1
if %NEED%==0 goto chainok

:setup
echo.
echo [SETUP] Runtime incomplete - installing the missing pieces now, one time only.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 goto setupfail

REM Only after an install attempt: import for real, to catch a broken DLL that
REM find_spec can't see. The normal path skips this - it is the slow one.
echo [VERIFY] loading the parsing chain once...
"%PY%" -c "import awpy, polars, demoparser2, pandas, numpy, pyarrow, tqdm" >nul 2>nul
if errorlevel 1 goto importfail
goto chainok

:setupfail
echo.
echo [ERROR] Setup failed. See the messages above.
pause
exit /b 1

:importfail
echo.
echo [ERROR] Environment still incomplete. Diagnostic:
"%PY%" -c "import awpy, polars, demoparser2, pandas, numpy, pyarrow, tqdm"
pause
exit /b 1

:chainok
REM server.py opens the browser itself - it knows the real bound port
REM (8790 may already be taken), so starting it here again would open a second tab.
REM No process scan here either: on a busy port server.py kills the owner and retries.
"%PY%" cs2tool\server.py --port 8790
pause
