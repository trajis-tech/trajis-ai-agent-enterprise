@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
if not exist "portable_python\python.exe" (
  echo ERROR: Product Python is missing. Run build\install_runtime.bat first.
  exit /b 1
)
"portable_python\python.exe" "build\pack_product.py"
if errorlevel 1 exit /b 1
certutil -hashfile "vendor\portable-agent-body.zip" SHA256
exit /b %ERRORLEVEL%
