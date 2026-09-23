@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo Trajis AI Agent 0.0.1
echo Installing locked Python, Node, wheels, n8n and OpenRPA, then starting the app.
echo Keep this window open. Network is required for the public runtimes.
echo.
call "%~dp0build\install_runtime.bat" --online
if errorlevel 1 (
  echo.
  echo Installation stopped. Read the messages above, then run this file again.
  pause
  exit /b 1
)
call "%~dp0點此開始.bat"
exit /b %ERRORLEVEL%
