@echo off
setlocal EnableExtensions
title US Balances Dashboard

set "RUNNER=%~dp0Start_Balance_Runner.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" set "POWERSHELL_EXE=powershell.exe"

if not exist "%RUNNER%" goto :incomplete_checkout
if not exist "%~dp0package.json" goto :incomplete_checkout
if not exist "%~dp0src\open_dashboard.ts" goto :incomplete_checkout

echo [US Balances] Starting the local dashboard...
echo [US Balances] First launch may take a minute while Node packages are prepared.
echo.

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RUNNER%" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [US Balances] The dashboard did not start. Review the error above.
  echo [US Balances] Make sure the ZIP is fully extracted and Node.js LTS is installed.
  if /I not "%CI%"=="true" pause
)
exit /b %EXIT_CODE%

:incomplete_checkout
echo [US Balances] The complete dashboard folder was not found.
echo [US Balances] If this was opened inside a ZIP, choose Extract All first,
echo [US Balances] then double-click Open_Balance_Dashboards.bat in the extracted folder.
if /I not "%CI%"=="true" pause
exit /b 2
