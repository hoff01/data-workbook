# EIA Weekly Source Switch

This repo uses `config/eia_weekly_source.json` to decide where the latest EIA weekly overlay comes from.

The current default is `latest_source: "xls"` because EIA paused the planned WPSR dissemination change and is still publishing the legacy XLS table workbooks on the Weekly Petroleum Status Report page.

## Fast Switch When EIA Changes

Use this file-drop workflow when EIA finally moves away from the XLS tables:

1. Copy or drop `config/eia_weekly_source.csv.example.json` over `config/eia_weekly_source.json`.
2. If EIA keeps the expected CSV URL, leave `csv.url` blank.
3. If EIA publishes a different CSV URL, set `csv.url` to that exact URL.
4. Run `npm run update:weekly`.

Rollback is the reverse: restore the current XLS config, or set `"latest_source": "xls"` in `config/eia_weekly_source.json`, then run `npm run update:weekly`.

This file-drop path assumes EIA keeps the expected WPSR CSV shape with `stub_1`, `sourcekey`, and current/week-ago date columns. If EIA changes the CSV schema, the parser in `src/weekly_xls.py` and the freshness header reader in `src/verify_weekly_freshness.ts` still need a code update.

Do not remove `xls.tables` from the dropped config. Keeping the XLS table list makes rollback a one-line source-mode change instead of a second file recovery step.

## XLS Table Change Only

If EIA keeps XLS files but changes the file names or table set, keep `"latest_source": "xls"` and only edit `xls.tables`.

Each entry needs:

```json
{
  "id": "PSW01",
  "url": "https://ir.eia.gov/wpsr/psw01.xls"
}
```

The `id` becomes `source_table` in the raw weekly artifact, so keep it stable and uppercase where possible.

## Overrides

Normal operation should use the JSON file. These overrides are for temporary debugging:

```bash
EIA_WEEKLY_LATEST_SOURCE=csv npm run update:weekly
EIA_WEEKLY_SOURCE_CONFIG=/path/to/eia_weekly_source.json npm run update:weekly
EIA_WEEKLY_LATEST_SOURCE=csv EIA_WPSR_CSV_URL=https://example.com/wpsr.csv npm run verify:weekly
EIA_WEEKLY_LATEST_SOURCE=csv EIA_WPSR_TODAY=2026-06-09 npm run verify:weekly
npm run weekly -- --latest-source csv
npm run weekly:raw -- --latest-source csv
```

Use the JSON file or `EIA_WEEKLY_LATEST_SOURCE` for full `update:weekly` runs. The `--latest-source` CLI flag applies to `npm run weekly` and `npm run weekly:raw`; it is useful for parser debugging but does not change the separate freshness command.

Precedence is:

1. CLI `--latest-source`
2. `EIA_WEEKLY_LATEST_SOURCE`
3. `config/eia_weekly_source.json`
4. Built-in fallback defaults

## Why The Config Is Outside eia_weekly/

The raw weekly pull cleans generated files inside `eia_weekly/` before rebuilding the raw artifact. Keep this source config under `config/` so a normal refresh cannot delete the switch file. Use `npm run weekly` for a standalone safe refresh that rebuilds the raw data, exports the product CSVs, removes temporary raw artifacts, and reapplies the Kpler PADD 1 split columns; use `npm run weekly:raw` only when debugging the raw parser.

## Validation After A Switch

Run:

```bash
npm run update:weekly
npm run validate
npm run typecheck
```

Expected success signals:

- `weekly rows=... latest_source=csv` or `latest_source=xls`
- `weekly freshness ok upstream=...`
- `dashboard freshness ok diesel:weekly=... jet:weekly=...`
- `validation ok`
