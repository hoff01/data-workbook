@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_Balance_Runner.ps1" -Route /
if errorlevel 1 pause
