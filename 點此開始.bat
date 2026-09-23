@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%CD%"
set "PY=%ROOT%\portable_python\python.exe"
if not exist "%PY%" (
  echo ERROR: portable_python\python.exe not found.
  echo Please run build\install_runtime.bat first.
  echo Do not use PowerShell install scripts.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8765/"
"%PY%" -m uvicorn backend.server:app --app-dir "%ROOT%\app" --host 127.0.0.1 --port 8765
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo ERROR: server exited with code %ERR%.
  echo If packages are missing, re-run build\install_runtime.bat
)
pause
exit /b %ERR%
