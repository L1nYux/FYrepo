@echo off
call "%~dp0tools\cnki_agent\run_agent_windows.cmd" %*
exit /b %ERRORLEVEL%
