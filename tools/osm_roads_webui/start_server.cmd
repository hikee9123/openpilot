@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

set "HOST=127.0.0.1"
set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"

cd /d "%REPO_ROOT%" || (
  echo Failed to enter repo root: %REPO_ROOT%
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo python was not found in PATH.
  echo Run this from a shell where python is available.
  pause
  exit /b 1
)

set "URL=http://%HOST%:%PORT%/"
echo Starting OSM roads web UI at %URL%
echo Repo: %REPO_ROOT%
echo Press Ctrl+C to stop the server.
echo.

if not defined OSM_ROADS_WEBUI_NO_BROWSER (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1; Start-Process '%URL%'" >nul 2>nul
)

python tools\scripts\osm_roads_webui.py --host %HOST% --port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Server exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
