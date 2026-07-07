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
# Create a repo-root .env or .env.local with KPLER_USERNAME and KPLER_PASSWORD.
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

The pipeline pulls Kpler `Flows` data from `2018-01-01` and includes forecast/predictive flows. Standard context outputs still pull daily data and write daily, Friday-ending weekly averages, and monthly averages. Balance guide pulls use direct Kpler `eia-weekly` and `monthly` granularities so the guide rows line up with EIA week-ending and monthly balance periods.

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

To run only the dashboard balance guide pulls, set:

```bash
export KPLER_PULL_FAMILIES="balance_guides"
./run.sh run
```

This still uses Kpler `eia-weekly` and `monthly` periods, includes predictive flows, and skips the broader daily context pulls.

macOS/Linux:

```bash
chmod +x ./run.sh
./run.sh setup-preflight
export KPLER_EMAIL="..."
# or: export KPLER_USERNAME="..."
export KPLER_PASSWORD="..."
./run.sh run
```

Balance guide pulls use one Kpler `split` per Flow request because the direct API rejects multiple `split` values. PADD routing is handled with exact Kpler zones such as `PADD 1 - A`, `PADD 1 - B`, `PADD 1 - C`, `PADD 3`, and `PADD 5`.

Balance guide pulls include:

- Diesel `Gasoil/Diesel`: PADD 1A/B Canada and non-Canada imports, PADD 1A/B Europe and Other exports, PADD 1C total imports and exports, PADD 3 exports to Africa/Europe/Latin America/Other, PADD 5 total imports and exports, PADD 3 receipts into PADD 1A/B and PADD 1C, and U.S. total imports from Canada/non-Canada plus exports to Europe/Latin America.
- Jet `Kero/Jet`: PADD 1 Canada and non-Canada imports, PADD 1 total exports, PADD 3 exports to Europe/Latin America/Other, PADD 3 receipts into PADD 1 and PADD 5, and PADD 5 total imports and exports.
- PADD subregions are requested directly with Kpler's exact zone spelling. Earlier `PADD 1A` style zones were rejected by Kpler's API bind step.

See [plan.md](plan.md) for the detailed implementation plan.
