@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  call :create_venv
  if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -m pip --version >nul 2>nul
if not errorlevel 1 goto :pip_ready

echo Python pip is missing; restoring it with Python -m ensurepip...
"%VENV_PYTHON%" -m ensurepip --upgrade
if not errorlevel 1 (
  "%VENV_PYTHON%" -m pip --version
  if not errorlevel 1 goto :pip_ready
)

echo The private Python environment is incomplete; rebuilding it...
rmdir /S /Q "%~dp0.venv"
call :create_venv
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip --version
if errorlevel 1 exit /b 1

:pip_ready
echo Installing or confirming the image packages...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 exit /b 1

echo Creating the weekly JSON and table image...
"%VENV_PYTHON%" "%~dp0generate_weekly_images.py" %*
if errorlevel 1 exit /b 1

echo.
echo Complete. Each EIA week has its own folder in:
echo   %~dp0outputs
exit /b 0

:create_venv
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%~dp0.venv"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python 3 was not found. Install Python 3 and run this file again.
    exit /b 1
  )
  python -m venv "%~dp0.venv"
)
if not exist "%VENV_PYTHON%" (
  echo ERROR: The private Python environment could not be created.
  exit /b 1
)
exit /b 0
