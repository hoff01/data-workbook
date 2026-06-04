@echo off
setlocal
cd /d "%~dp0"
npm run dashboard:open -- jet
if errorlevel 1 pause
