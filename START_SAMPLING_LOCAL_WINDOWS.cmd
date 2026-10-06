@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0tools\start_sampling_local.py"
  goto finished
)

py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0tools\start_sampling_local.py"
  goto finished
)

python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 (
  python "%~dp0tools\start_sampling_local.py"
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
    "%%~P" -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
    if not errorlevel 1 (
      "%%~P" "%~dp0tools\start_sampling_local.py"
      goto finished
    )
  )
)

echo 未找到 Python 3.11 或更新版本。
echo 安装 Python 时勾选 Add python.exe to PATH，或在 Anaconda Prompt 中运行此文件。
pause
exit /b 1

:finished
set "LOCAL_TEST_EXIT=%ERRORLEVEL%"
if not "%LOCAL_TEST_EXIT%"=="0" echo 启动未完成。请保留这个窗口，将具体报错截图发来。
pause
exit /b %LOCAL_TEST_EXIT%
