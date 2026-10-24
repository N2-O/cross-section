@echo off
title Cross-Section - Database Check
cd /d "%~dp0"

if not exist "python\python.exe" (
  echo [ERROR] Runtime not found. Run START.bat first.
  pause
  exit /b 1
)

"python\python.exe" check_db.py
echo.
pause
