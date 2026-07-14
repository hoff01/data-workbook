@echo off
setlocal EnableExtensions
title Configure US Balances Kpler Key

set "EXAMPLE=%~dp0.env.example"
set "LOCAL_ENV=%~dp0.env.local"

if not exist "%EXAMPLE%" (
  echo [US Balances] .env.example is missing. Pull or extract the complete repository and retry.
  pause
  exit /b 2
)

if not exist "%LOCAL_ENV%" (
  copy /Y "%EXAMPLE%" "%LOCAL_ENV%" >nul
  if errorlevel 1 (
    echo [US Balances] Could not create %LOCAL_ENV%
    pause
    exit /b 1
  )
  echo [US Balances] Created the ignored local credential file: %LOCAL_ENV%
) else (
  echo [US Balances] Opening the existing ignored credential file: %LOCAL_ENV%
)

echo [US Balances] Set KPLER_API_KEY to the value after "Basic ", save, and close Notepad.
echo [US Balances] The real key remains outside Git because .env.local is ignored.
start "" notepad.exe "%LOCAL_ENV%"
exit /b 0
