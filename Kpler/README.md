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
$env:KPLER_USERNAME = "..."
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

`KPLER_EMAIL` is also accepted if that is the login name on your Kpler account. Do not paste credentials into Python source files; `Kpler/config/local.env.ps1`, `Kpler/config/local.env`, and `Kpler/config/.env` are ignored by git for local secret storage.

The pipeline pulls daily Kpler `Flows` data from `2018-01-01`, includes forecast/predictive flows, fills missing daily dates with `0.0`, and writes daily, Friday-ending weekly 7-day averages, and monthly average CSVs.

Implementation notes:

- Uses direct HTTPS requests to `https://api.kpler.com/v1/flows`; it does not instantiate the Kpler Python SDK client.
- Sends a stable `User-Agent` from `KPLER_USER_AGENT` and keeps credentials in the HTTP Basic Auth header, not in URLs or manifests.
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
# or: export KPLER_USERNAME="..."
export KPLER_PASSWORD="..."
./run.sh run
```

Diesel-specific guide pulls include:

- PADD 1A/B `Gasoil/Diesel` imports split by origin country, with Canada and non-Canada guide totals.
- PADD 1C `Gasoil/Diesel` imports split by origin country and origin PADD with `withIntraCountry=true`.
- Weekly and monthly outputs derived from daily Kpler pulls in `output/weekly/us_diesel_padd1_import_guides_weekly.csv` and `output/monthly/us_diesel_padd1_import_guides_monthly.csv`.

See [plan.md](plan.md) for the detailed implementation plan.
