@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%CD%"
set "PY=%ROOT%\portable_python\python.exe"
if not exist "%PY%" set "PY=python"
set ALLOW_MODEL_REQUESTS=False
"%PY%" -m unittest discover -s "%ROOT%\tests" -v
exit /b %ERRORLEVEL%
