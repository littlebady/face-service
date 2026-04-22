@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%start_all.ps1") do set "START_PS1=%%~fI"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -WindowStyle Minimized -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%START_PS1%') | Out-Null"
echo Start command submitted.
echo Check status file: "%SCRIPT_DIR%.run\services.json"
exit /b 0
