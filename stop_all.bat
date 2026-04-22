@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_all.ps1"
if errorlevel 1 (
  echo.
  echo Stop script failed. See message above.
  pause
)
