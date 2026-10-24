@echo off
title Cross-Section - Setup Runtime
cd /d "%~dp0"

echo.
echo   Cross-Section: preparing Python runtime
echo   (only needed once; ~70 MB from mirrors)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo [FAILED] Runtime is not ready. See the messages above.
  echo          Re-run SETUP.bat after checking your network.
  pause
  exit /b 1
)

echo.
echo   Done. You can start the app now.
exit /b 0
