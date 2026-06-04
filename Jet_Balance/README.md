# Jet Balance

Self-contained static regional balance workbook for Kerosene-Type Jet Fuel.

Open `../Open_Jet_Dashboard.command` on Mac or
`../Open_Jet_Dashboard.bat` on Windows for the one-click
workflow. The launcher starts the local dashboard server in the background when
needed and opens `http://127.0.0.1:8787/Jet_Balance/index.html`.

Open `index.html` directly in a modern browser only for read-only analysis.
The Reference-tab background update buttons require the local server.
The page loads compact runtime chunks and also keeps source copies in
folder-local subdirectories:

- `eia_monthly/`
- `eia_weekly/`
- `kpler/`
- `padd_1/`
- `data/jet_balance_runtime_base.js`
- `data/jet_balance_runtime_weekly.js`
- `data/jet_balance_runtime_reference.js`

Set `BALANCE_WRITE_FULL_BUNDLE=1` before running the build to also emit the
full debug bundle at `data/jet_balance_bundle.json`.

Local app workflow:

- The balance sheet toggles between monthly and weekly regional balances and
  shows one period per column.
- PADD groups use short display labels: P1-A/B Northeast, P1-C Lower Atlantic,
  P2 Midwest, P3 Gulf Coast, P4 Rocky Mountain, P5 West Coast, U.S.,
  PADDs 1, 2, 3, and PADDs 1,3. Each group can be collapsed,
  and the balance header includes Expand all and Collapse all controls.
- Each PADD builds from supply lines to total supply, demand lines to total
  demand, then calculates build/(draw) per day and total period build/(draw).
- The chart sheet follows the active frequency and selected region, and each
  chart uses a five-year band: 2019 plus 2022-2025.
- The Crude runs sheet uses shared actual-only EIA refinery context for crude
  net inputs, operable and operating capacity, and utilization by PADD and U.S.
- Chart hover shows period values. The underlying chart table appears only
  after clicking Zoom.
- Chart axes auto-fit to visible data without forcing zero, and y-axis ticks
  use clean whole-number increments.
- Each chart card includes a compact latest/prior/band insight strip.
- The Context Pulse adds external-source context from power-sector DFO burn,
  weather/load inputs, and JODI international product demand/trade where those
  files are packaged locally.
- The Reference tab inventories active, packaged, dry-run, and candidate
  sources with latest dates, row counts, official source URLs, and coverage
  notes.
- The Reference tab can start background local refresh groups when served by
  the dashboard update runner: Weekly, Monthly, Other, or Complete.
- The Market Monitor highlights the selected region's latest balance,
  prior-period change, largest regional draw, and lowest stock-cover region.
- Heatmap mode shades balance-table cells by row-level magnitude so large
  moves are easier to scan without changing the displayed values.
- Saved View presets let users save, load, delete, and reset product-specific
  workbook states in browser storage.
- View state is encoded into the URL, so duplicate or manually edited tabs can
  hold independent workbook views.
- `CSV` exports the active balance statement or Crude runs table, `JSON`
  exports the regional balance/crude-runs bundle and view state, and `HTML`
  exports a standalone copy.

Forecast method: monthly balance anchored to a 3-year seasonal average from
2023, 2024, and 2025, with weekly EIA forecast values reconciled back to the
monthly balance through 2026-12-31.
