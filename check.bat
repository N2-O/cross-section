@echo off
title Cross-Section - Database Check
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run START.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" check_db.py
echo.
pause
