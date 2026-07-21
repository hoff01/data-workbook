# weekly_call_outputs

This portable, standalone folder creates a weekly balance table image and three
inventory-change bar charts from the dashboard's exact saved state. The weekly
JSON and every PNG are rendered from the same materialized monthly and weekly
rows that the user saved, including all manual adjustments and the exact total
period build/draw values.

## One-click Windows run

Double-click `run_weekly_images.bat`.

When the main dashboard is opened with its one-click launcher, the workflow is
available in either workbook's **Reference** tab. **Save Diesel weekly call
images** creates the Diesel set, while **Save Jet weekly call images** creates
the Jet set. Each button first saves the exact current dashboard state into the
product folder and then runs the formatter from that state. Both buttons run in
the background, use the launcher's user-local Python and Node runtimes, and
report the product-specific saved or failed status in the Reference panel.

The launcher:

1. Creates a managed `.venv` under
   `%USERPROFILE%\US_Balances\weekly_call_outputs` (or the configured
   `US_BALANCES_RUNTIME_ROOT`) so local environments stay together and out of
   the Git checkout.
2. Installs the required plotting package.
3. Runs the parent balance repository's existing `build:balances` command with
   `BALANCE_WRITE_FULL_BUNDLE=1` to activate its complete source bundle.
4. Loads the product's saved `diesel_balance.json` or `jet_balance.json` and verifies that it belongs
   to the product and current settings revision.
5. Creates a weekly-only JSON containing the latest EIA actual, the next five
   forecast weeks, and the portable dashboard state used for the run.
6. Renders the title-free weekly balance table plus the latest EIA Actuals bar
   chart and the first two Forecast bar charts.

New intermediate full-bundle files are removed after the weekly JSON is
created. The dashboard does not load or depend on this package.

## Portable dashboard HTML

The dashboard toolbar's **Export HTML** button first captures the exact active
view and saves its portable dashboard state through the local runner. The
runner then calls `export_dashboard_html.py`, which embeds the normal HTML,
base runtime, weekly data, crude data, Power DFO data, reference data,
adjustments, outages, scenarios, and view controls into one transferable file.

For Diesel, the export is written to both:

```text
outputs/<latest-actual-week>/diesel_export_dashboard.html
outputs/diesel_export_dashboard.html
```

Jet uses `jet_export_dashboard.html`. The dated copy stays with the weekly
archive and the root copy is the latest easy-to-find version. The recipient can
open the HTML directly in a browser without the repository or runner. Refresh
and server-backed persistence are disabled inside the portable snapshot, while
the dashboard, charts, filters, local adjustments, JSON/CSV downloads, and
chart image exports remain available.

## Weekly output repository

Every EIA actual week has its own self-contained folder:

```text
outputs/
  index.json
  diesel_export_dashboard.html
  2026-07-03/
    diesel_export_dashboard.html
    diesel_export_dashboard.manifest.json
    diesel_dashboard_state.json
    diesel_weekly_stats.json
    diesel_weekly_balance_table.png
    diesel_eia_actuals.png
    diesel_forecast_week_1.png
    diesel_forecast_week_2.png
    diesel_manifest.json
    jet_dashboard_state.json
    jet_weekly_stats.json
    jet_weekly_balance_table.png
    jet_eia_actuals.png
    jet_forecast_week_1.png
    jet_forecast_week_2.png
    jet_manifest.json
```

The date folder is always the latest actual EIA week in the generated balance
JSON. Re-running during the same EIA week refreshes that folder. The next actual
week automatically creates a new folder, preserving prior weeks. Diesel and Jet
use product-prefixed JSON, manifest, table, and bar-chart names, so running one
side never overwrites the other. `index.json` is the catalog of every archived
product/week pair and lists the table plus bar-chart PNGs.

The first table column is the latest actual. The yellow column is the first
forecast and the remaining four columns are forecast weeks two through five.
P3 and the total U.S. block are separated by white space, and the dates are
repeated above the U.S. block to match the reference format.
The region names and row sets also follow the reference exactly: PADD 1-A/B,
PADD 2, PADD 3, and US use their own displayed row order rather than sharing a
generic template.
The table fills its image canvas and has no separate product statistics title.
The charts reproduce the requested inventory-change views in million barrels:
green for builds, red for draws, independently scaled axes, and value labels on
every bar. There is no composite Stats slide.

## Adjusting the format

All presentation controls are in `weekly_stats_config.json` under `format`:

- `font_scale` changes every font together.
- `colors` contains the table, bar, and highlight colors.
- `table` contains image size, margins, column widths, and font sizes.
- `table.us_section_gap_rows` controls the white space between P3 and U.S.;
  `table.repeat_header_before_us` controls the repeated date header.
- `chart` contains image size, plot margins, bar width, and font sizes.

The effective settings used for a run are copied into that week's
product manifest, making every archived image reproducible.

## Forecast and adjustment rules

- Weekly actual exports remain the solved/source weekly total. Destination
  values do not recalculate that actual total.
- Forward weekly forecast exports are built from the adjusted monthly forecast.
  PADD 3 is the sum of Latin America, Europe, Africa, and Other; the other PADD
  export rows use their adjusted monthly total.
- Monthly forecast edits step-hold into every forecast week in that month.
  An exact weekly edit takes precedence for only that week and never
  recalibrates its neighboring weeks.
- Total weekly build/draw is exported from the saved materialized row. The
  formatter does not redistribute or solve weekly values to force a monthly
  build/draw target.

Use **Save dashboard** to download a portable JSON copy and persist the same
state in the product folder. Another user can open the dashboard through the
launcher and choose **Import dashboard JSON** to restore the settings,
adjustments, scenarios, and view without relying on browser storage.

## Moving this package

Copy the entire `weekly_call_outputs` folder directly inside another compatible
balance repository. The script finds the parent repository using relative
paths; neither the launcher nor the configuration stores an absolute balance
folder path.

The compatible repository must contain:

- `package.json` with a `build:balances` script.
- `src/build_balance_dashboards.ts`.
- The normal weekly inputs used by that balance.

To switch the same generic package to Jet, change `"product": "diesel"` to
`"product": "jet"` in `weekly_stats_config.json`, or run:

```bat
run_weekly_images.bat --product jet
```

## Useful options

Use an already-created full bundle without rebuilding the balances:

```bat
run_weekly_images.bat --skip-build
```

Re-render the latest archived week from its weekly-only JSON:

```bat
run_weekly_images.bat --render-only
```

Re-render one specific archived week:

```bat
run_weekly_images.bat --render-only --week 2026-07-03
```

The `--output-dir` option changes the archive root. The script still creates a
date folder below it, so weekly repositories are never flattened together.
