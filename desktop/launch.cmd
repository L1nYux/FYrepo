@echo off
setlocal
set "ELECTRON_RUN_AS_NODE="
cd /d "%~dp0"
if not exist "node_modules\electron\dist\electron.exe" (
  echo Please install desktop dependencies first: npm install
  pause
  exit /b 1
)
start "Research Workbench" "node_modules\electron\dist\electron.exe" "%~dp0."
endlocal
