param(
    [string]$Route = "/",
    [switch]$NoOpen,
    [switch]$ForceSetup,
    [switch]$SkipPythonSetup,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$SharedRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalRoot = Join-Path $env:USERPROFILE "US_Balances"
$NodeRoot = Join-Path $LocalRoot "node"
$PythonRoot = Join-Path $LocalRoot "python"
$CacheRoot = Join-Path $LocalRoot "cache"
$NodeStamp = Join-Path $NodeRoot ".package-lock.sha256"
$PythonStamp = Join-Path $PythonRoot ".requirements.sha256"
$LocalPython = Join-Path $PythonRoot ".venv\Scripts\python.exe"
$RefreshReadyFile = Join-Path $PythonRoot ".refresh-ready"

foreach ($RequiredPath in @(
    (Join-Path $SharedRoot "package.json"),
    (Join-Path $SharedRoot "src\open_dashboard.ts"),
    (Join-Path $SharedRoot "src\dashboard_update_server.ts")
)) {
    if (!(Test-Path $RequiredPath)) {
        throw "The complete US Balances checkout was not found at $SharedRoot. If you downloaded a ZIP, extract the entire ZIP before running the .bat launcher."
    }
}

function New-Directory {
    param([string]$Path)
    if (!(Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Get-FileSha256 {
    param([string]$Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        return [System.BitConverter]::ToString($sha.ComputeHash($stream)).Replace("-", "")
    }
    finally {
        if ($stream) {
            $stream.Dispose()
        }
        $sha.Dispose()
    }
}

function Get-CombinedHash {
    param([string[]]$Paths)
    $text = ""
    foreach ($Path in $Paths) {
        if (Test-Path $Path) {
            $hash = Get-FileSha256 $Path
            $name = [System.IO.Path]::GetFileName($Path)
            $text += "$name=$hash`n"
        }
    }
    if (!$text) {
        return ""
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

function Read-Stamp {
    param([string]$Path)
    if (Test-Path $Path) {
        return (Get-Content -Raw $Path).Trim()
    }
    return ""
}

function Resolve-SystemPython {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @("py", "-3")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @("python")
    }
    throw "Python 3 was not found. Install Python 3.11+ and rerun this launcher."
}

function Invoke-SystemPython {
    param([string[]]$Arguments)
    $cmd = @(Resolve-SystemPython)
    $cmdArgs = @()
    if ($cmd.Length -gt 1) {
        $cmdArgs += $cmd[1..($cmd.Length - 1)]
    }
    & $cmd[0] @($cmdArgs + $Arguments) | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

function Test-PythonPip {
    param([string]$PythonPath)
    $probeExitCode = 1
    try {
        & $PythonPath -m pip --version *> $null
        $probeExitCode = $LASTEXITCODE
    }
    catch {
        $probeExitCode = 1
    }
    return $probeExitCode -eq 0
}

function Ensure-PythonPip {
    param(
        [string]$PythonPath,
        [string]$VenvPath,
        [string]$StampPath
    )
    if (Test-PythonPip -PythonPath $PythonPath) {
        return $false
    }

    Write-Host "[US Balances] Python setup: pip is missing from the local environment; restoring it with Python -m ensurepip"
    Remove-Item -Force $StampPath -ErrorAction SilentlyContinue
    $ensurePipExitCode = 1
    try {
        & $PythonPath -m ensurepip --upgrade | Out-Host
        $ensurePipExitCode = $LASTEXITCODE
    }
    catch {
        $ensurePipExitCode = 1
    }
    if ($ensurePipExitCode -ne 0 -or !(Test-PythonPip -PythonPath $PythonPath)) {
        Write-Host "[US Balances] Python setup: the local environment is incomplete; rebuilding the managed virtual environment"
        Remove-Item -Recurse -Force $VenvPath
        Invoke-SystemPython @("-m", "venv", $VenvPath)
    }
    if (!(Test-PythonPip -PythonPath $PythonPath)) {
        throw "Python -m pip is unavailable after automatic repair. Install or repair Python 3.11+ and retry."
    }
    & $PythonPath -m pip --version | Out-Host
    Write-Host "[US Balances] Python setup: pip restored successfully"
    return $true
}

function Ensure-NodeRuntime {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (!$node -or !$npm) {
        throw "Node.js LTS and npm were not found. Install Node.js LTS, reopen PowerShell, and rerun this launcher."
    }

    New-Directory $NodeRoot
    Copy-Item (Join-Path $SharedRoot "package.json") (Join-Path $NodeRoot "package.json") -Force
    $sharedLock = Join-Path $SharedRoot "package-lock.json"
    if (Test-Path $sharedLock) {
        Copy-Item $sharedLock (Join-Path $NodeRoot "package-lock.json") -Force
    }

    $tsx = Join-Path $NodeRoot "node_modules\.bin\tsx.cmd"
    $tsxCli = Join-Path $NodeRoot "node_modules\tsx\dist\cli.mjs"
    $hash = Get-CombinedHash @((Join-Path $SharedRoot "package.json"), $sharedLock)
    if ($ForceSetup -or !(Test-Path $tsx) -or (Read-Stamp $NodeStamp) -ne $hash) {
        Write-Host "[US Balances] Node setup: installing reviewed local dependencies"
        Push-Location $NodeRoot
        try {
            if (Test-Path (Join-Path $NodeRoot "package-lock.json")) {
                & $npm.Source ci | Out-Host
            }
            else {
                & $npm.Source install | Out-Host
            }
            if ($LASTEXITCODE -ne 0) {
                throw "npm dependency setup failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
        Set-Content -Path $NodeStamp -Value $hash -Encoding UTF8
        Write-Host "[US Balances] Node setup: dependencies installed"
    }
    if (!(Test-Path $tsx) -or !(Test-Path $tsxCli)) {
        throw "Local tsx runtime was not created under $NodeRoot\node_modules"
    }
    return $tsx
}

function Ensure-PythonRuntime {
    Write-Host "[US Balances] Python setup: resolving Python 3"
    New-Directory $PythonRoot
    $venv = Join-Path $PythonRoot ".venv"
    $python = Join-Path $venv "Scripts\python.exe"
    $requirements = Join-Path $SharedRoot "requirements.txt"
    $hash = Get-CombinedHash @($requirements)
    $venvWasCreated = $false

    if ($ForceSetup -or !(Test-Path $python)) {
        Remove-Item -Force $PythonStamp -ErrorAction SilentlyContinue
    }
    if ($ForceSetup -and (Test-Path $venv)) {
        Write-Host "[US Balances] Python setup: removing the previous local environment"
        Remove-Item -Recurse -Force $venv
    }
    if (!(Test-Path $python)) {
        Write-Host "[US Balances] Python setup: creating the local virtual environment (this can take about a minute)"
        Invoke-SystemPython @("-m", "venv", $venv)
        $venvWasCreated = $true
        Write-Host "[US Balances] Python setup: local virtual environment created"
    }
    $pipWasRepaired = Ensure-PythonPip -PythonPath $python -VenvPath $venv -StampPath $PythonStamp
    if ($ForceSetup -or $venvWasCreated -or $pipWasRepaired -or (Read-Stamp $PythonStamp) -ne $hash) {
        Remove-Item -Force $PythonStamp -ErrorAction SilentlyContinue
        $pipOptions = @("--disable-pip-version-check", "--no-input", "--timeout", "60", "--retries", "2")
        Write-Host "[US Balances] Python setup: upgrading pip"
        & $python -m pip @pipOptions install --upgrade pip | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "pip upgrade failed with exit code $LASTEXITCODE."
        }
        Write-Host "[US Balances] Python setup: installing refresh dependencies (large wheels can take several minutes)"
        & $python -m pip @pipOptions install -r $requirements | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Python dependency setup failed with exit code $LASTEXITCODE."
        }
        Write-Host "[US Balances] Python setup: validating installed dependencies"
        & $python -m pip check | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Python dependency validation failed with exit code $LASTEXITCODE."
        }
        & $python -c "import matplotlib, polars, pyarrow, requests, yaml"
        if ($LASTEXITCODE -ne 0) {
            throw "Python refresh dependency import validation failed with exit code $LASTEXITCODE."
        }
        Set-Content -Path $PythonStamp -Value $hash -Encoding UTF8
        Write-Host "[US Balances] Python setup: refresh dependencies installed and validated"
    }
    else {
        Write-Host "[US Balances] Python setup: existing refresh dependencies are current"
    }
    return $python
}

function Open-DashboardUrl {
    param([string]$Url)

    $probePath = $env:US_BALANCES_BROWSER_OPEN_PROBE
    if ($probePath) {
        $probeDirectory = Split-Path -Parent $probePath
        if ($probeDirectory) {
            New-Directory $probeDirectory
        }
        Set-Content -Path $probePath -Value $Url -Encoding UTF8
        Write-Host "[US Balances] Browser-open probe recorded $Url"
        return
    }

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Url
    $startInfo.UseShellExecute = $true
    try {
        [System.Diagnostics.Process]::Start($startInfo) | Out-Null
    }
    catch {
        throw "The dashboard server is ready at $Url, but Windows could not open the default browser. Copy that URL into Chrome or Edge. $($_.Exception.Message)"
    }
}

New-Directory $LocalRoot
New-Directory $CacheRoot
New-Directory (Join-Path $CacheRoot "npm")
New-Directory (Join-Path $CacheRoot "pip")
New-Directory (Join-Path $CacheRoot "pycache")
New-Directory (Join-Path $CacheRoot "matplotlib")

$env:npm_config_cache = Join-Path $CacheRoot "npm"
$env:PIP_CACHE_DIR = Join-Path $CacheRoot "pip"
$env:PYTHONPYCACHEPREFIX = Join-Path $CacheRoot "pycache"
$env:MPLCONFIGDIR = Join-Path $CacheRoot "matplotlib"
$env:US_BALANCES_SHARED_ROOT = $SharedRoot
$env:US_BALANCES_RUNTIME_ROOT = $LocalRoot
$env:US_BALANCES_REFRESH_READY_FILE = $RefreshReadyFile
if (!$SkipPythonSetup) {
    Remove-Item -Force $RefreshReadyFile -ErrorAction SilentlyContinue
}
Write-Host "[US Balances] Preparing the local Node runtime under $NodeRoot"
$env:US_BALANCES_TSX_COMMAND = Ensure-NodeRuntime
try { $Host.UI.RawUI.WindowTitle = "US Balances Dashboard" } catch {}
$env:US_BALANCES_NODE_COMMAND = (Get-Command node.exe -ErrorAction Stop).Source
$env:US_BALANCES_TSX_CLI = Join-Path $NodeRoot "node_modules\tsx\dist\cli.mjs"
if (!$SkipPythonSetup -or (Test-Path $LocalPython)) {
    $env:US_BALANCES_PYTHON = $LocalPython
}
$KplerLocalEnvScript = Join-Path $SharedRoot "Kpler\config\local.env.ps1"
if (Test-Path $KplerLocalEnvScript) {
    . $KplerLocalEnvScript
}
if ($Port -gt 0) {
    $env:DASHBOARD_UPDATE_PORT = [string]$Port
}

Set-Location $SharedRoot
$openArgs = @((Join-Path $SharedRoot "src\open_dashboard.ts"), $Route)
$openArgs += "--no-open"
Write-Host "[US Balances] Starting the local dashboard server"
$openOutput = @(& $env:US_BALANCES_NODE_COMMAND $env:US_BALANCES_TSX_CLI @openArgs 2>&1)
$openExitCode = $LASTEXITCODE
$openOutput | ForEach-Object { Write-Host $_ }
if ($openExitCode -ne 0) {
    exit $openExitCode
}

$dashboardUrl = ""
foreach ($line in $openOutput) {
    if ([string]$line -match "https?://[^\s]+") {
        $dashboardUrl = $Matches[0]
    }
}
if (!$dashboardUrl) {
    throw "The dashboard server started, but its local URL was not reported."
}
if (!$NoOpen) {
    Open-DashboardUrl $dashboardUrl
    Write-Host "[US Balances] Opened $dashboardUrl"
}
else {
    Write-Host "[US Balances] Dashboard ready at $dashboardUrl"
}

if (!$SkipPythonSetup) {
    Write-Host "[US Balances] The dashboard is available. Preparing Python refresh tools under $PythonRoot"
    try {
        $env:US_BALANCES_PYTHON = Ensure-PythonRuntime
        Set-Content -Path $RefreshReadyFile -Value (Get-Date).ToUniversalTime().ToString("o") -Encoding UTF8
        Write-Host "[US Balances] Dashboard and refresh tools are ready"
    }
    catch {
        Remove-Item -Force $RefreshReadyFile -ErrorAction SilentlyContinue
        Write-Host "[US Balances] Python refresh-tool setup failed. Review the stage output above, check network access, and retry. If the local environment is damaged, rerun with -ForceSetup."
        throw
    }
}
elseif (Test-Path $LocalPython) {
    $env:US_BALANCES_PYTHON = $LocalPython
    Set-Content -Path $RefreshReadyFile -Value (Get-Date).ToUniversalTime().ToString("o") -Encoding UTF8
}
else {
    throw "Python refresh tools are not installed. Rerun without -SkipPythonSetup so first-run setup can complete."
}

Write-Host "[US Balances] Dashboard and refresh tools are ready. No data refresh has started; use a dashboard refresh button."
