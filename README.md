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

Use `npm run update:all` only when Kpler authentication is available and a full refresh is intended.

## Documentation

Durable plans, architecture notes, and chart-recreation guides live under `docs/`.

## Local Files

Local credentials and runtime caches are intentionally ignored:

- `.env`
- `Kpler/config/local.env`
- `node_modules/`
- `logs/`
- generated Kpler raw request folders
