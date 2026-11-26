@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
if not defined PSYCHTOOL_PORT set PSYCHTOOL_PORT=8000
set "URL=http://127.0.0.1:%PSYCHTOOL_PORT%/"
set "HEALTH=%URL%api/health"

curl -sf --max-time 1 "%HEALTH%" >nul 2>&1
if %ERRORLEVEL%==0 goto :open_browser

where uv >nul 2>&1
if %ERRORLEVEL%==0 (
  start "psychtool" cmd /k uv run psychtool-server
  goto :wait_ready
)
if exist ".venv\Scripts\psychtool-server.exe" (
  start "psychtool" cmd /k ".venv\Scripts\psychtool-server.exe"
  goto :wait_ready
)
if exist ".venv\Scripts\python.exe" (
  start "psychtool" cmd /k ".venv\Scripts\python.exe -m psychtool.server"
  goto :wait_ready
)

echo This copy of psychtool isn't ready to start. Ask the person who installed it to check the installation, then try again.
pause
exit /b 1

:wait_ready
set /a tries=0
:wait_loop
curl -sf --max-time 1 "%HEALTH%" >nul 2>&1
if %ERRORLEVEL%==0 goto :open_browser
set /a tries+=1
if %tries% GEQ 60 (
  echo The writing workspace did not become ready in time. Ask the person who installed it to check the installation, then try again.
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto :wait_loop

:open_browser
start "" "%URL%"
exit /b 0
