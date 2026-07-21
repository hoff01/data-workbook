# US Balances

Static Diesel and Jet balance dashboards backed by EIA monthly/weekly data, Kpler flow context, refinery capacity, PADD 1 splits, and power-generation DFO context.

## Main Outputs

- `Diesel_Balance/index.html` - packaged Diesel dashboard.
- `Jet_Balance/index.html` - packaged Jet dashboard.
- `eia_monthly/` - public monthly balance CSVs.
- `eia_weekly/` - public weekly balance CSVs.
- `Kpler/output/` - packaged Kpler flow outputs used by the dashboards.

## Source Code

- `src/update_pipeline.ts` - update orchestration.
- `src/build_balance_dashboards.ts` - dashboard generator.
- `src/monthly.ts` and `src/run_weekly_pipeline.ts` - EIA source refreshes.
- `src/export_raw_headers.py` and `src/export_bulk_series.py` - EIA public CSV exports.
- `src/kpler_*.py` - Kpler pull, transform, and PADD 1 split support.
- `power_generation_dfo/` - power-sector DFO refresh scripts and outputs.

## Common Commands

```bash
npm run update:monthly
npm run update:weekly
npm run update:other
npm run update:power-dfo
npm run build:balances
npm run validate
npm run verify:dashboard
```

## Kpler API Key

On Windows, double-click `Configure_Kpler_Auth.bat`. It creates the ignored
root `.env.local` file from `.env.example` and opens it in Notepad. Paste the
value after `Basic ` here, then save:

```dotenv
KPLER_API_KEY=your-key-value
```

On macOS/Linux, run `cp .env.example .env.local` and edit the same line. Check
the file without calling Kpler using `npm run kpler:preflight`; the output must
say `auth_configured=true`. Validate the key with one small API request using
`npm run kpler:auth-check` (or `Kpler\run.ps1 -CheckAuth` on Windows). Never
commit `.env.local` or a real key.

The `update:*` commands rebuild `Diesel_Balance/index.html` and `Jet_Balance/index.html` after data changes, then run the dashboard freshness check. Monthly and complete updates download the ignored `cache/eia/PET.zip` prerequisite before exporting, so a fresh GitHub clone does not require a pre-populated cache. `npm run update:all` includes the live Kpler pull and fails visibly if a required Kpler step fails. Set `US_BALANCES_SKIP_KPLER_REFRESH=1` only when you intentionally want a warning-labeled run that keeps the existing local `Kpler/output/` files.

## Documentation

Durable plans, architecture notes, and chart-recreation guides live under `docs/`.

For day-to-day Windows/Mac launch, refresh, shared-edit, GitHub push, and
certificate-warning avoidance steps, use `docs/operating-guide.md`.

For copying the dashboards to another user or importing an exact saved
dashboard JSON, use `docs/transfer-guide.md`.

## Local Files

Local credentials and runtime caches are intentionally ignored:

- `.env`
- `Kpler/config/local.env`
- `cache/eia/PET.zip`
- `node_modules/`
- `logs/`
- generated Kpler raw request folders
