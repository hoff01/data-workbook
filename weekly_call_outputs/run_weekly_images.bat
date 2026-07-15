@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "RUNTIME_ROOT=%US_BALANCES_RUNTIME_ROOT%"
if not defined RUNTIME_ROOT set "RUNTIME_ROOT=%USERPROFILE%\US_Balances"
set "PYTHON_ROOT=%RUNTIME_ROOT%\weekly_call_outputs"
set "VENV_DIR=%PYTHON_ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PIP_CACHE_DIR=%RUNTIME_ROOT%\cache\pip"
set "PYTHONPYCACHEPREFIX=%RUNTIME_ROOT%\cache\pycache"
set "MPLCONFIGDIR=%RUNTIME_ROOT%\cache\matplotlib"

if not exist "%PYTHON_ROOT%" mkdir "%PYTHON_ROOT%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if not exist "%PYTHONPYCACHEPREFIX%" mkdir "%PYTHONPYCACHEPREFIX%"
if not exist "%MPLCONFIGDIR%" mkdir "%MPLCONFIGDIR%"

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

echo The managed weekly-output environment is incomplete; rebuilding it...
rmdir /S /Q "%VENV_DIR%"
call :create_venv
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip --version
if errorlevel 1 exit /b 1

:pip_ready
echo Installing or confirming the image packages...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 exit /b 1

echo Creating the weekly JSON, table image, and bar charts...
"%VENV_PYTHON%" "%~dp0generate_weekly_images.py" %*
if errorlevel 1 exit /b 1

echo.
echo Complete. Each EIA week has its own folder in:
echo   %~dp0outputs
exit /b 0

:create_venv
echo Creating the weekly-output environment under %PYTHON_ROOT%...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%VENV_DIR%"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python 3 was not found. Install Python 3 and run this file again.
    exit /b 1
  )
  python -m venv "%VENV_DIR%"
)
if not exist "%VENV_PYTHON%" (
  echo ERROR: The managed weekly-output environment could not be created.
  exit /b 1
)
exit /b 0
