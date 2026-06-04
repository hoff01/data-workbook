# Kpler Pulls

Balance-ready Kpler liquids flow pulls for U.S., Europe, and domestic U.S. PADD movements.

Windows PowerShell quick start:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
cd Kpler
.\run.ps1 -Setup -Preflight
```

Required credentials:

```powershell
$env:KPLER_EMAIL = "..."
$env:KPLER_PASSWORD = "..."
.\run.ps1 -Run
```

You can also copy and edit the PowerShell environment template:

```powershell
Copy-Item .\config\env.example.ps1 .\config\local.env.ps1
notepad .\config\local.env.ps1
. .\config\local.env.ps1
.\run.ps1 -Run
```

The pipeline pulls daily Kpler `Flows` data from `2018-01-01`, includes forecast/predictive flows, fills missing daily dates with `0.0`, and writes daily, Friday-ending weekly 7-day averages, and monthly average CSVs.

Implementation notes:

- Uses direct HTTPS requests to `https://api.kpler.com/v1/flows`; it does not instantiate the Kpler Python SDK client.
- Uses Polars for CSV parsing, normalization, date completion, and weekly/monthly aggregation.
- Default end date is today plus 45 days. Override with `KPLER_END_DATE=YYYY-MM-DD`.
Check dynamic settings without calling Kpler:

```powershell
.\run.ps1 -Preflight
```

See `Kpler/config/env.example` for all runtime environment variables.

macOS/Linux:

```bash
chmod +x ./run.sh
./run.sh setup-preflight
export KPLER_EMAIL="..."
export KPLER_PASSWORD="..."
./run.sh run
```

See [plan.md](plan.md) for the detailed implementation plan.
