@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "AGENT_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%AGENT_PY%" (
  python -m venv "%~dp0.venv"
  if errorlevel 1 goto fail
)
"%AGENT_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
"%AGENT_PY%" "%~dp0agent_server.py"
pause
exit /b 0
:fail
echo Setup failed. Install Python 3.11 or newer, then retry.
pause
exit /b 1
