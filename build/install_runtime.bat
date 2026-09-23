@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
set "DEPLOY_ROOT=%CD%"
set "DEPLOY_MODE=%~1"
if /I "%DEPLOY_MODE%"=="--offline" goto configured
if /I "%DEPLOY_MODE%"=="--online" goto configured
if /I "%DEPLOY_MODE%"=="--help" goto help
if not "%DEPLOY_MODE%"=="" goto help
echo 1. Offline install from manually downloaded files
echo 2. Online install using CMD and portable Python
echo 3. Open manual download guide
echo 4. Exit
choice /c 1234 /n /m "Select [1-4]: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto guide
if errorlevel 2 goto online
set "DEPLOY_MODE=--offline"
goto configured
:online
set "DEPLOY_MODE=--online"
:configured
if not exist "build.lock.json" (
  echo ERROR: build.lock.json missing. Extract the product body first.
  exit /b 1
)
set "DEPLOY_PYDIR=%DEPLOY_ROOT%\portable_python"
set "DEPLOY_PYZIP=%DEPLOY_ROOT%\vendor\wheels\python-3.11.9-embed-amd64.zip"
set "DEPLOY_EXPECT=009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
if exist "%DEPLOY_PYDIR%\python.exe" goto install
if exist "%DEPLOY_PYZIP%" goto verify
if /I "%DEPLOY_MODE%"=="--offline" (
  echo ERROR: missing vendor\wheels\python-3.11.9-embed-amd64.zip
  echo No download attempted. See docs\MANUAL_DOWNLOADS.html
  exit /b 1
)
where curl.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: curl.exe missing. Use manual download and --offline.
  exit /b 1
)
if not exist "vendor\wheels" mkdir "vendor\wheels"
curl.exe --fail --location --retry 3 -o "%DEPLOY_PYZIP%.download" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
if errorlevel 1 exit /b 1
set "DEPLOY_VERIFY=%DEPLOY_PYZIP%.download"
call :hash
if errorlevel 1 exit /b 1
move /y "%DEPLOY_PYZIP%.download" "%DEPLOY_PYZIP%" >nul
if errorlevel 1 exit /b 1
:verify
set "DEPLOY_VERIFY=%DEPLOY_PYZIP%"
call :hash
if errorlevel 1 exit /b 1
where tar.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: tar.exe missing. Manually extract the verified Python ZIP to portable_python.
  exit /b 1
)
if not exist "%DEPLOY_PYDIR%" mkdir "%DEPLOY_PYDIR%"
tar.exe -xf "%DEPLOY_PYZIP%" -C "%DEPLOY_PYDIR%"
if errorlevel 1 exit /b 1
:install
if /I "%DEPLOY_MODE%"=="--offline" (
  "%DEPLOY_PYDIR%\python.exe" "%DEPLOY_ROOT%\build\install_from_lock.py" --offline
) else (
  "%DEPLOY_PYDIR%\python.exe" "%DEPLOY_ROOT%\build\install_from_lock.py"
)
if errorlevel 1 (
  echo ERROR: installation incomplete. Fix the listed files and retry.
  exit /b 1
)
echo Installation complete. Run the launcher in the product folder.
exit /b 0
:hash
certutil -hashfile "%DEPLOY_VERIFY%" SHA256 2>nul | findstr /i /x /c:"%DEPLOY_EXPECT%" >nul
if errorlevel 1 (
  echo ERROR: Python ZIP SHA-256 mismatch or certutil unavailable.
  echo The file has been preserved. See docs\MANUAL_DOWNLOADS.html
  exit /b 1
)
exit /b 0
:guide
start "" "%DEPLOY_ROOT%\docs\MANUAL_DOWNLOADS.html"
exit /b 0
:help
echo Usage: build\install_runtime.bat [--offline ^| --online ^| --help]
echo No argument opens a menu. Offline never falls back to online.
echo See docs\MANUAL_DOWNLOADS.html for links, paths and SHA-256 values.
exit /b 0
