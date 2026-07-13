# weekly_call_ouputs

This portable, standalone folder creates PowerPoint-ready weekly balance images
from the balance repository's own generated JSON. It is separate from the
dashboard: it calls the existing balance JSON builder as an upstream source,
creates its own compact weekly JSON, and renders every image from that compact
JSON.

## One-click Windows run

Double-click `run_weekly_images.bat`.

The launcher:

1. Creates a private `.venv` inside this folder.
2. Installs the required plotting package.
3. Runs the parent balance repository's existing `build:balances` command with
   `BALANCE_WRITE_FULL_BUNDLE=1` to activate its complete JSON output.
4. Creates a weekly-only JSON containing the latest EIA actual and the next
   five forecast weeks.
5. Renders the table, latest EIA Actuals plot, first two Forecast plots, and an
   exact 2400 x 1350 standard 16:9 PowerPoint slide image.

New intermediate full-bundle files are removed after the weekly JSON is
created. The dashboard does not load or depend on this package.

## Weekly output repository

Every EIA actual week has its own self-contained folder:

```text
outputs/
  index.json
  2026-07-03/
    diesel_weekly_stats.json
    diesel_weekly_stats_slide.png
    manifest.json
    individual_outputs/
      diesel_weekly_balance_table.png
      diesel_eia_actuals.png
      diesel_forecast_week_1.png
      diesel_forecast_week_2.png
```

The date folder is always the latest actual EIA week in the generated balance
JSON. Re-running during the same EIA week refreshes that folder. The next actual
week automatically creates a new folder, preserving prior weeks. `index.json`
is the catalog of every archived week.

The first table column is the latest actual. The yellow column is the first
forecast and the remaining four columns are forecast weeks two through five.
P3 and the total U.S. block are separated by white space, and the dates are
repeated above the U.S. block to match the reference format.
The region names and row sets also follow the reference exactly: PADD 1-A/B,
PADD 2, PADD 3, and US use their own displayed row order rather than sharing a
generic template.
The chart titles keep `EIA Actuals` and `Forecast` capitalized and on one line.
Each chart scales its Y axis independently, including extra label space above
positive bars and below negative bars so the title, values, and bars do not
overlap.

## Adjusting the format

All presentation controls are in `weekly_stats_config.json` under `format`:

- `font_scale` changes every font together.
- `colors` contains all table, chart, and highlight colors.
- `table` contains image size, margins, column widths, and font sizes.
- `table.us_section_gap_rows` controls the white space between P3 and U.S.;
  `table.repeat_header_before_us` controls the repeated date header.
- `chart` contains image size, plot margins, bar width, and font sizes.
- `slide.width_px` and `slide.height_px` control the complete slide canvas.
- `slide.placements` controls table and chart positions on the complete slide.
- `slide.enforce_equal_chart_size` prevents Actuals and Forecast placements
  from using different dimensions.

Each placement is `[left, bottom, width, height]`, measured from 0.0 to 1.0
across the full slide. For example, increasing the third value makes that image
wider. The defaults are calibrated to the supplied full PowerPoint-slide
reference and render at exactly 2400 x 1350 pixels.

The effective settings used for a run are copied into that week's
`manifest.json`, making every archived image set reproducible.

## Moving this package

Copy the entire `weekly_call_ouputs` folder directly inside another compatible
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
