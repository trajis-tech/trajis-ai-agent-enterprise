# Pack n8n on a build PC that can reach npm. Never run this on locked-down corp PCs
# as the product installer. Output: vendor\n8n-runtime-VERSION-win-x64.zip
@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
if "%N8N_VERSION%"=="" set "N8N_VERSION=2.34.6"
set "OUTDIR=%CD%\vendor\n8n-build"
set "NODE=%CD%\filesystem\system\node\node.exe"
set "NPM=%CD%\filesystem\system\node\npm.cmd"
if not exist "%NPM%" (
  echo Need Node from install_from_lock first, or a system Node on the build PC.
  pause
  exit /b 1
)
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
mkdir "%OUTDIR%"
pushd "%OUTDIR%"
echo {"name":"n8n-runtime","private":true,"dependencies":{"n8n":"%N8N_VERSION%"}} > package.json
if exist package-lock.json (
  call "%NPM%" ci --omit=dev --no-fund --no-audit
) else (
  call "%NPM%" install --omit=dev --no-fund --no-audit
)
if errorlevel 1 (
  echo npm ci/install failed
  popd
  exit /b 1
)
popd
set "ZIP=%CD%\vendor\n8n-runtime-%N8N_VERSION%-win-x64.zip"
if exist "%ZIP%" del "%ZIP%"
tar.exe -a -c -f "%ZIP%" -C "%OUTDIR%" .
echo Packed %ZIP%
certutil -hashfile "%ZIP%" SHA256
echo Put url+sha256 into build.lock.json n8n_runtime and attach this zip as GitHub Release asset 2.
exit /b 0
