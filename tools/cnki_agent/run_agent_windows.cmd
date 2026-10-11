@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
for %%P in ("%~dp0.venv\Scripts\python.exe" "%~dp0..\..\.venv\Scripts\python.exe") do (
  if exist "%%~P" (
    "%%~P" -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
    if not errorlevel 1 (
      "%%~P" "%~dp0start_agent.py" %*
      goto finished
    )
  )
)
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0start_agent.py" %*
  goto finished
)
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if not errorlevel 1 (
  python "%~dp0start_agent.py" %*
  goto finished
)
for %%P in (
  "%USERPROFILE%\anaconda3\python.exe"
  "%USERPROFILE%\miniconda3\python.exe"
  "%LOCALAPPDATA%\anaconda3\python.exe"
  "%LOCALAPPDATA%\miniconda3\python.exe"
  "%PROGRAMDATA%\anaconda3\python.exe"
  "%PROGRAMDATA%\miniconda3\python.exe"
) do (
  if exist "%%~P" (
    "%%~P" -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
    if not errorlevel 1 (
      "%%~P" "%~dp0start_agent.py" %*
      goto finished
    )
  )
)
echo Python 3.11+ was not found. Install Python or use Anaconda Prompt, then retry.
pause
exit /b 1
:finished
set "AGENT_START_EXIT=%ERRORLEVEL%"
pause
exit /b %AGENT_START_EXIT%
