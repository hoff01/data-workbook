@echo off
setlocal EnableExtensions
if not exist "%~dp0Start_Balance_Runner.bat" goto :missing_runner
call "%~dp0Start_Balance_Runner.bat" -Route / %*
exit /b %ERRORLEVEL%

:missing_runner
echo [US Balances] Start_Balance_Runner.bat is missing.
echo [US Balances] Extract the complete repository before opening the dashboard.
if /I not "%CI%"=="true" pause
exit /b 2
