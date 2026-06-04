param(
    [switch]$Setup,
    [switch]$Preflight,
    [switch]$Run,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Resolve-SystemPython {
    $pythonCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @("py", "-3")
    }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @("python")
    }
    throw "Python 3 was not found. Install Python 3.11+ and rerun this script."
}

function Invoke-SystemPython {
    param([string[]]$Arguments)
    $cmd = Resolve-SystemPython
    & $cmd[0] @($cmd[1..($cmd.Length - 1)] + $Arguments)
}

function Setup-Environment {
    if ($Force -and (Test-Path $Venv)) {
        Remove-Item -Recurse -Force $Venv
    }
    if (!(Test-Path $Python)) {
        Invoke-SystemPython @("-m", "venv", $Venv)
    }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
}

function Test-Environment {
    if (!(Test-Path $Python)) {
        throw "Virtual environment is missing. Run: .\run.ps1 -Setup"
    }
}

if (!$Setup -and !$Preflight -and !$Run) {
    $Setup = $true
    $Preflight = $true
}

if ($Setup) {
    Setup-Environment
}

if ($Preflight) {
    Test-Environment
    & $Python (Join-Path $Root "src\kpler_pull.py") --preflight
}

if ($Run) {
    Test-Environment
    & $Python (Join-Path $Root "src\kpler_pull.py")
}
