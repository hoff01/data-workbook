# weekly_call_ouputs

This portable, standalone folder creates a weekly balance table image
from the balance repository's own generated JSON. It is separate from the
dashboard: it calls the existing balance JSON builder as an upstream source,
creates its own compact weekly JSON, and renders the table PNG from that compact
JSON.

## One-click Windows run

Double-click `run_weekly_images.bat`.

When the main dashboard is opened with its one-click launcher, the same workflow
is available in either workbook's **Reference** tab. **Save Diesel weekly table
image** creates the Diesel table, while **Save Jet weekly table image** creates
the Jet table. Both buttons run in the background, use the launcher's user-local
Python and Node runtimes, and report the product-specific saved or failed status
in the Reference panel.

The launcher:

1. Creates a private `.venv` inside this folder.
2. Installs the required plotting package.
3. Runs the parent balance repository's existing `build:balances` command with
   `BALANCE_WRITE_FULL_BUNDLE=1` to activate its complete JSON output.
4. Creates a weekly-only JSON containing the latest EIA actual and the next
   five forecast weeks.
5. Renders only the weekly balance table PNG, without a Diesel Stats or Jet
   Stats title.

New intermediate full-bundle files are removed after the weekly JSON is
created. The dashboard does not load or depend on this package.

## Weekly output repository

Every EIA actual week has its own self-contained folder:

```text
outputs/
  index.json
  2026-07-03/
    diesel_weekly_stats.json
    diesel_weekly_balance_table.png
    diesel_manifest.json
    jet_weekly_stats.json
    jet_weekly_balance_table.png
    jet_manifest.json
```

The date folder is always the latest actual EIA week in the generated balance
JSON. Re-running during the same EIA week refreshes that folder. The next actual
week automatically creates a new folder, preserving prior weeks. Diesel and Jet
use product-prefixed JSON, manifest, and table-image names, so running one side
never overwrites the other. `index.json` is the catalog of every archived
product/week pair.

The first table column is the latest actual. The yellow column is the first
forecast and the remaining four columns are forecast weeks two through five.
P3 and the total U.S. block are separated by white space, and the dates are
repeated above the U.S. block to match the reference format.
The region names and row sets also follow the reference exactly: PADD 1-A/B,
PADD 2, PADD 3, and US use their own displayed row order rather than sharing a
generic template.
The table fills the image canvas; there is no separate product statistics title,
inventory chart, or composite slide.

## Adjusting the format

All presentation controls are in `weekly_stats_config.json` under `format`:

- `font_scale` changes every font together.
- `colors` contains the table and highlight colors.
- `table` contains image size, margins, column widths, and font sizes.
- `table.us_section_gap_rows` controls the white space between P3 and U.S.;
  `table.repeat_header_before_us` controls the repeated date header.

The effective settings used for a run are copied into that week's
product manifest, making every archived table image reproducible.

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
