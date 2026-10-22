@echo off
setlocal
for /f "delims=" %%I in ('wsl -d Ubuntu-24.04 -u hadoop -- wslpath -u "%~dp0."') do set "PM25_PROJECT=%%I"
wsl -d Ubuntu-24.04 -u hadoop -- bash "%PM25_PROJECT%/scripts/start.sh"
if errorlevel 1 (
  pause
  exit /b 1
)
if "%~1"=="--no-browser" exit /b 0
start "" "http://localhost:8000"
