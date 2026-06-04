Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "scheduled_email_windows.log"

function Write-Log {
    param([string]$Message)
    "[$(Get-Date -Format o)] $Message" | Out-File -FilePath $LogPath -Append -Encoding utf8
}

function Invoke-Python {
    param([string[]]$Arguments)
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3 @Arguments
        return $LASTEXITCODE
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python @Arguments
        return $LASTEXITCODE
    }
    throw "Python was not found. Install Python 3 and rerun scripts\install_windows_task.ps1."
}

Set-Location $Root
Write-Log "starting DOE summary dashboard email"

$exitCode = Invoke-Python @("build.py", "--refresh-eia-weekly", "--week", "latest", "--validate", "--skip-email")
if ($exitCode -ne 0) {
    throw "build.py failed with exit code $exitCode"
}

$ManifestPath = Join-Path $Root "archive\manifest.csv"
if (-not (Test-Path $ManifestPath)) {
    throw "manifest not found at $ManifestPath"
}

$Latest = Import-Csv $ManifestPath | Sort-Object { [datetime]$_.week_ending } | Select-Object -Last 1
if (-not $Latest) {
    throw "manifest is empty"
}

$Week = $Latest.week_ending
$PdfPath = Join-Path $Root $Latest.output_pdf
if (-not (Test-Path $PdfPath)) {
    throw "PDF not found at $PdfPath"
}

$RecipientsPath = Join-Path $Root "email_recipients.txt"
$Recipients = Get-Content $RecipientsPath |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }
if (-not $Recipients -or $Recipients.Count -eq 0) {
    throw "No recipients found in $RecipientsPath"
}

$Outlook = New-Object -ComObject Outlook.Application
$Mail = $Outlook.CreateItem(0)
$Mail.To = ($Recipients -join ";")
$Mail.Subject = "DOE Summary W/E $Week"
$Mail.Body = "DOE Weekly Summary W/E $Week`r`n`r`nThe dashboard PDF is attached."
[void]$Mail.Attachments.Add($PdfPath)
$Mail.Send()

Write-Log "sent DOE summary dashboard email for $Week to $($Recipients -join ', ')"
