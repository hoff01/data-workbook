Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "EIA Summary Dashboard"
$Runner = Join-Path $Root "scripts\run_scheduled_email.ps1"

if (-not (Test-Path $Runner)) {
    throw "Runner not found at $Runner"
}

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py -3 -m pip install -r (Join-Path $Root "requirements.txt")
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python was not found. Install Python 3, then rerun this installer."
    }
    & python -m pip install -r (Join-Path $Root "requirements.txt")
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
    -WorkingDirectory $Root

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At 9:30am
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel LeastPrivilege
$Settings = New-ScheduledTaskSettingsSet -Compatibility Win8 -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Builds and emails the EIA summary dashboard PDF every Wednesday at 9:30 AM." `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' for Wednesdays at 9:30 AM."
Write-Host "Recipients are read from: $Root\email_recipients.txt"
Write-Host "Run once now with: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
