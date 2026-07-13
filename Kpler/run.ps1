param(
    [switch]$Setup,
    [switch]$Preflight,
    [switch]$Run,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $Root
$RuntimeRoot = if ($env:US_BALANCES_RUNTIME_ROOT) { $env:US_BALANCES_RUNTIME_ROOT } else { Join-Path $env:USERPROFILE "US_Balances" }
$PythonRoot = Join-Path $RuntimeRoot "python"
$CacheRoot = Join-Path $RuntimeRoot "cache"
$Venv = Join-Path $PythonRoot ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$LocalEnvScript = Join-Path $Root "config\local.env.ps1"

if (Test-Path $LocalEnvScript) {
    . $LocalEnvScript
}

function Assert-NativeSuccess {
    param([string]$Label)
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

function Set-RuntimeEnvironment {
    if (!(Test-Path $CacheRoot)) {
        New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
    }
    foreach ($child in @("pip", "pycache")) {
        $path = Join-Path $CacheRoot $child
        if (!(Test-Path $path)) {
            New-Item -ItemType Directory -Force -Path $path | Out-Null
        }
    }
    $env:US_BALANCES_SHARED_ROOT = $RepoRoot
    $env:US_BALANCES_RUNTIME_ROOT = $RuntimeRoot
    $env:PIP_CACHE_DIR = Join-Path $CacheRoot "pip"
    $env:PYTHONPYCACHEPREFIX = Join-Path $CacheRoot "pycache"
}

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
    $cmdArgs = @()
    if ($cmd.Length -gt 1) {
        $cmdArgs += $cmd[1..($cmd.Length - 1)]
    }
    & $cmd[0] @($cmdArgs + $Arguments)
    Assert-NativeSuccess "Python"
}

function Setup-Environment {
    Set-RuntimeEnvironment
    if (!(Test-Path $PythonRoot)) {
        New-Item -ItemType Directory -Force -Path $PythonRoot | Out-Null
    }
    if ($Force -and (Test-Path $Venv)) {
        Remove-Item -Recurse -Force $Venv
    }
    if (!(Test-Path $Python)) {
        Invoke-SystemPython @("-m", "venv", $Venv)
    }
    & $Python -m pip install --upgrade pip
    Assert-NativeSuccess "pip upgrade"
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
    Assert-NativeSuccess "Kpler dependency setup"
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
    Set-RuntimeEnvironment
    Test-Environment
    & $Python (Join-Path $RepoRoot "src\kpler_pull.py") --preflight
    Assert-NativeSuccess "Kpler preflight"
}

if ($Run) {
    Set-RuntimeEnvironment
    Test-Environment
    & $Python (Join-Path $RepoRoot "src\kpler_pull.py")
    Assert-NativeSuccess "Kpler pull"
}
