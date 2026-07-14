# Kpler Pulls

Balance-ready Kpler liquids flow pulls for the U.S. diesel and jet balance dashboards.

Windows PowerShell quick start:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
cd Kpler
.\run.ps1 -Setup -Preflight
```

Required Kpler API v2 key:

```powershell
# Create a repo-root .env/.env.local or Kpler/config/local.env with KPLER_API_KEY.
.\run.ps1 -Run
```

From the repo root, the simplest Windows setup is to double-click
`Configure_Kpler_Auth.bat`, paste the key into `.env.local`, and save. Confirm
that the file is detected with `.\Kpler\run.ps1 -Preflight`, then validate the
credential with one small Flows request using `.\Kpler\run.ps1 -CheckAuth`.

You can also copy and edit the PowerShell environment template:

```powershell
Copy-Item .\config\env.example.ps1 .\config\local.env.ps1
notepad .\config\local.env.ps1
. .\config\local.env.ps1
.\run.ps1 -Run
```

Set `KPLER_API_KEY` to the value after `Basic `, or set `KPLER_API_V2_BASIC_AUTH` to the complete `Basic ...` header value. Do not paste credentials into Python source files; `Kpler/config/local.env.ps1`, `Kpler/config/local.env`, and `Kpler/config/.env` are ignored by git for local secret storage.

The pipeline pulls Kpler `Flows` data from `2018-01-01` and includes forecast/predictive flows. Standard context outputs still pull daily data and write daily, Friday-ending weekly averages, and monthly averages. Balance guide pulls use direct Kpler `eia-weekly` and `monthly` granularities so the guide rows line up with EIA week-ending and monthly balance periods.

Implementation notes:

- The implementation lives in the repo-root `src/kpler_*.py` files. The `Kpler/` folder keeps Kpler config, launchers, requirements, manifests, raw pulls, and outputs.
- Uses the Kpler API v2 Cargo Flows endpoint at `https://api.kpler.com/v2/cargo/flows`; it does not instantiate the Kpler Python SDK client.
- Sends a stable `User-Agent` from `KPLER_USER_AGENT` and keeps the API key in the HTTP Basic Authorization header, not in URLs or manifests.
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
export KPLER_API_KEY="..."
./run.sh auth-check
./run.sh run
```

Balance guide pulls use one Kpler `split` per Flow request because the direct API rejects multiple `split` values. PADD routing is handled with exact Kpler zones such as `PADD 1 - A`, `PADD 1 - B`, `PADD 1 - C`, `PADD 3`, and `PADD 5`.

Balance guide pulls include:

- Diesel `Gasoil/Diesel`: PADD 1A/B Canada and non-Canada imports, PADD 1A/B Europe and Other exports, PADD 1C total imports and exports, PADD 3 exports to Africa/Europe/Latin America/Other, PADD 5 total imports and exports, PADD 3 receipts into PADD 1A/B and PADD 1C, and U.S. total imports from Canada/non-Canada plus exports to Europe/Latin America.
- Jet `Kero/Jet`: PADD 1 Canada and non-Canada imports, PADD 1 total exports, PADD 3 exports to Europe/Latin America/Other, PADD 3 receipts into PADD 1 and PADD 5, and PADD 5 total imports and exports.
- PADD subregions are requested directly with Kpler's exact zone spelling. Earlier `PADD 1A` style zones were rejected by Kpler's API bind step.

See [plan.md](plan.md) for the detailed implementation plan.
