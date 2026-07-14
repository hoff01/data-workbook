param(
    [switch]$Setup,
    [switch]$Preflight,
    [switch]$CheckAuth,
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
    $cmd = @(Resolve-SystemPython)
    $cmdArgs = @()
    if ($cmd.Length -gt 1) {
        $cmdArgs += $cmd[1..($cmd.Length - 1)]
    }
    & $cmd[0] @($cmdArgs + $Arguments)
    Assert-NativeSuccess "Python"
}

function Ensure-PythonPip {
    $probeExitCode = 1
    try {
        & $Python -m pip --version *> $null
        $probeExitCode = $LASTEXITCODE
    }
    catch {
        $probeExitCode = 1
    }
    if ($probeExitCode -eq 0) {
        return
    }
    Remove-Item -Force (Join-Path $PythonRoot ".requirements.sha256") -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $PythonRoot ".refresh-ready") -ErrorAction SilentlyContinue
    Write-Host "[Kpler] pip is missing from the local environment; restoring it with Python -m ensurepip"
    $ensurePipExitCode = 1
    try {
        & $Python -m ensurepip --upgrade
        $ensurePipExitCode = $LASTEXITCODE
    }
    catch {
        $ensurePipExitCode = 1
    }
    $pipAvailable = $false
    if ($ensurePipExitCode -eq 0) {
        try {
            & $Python -m pip --version *> $null
            $pipAvailable = $LASTEXITCODE -eq 0
        }
        catch {
            $pipAvailable = $false
        }
    }
    if (!$pipAvailable) {
        Write-Host "[Kpler] The shared Python environment is incomplete; rebuilding the managed virtual environment"
        Remove-Item -Recurse -Force $Venv
        Remove-Item -Force (Join-Path $PythonRoot ".requirements.sha256") -ErrorAction SilentlyContinue
        Remove-Item -Force (Join-Path $PythonRoot ".refresh-ready") -ErrorAction SilentlyContinue
        Invoke-SystemPython @("-m", "venv", $Venv)
    }
    & $Python -m pip --version
    Assert-NativeSuccess "Python -m pip validation"
}

function Setup-Environment {
    Set-RuntimeEnvironment
    $venvWasCreated = $false
    if (!(Test-Path $PythonRoot)) {
        New-Item -ItemType Directory -Force -Path $PythonRoot | Out-Null
    }
    if ($Force -or !(Test-Path $Python)) {
        Remove-Item -Force (Join-Path $PythonRoot ".requirements.sha256") -ErrorAction SilentlyContinue
        Remove-Item -Force (Join-Path $PythonRoot ".refresh-ready") -ErrorAction SilentlyContinue
    }
    if ($Force -and (Test-Path $Venv)) {
        Remove-Item -Recurse -Force $Venv
    }
    if (!(Test-Path $Python)) {
        Invoke-SystemPython @("-m", "venv", $Venv)
        $venvWasCreated = $true
    }
    if ($venvWasCreated) {
        Remove-Item -Force (Join-Path $PythonRoot ".requirements.sha256") -ErrorAction SilentlyContinue
        Remove-Item -Force (Join-Path $PythonRoot ".refresh-ready") -ErrorAction SilentlyContinue
    }
    Ensure-PythonPip
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

if (!$Setup -and !$Preflight -and !$CheckAuth -and !$Run) {
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

if ($CheckAuth) {
    Set-RuntimeEnvironment
    Test-Environment
    & $Python (Join-Path $RepoRoot "src\kpler_pull.py") --check-auth
    Assert-NativeSuccess "Kpler auth check"
}

if ($Run) {
    Set-RuntimeEnvironment
    Test-Environment
    & $Python (Join-Path $RepoRoot "src\kpler_pull.py")
    Assert-NativeSuccess "Kpler pull"
}
