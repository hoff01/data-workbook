# AGENTS.md - Static Petroleum Forecast HTML Apps

This file is the implementation contract and build plan for the local static
forecast frontend. Follow this plan unless Alex explicitly changes the
constraints.

The current scope is United States petroleum products only. Do not build Europe
specific screens yet.

---

## 0. Objective

Build three separate, high-performance, local-first HTML applications:

```text
dist/gasoline-forecast.html
dist/diesel-forecast.html
dist/jet-forecast.html
```

Each file must be a full standalone analytical product forecast app for one
commodity. Gasoline, diesel, and jet should be as close to identical as the data
allows: same layout, same controls, same calculation architecture, same chart
types, same export behavior, same QA gates, and same performance targets.

The forecasting target is a full product balance, not a chart-only extrapolation.
Monthly balances are the anchor dataset because they carry the broadest balance
structure and cleaner accounting categories. The weekly EIA forecast should be
derived from the monthly balance path, then reconciled back to the observed
weekly cadence so the app can explain how a monthly supply/demand view becomes a
weekly EIA-style forecast.

The end user should need only a modern browser to open the final release files.
No Python, PowerShell, Rust, Node, package install, VPN, proxy, or server should
be required at runtime.

---

## 1. Concrete Deliverables

### 1.1 Final static HTML files

Build exactly three product files for the current scope:

```text
dist/gasoline-forecast.html
dist/diesel-forecast.html
dist/jet-forecast.html
```

Do not ship one HTML file with a product toggle as the primary deliverable.
Product switching may exist as a convenience only if the three separate final
files still exist.

### 1.2 Shared source tree

Maintain one shared frontend/calculation source tree:

```text
shared calculation engine
shared data model
shared chart engine
shared UI components
shared build pipeline
product-specific config
        |
        +-- gasoline-forecast.html
        +-- diesel-forecast.html
        +-- jet-forecast.html
```

Do not manually copy and edit three separate apps.

### 1.3 Product parity

The three products must expose matching sections:

```text
summary dashboard
balance table
EIA weekly panel
EIA monthly panel
Kpler split panel
JODI reference panel when available
forecast horizon controls
official adjustment audit
trader scenario controls
sensitivity grid
scenario comparison
chart deck
data quality panel
download/export panel
```

Fields that do not exist for a product should render as unavailable with a clear
data reason, not as a broken or missing layout.

### 1.4 Data inputs already present in this repo

The first build should use the existing local pipeline outputs:

```text
eia_weekly/gasoline.csv
eia_weekly/diesel.csv
eia_weekly/jet.csv

eia_monthly/gasoline.csv
eia_monthly/diesel.csv
eia_monthly/jet.csv

Kpler/config/products.yml
Kpler/config/pull_sets.yml
Kpler/config/regions.yml
Kpler/manifest.json

Jodi_Data/africa_gasoline.csv
Jodi_Data/africa_diesel.csv
Jodi_Data/africa_jet.csv
Jodi_Data/europe_gasoline.csv
Jodi_Data/europe_diesel.csv
Jodi_Data/europe_jet.csv
Jodi_Data/manifest.json
```

Europe-specific UI is out of scope for this pass, but JODI and Kpler data can
still be loaded as reference inputs if needed for U.S. balances.

---

## 2. Product Definitions

Use one product registry. Every shared component should read this registry
instead of hardcoding product names in the UI.

```ts
type ProductKey = "gasoline" | "diesel" | "jet";

type ProductConfig = {
  key: ProductKey;
  title: string;
  eiaWeeklyCsv: string;
  eiaMonthlyCsv: string;
  kplerProductName: string;
  jodiAfricaCsv: string;
  jodiEuropeCsv: string;
  defaultUnit: "kbd";
  dateColumn: "week_ending" | "Date";
};
```

Default values:

```text
gasoline:
  title: Gasoline Forecast
  Kpler product: Light Ends
  weekly source: eia_weekly/gasoline.csv
  monthly source: eia_monthly/gasoline.csv

diesel:
  title: Diesel Forecast
  Kpler product: Gasoil/Diesel
  weekly source: eia_weekly/diesel.csv
  monthly source: eia_monthly/diesel.csv

jet:
  title: Jet Forecast
  Kpler product: Kero/Jet
  weekly source: eia_weekly/jet.csv
  monthly source: eia_monthly/jet.csv
```

---

## 3. UX Standard

This is an analyst/trader tool, not a marketing page. The first screen should
be the working dashboard.

### 3.1 First viewport

The first viewport must show:

```text
product name
latest data date
forecast horizon
official forecast total
scenario total
change from official
data freshness status
top chart
key controls
```

There should be no landing hero, no decorative illustration, and no marketing
copy. The user should be able to start using the tool immediately.

### 3.2 Layout

Use a dense but readable desktop-first analytics layout:

```text
top command bar
left or top scenario controls
main chart workspace
right or lower inspection/details panel
tabbed detail sections
sticky summary strip
```

Responsive behavior:

```text
desktop: multi-column workspace
tablet: controls above chart, details below
mobile: single-column, chart-first, compact controls
```

### 3.3 Visual design

Design target:

```text
quiet
professional
fast to scan
high contrast where data matters
no one-note color palette
no oversized cards
no nested cards
no gradient orb decoration
```

Use color by meaning:

```text
official baseline: neutral blue
trader scenario: green or amber depending on direction
downside/stress: red
historical/reference: gray
forecast/estimated: dashed line style
missing/stale data: muted warning style
```

### 3.4 Controls

Use controls that match the action:

```text
segmented controls for scenario/product view modes
toggles for include/exclude options
sliders or numeric steppers for adjustment values
date range inputs for horizon changes
menus for saved scenario presets
icon buttons for reset, export, copy, expand, collapse
tabs for weekly/monthly/Kpler/JODI/data quality views
```

Avoid explanatory text inside the app. The UI should be self-evident through
labels, tooltips, and consistent placement.

---

## 4. Application Modes Inside Each Product File

Each product HTML should include two calculation layers in the same file:

```text
official forecast
trader scenario
```

The official forecast is the default and source of truth. Trader changes are
temporary overlays on top of the official forecast.

Do not create separate official/trader HTML files in this version unless Alex
asks for that later. The requested split is by product: gasoline, diesel, jet.

### 4.1 Official layer

The official layer contains:

```text
base forecast values
hardcoded official adjustments
forecast horizon
official scenario labels
published metadata
```

Official values are editable only in source/config before build. Trader runtime
actions must never mutate official source values.

### 4.2 Trader layer

Trader adjustments are:

```text
runtime-only by default
sparse overlays
resettable without changing official values
exportable as a separate scenario patch
importable only as trader patches
```

Reset must clear only trader/runtime adjustments.

---

## 5. Runtime Data Model

Use this layered model for every product:

```text
baseProductData
+ officialAdjustments
= officialActiveForecast

baseProductData
+ officialAdjustments
+ traderRuntimeAdjustments
= traderActiveScenario
```

### 5.1 Core entities

```rust
pub enum Product {
    Gasoline,
    Diesel,
    Jet,
}

pub enum Frequency {
    Daily,
    Weekly,
    Monthly,
}

pub enum BalanceMetric {
    Production,
    Imports,
    Exports,
    Stocks,
    ProductSupplied,
    Demand,
    RefineryRuns,
    NetSupply,
    ImpliedBalance,
}

pub enum DataLineage {
    RealizedEiaWeekly,
    RealizedEiaMonthly,
    MonthlyDerivedWeeklyForecast,
    KplerInformedSplit,
    JodiReference,
    OfficialAdjustment,
    TraderAdjustment,
}

pub struct ForecastPoint {
    pub product: Product,
    pub period_idx: u32,
    pub frequency: Frequency,
    pub metric: BalanceMetric,
    pub value_kbd: f64,
    pub is_forecast: bool,
    pub lineage: DataLineage,
    pub quality_flag: u8,
}
```

### 5.1A Product balance graph

Represent every forecast as a balance graph, not as loose columns.

```rust
pub struct BalanceNode {
    pub product: Product,
    pub frequency: Frequency,
    pub period_idx: u32,
    pub metric: BalanceMetric,
    pub value_kbd: f64,
    pub lineage: DataLineage,
    pub source_node_ids: &'static [u32],
}

pub struct BalanceReconciliation {
    pub product: Product,
    pub month_idx: u32,
    pub monthly_value_kbd: f64,
    pub weekly_derived_value_kbd: f64,
    pub absolute_diff_kbd: f64,
    pub percent_diff: f64,
    pub tolerance_kbd: f64,
    pub passes: bool,
}
```

The balance graph must let the app answer this question for any forecast value:

```text
which monthly value, realized weekly value, split share, adjustment, and model
component produced this number?
```

### 5.2 Official adjustments

Hardcode official adjustments in source or generated Rust constants:

```rust
pub enum AdjustmentMode {
    Delta,
    Override,
    Percent,
}

pub struct OfficialAdjustment {
    pub product: Product,
    pub metric: BalanceMetric,
    pub period_idx: u32,
    pub mode: AdjustmentMode,
    pub value: f64,
    pub note: &'static str,
}
```

### 5.3 Trader adjustments

Trader changes should stay sparse:

```rust
pub struct TraderAdjustment {
    pub input_id: u32,
    pub period_idx: u32,
    pub mode: AdjustmentMode,
    pub value: f64,
}
```

---

## 6. Forecast Horizon Rule

Each product can have its own official horizon, but the UI and engine must use
the same horizon model:

```rust
pub struct ForecastHorizon {
    pub product: Product,
    pub start_period_idx: u32,
    pub end_period_idx: u32,
    pub frequency: Frequency,
}
```

Rules:

```text
official config controls max horizon
trader scenario cannot extend beyond official horizon
charts and tables render only inside the active horizon
source data can extend beyond horizon for lag/reference calculations
```

---

## 6A. Balance-First Forecasting Mandate

The core model must build a full balance for gasoline, diesel, and jet before it
builds weekly forecast outputs. The balance should be explicit enough that Alex
can see which side of the ledger changed and why.

### 6A.1 Monthly balance is the anchor

Use monthly EIA outputs as the primary accounting layer:

```text
monthly supply
monthly imports
monthly exports
monthly demand/product supplied
monthly stock change
monthly implied balance
monthly PADD and route/split adjustments where available
```

Monthly values should establish the official balance path. Weekly values are the
higher-frequency expression of that path, not an independent model that can
drift away from the monthly view.

### 6A.2 Weekly EIA forecast is derived from monthly values

For each product, generate the weekly EIA-style forecast from the monthly
balance using a reconciliation pipeline:

```text
latest monthly balance
        |
        v
monthly forecast path by balance component
        |
        v
calendar-aware weekly allocation
        |
        v
weekly EIA category forecast
        |
        v
weekly-to-monthly reconciliation check
        |
        v
published official weekly forecast layer
```

The weekly allocation must respect:

```text
month boundaries
partial weeks
EIA week-ending convention
calendar days in month
holiday and seasonal effects when supported by data
latest realized weekly observations
known monthly values that are newer than weekly or vice versa
```

### 6A.3 Reconciliation rules

Every weekly forecast must reconcile back to the monthly balance within an
audited tolerance.

Required checks:

```text
sum or average weekly values to monthly equivalent
compare against monthly official path
record absolute difference
record percentage difference
flag rows outside tolerance
show reconciliation status in the quality panel
block release build on unexplained material breaks
```

The app should make it obvious whether a weekly number is:

```text
realized weekly EIA data
monthly-derived weekly forecast
Kpler-informed split
JODI-informed reference value
trader-adjusted runtime value
```

### 6A.4 Balance components

Build each product around the same balance grammar, even where exact component
names differ across EIA files.

Core components:

```text
production or refinery output
imports
exports
net receipts/transfers when available
product supplied or demand
stock change
ending stocks
implied balance residual
```

Do not hide the residual. If the monthly balance does not close cleanly, expose
the residual as an explicit diagnostic series so Alex can decide whether to
adjust the official path.

### 6A.5 Forecasting model stack

Use an ensemble hierarchy. Do not rely on one forecasting method.

Baseline statistical layer:

```text
seasonal naive
rolling seasonal average
ETS / exponential smoothing
ARIMA / SARIMAX where it improves backtests
state-space trend and seasonal decomposition
```

Machine-learning layer:

```text
gradient boosted trees for component-level deltas
regularized regression with lagged features
calendar and holiday features
Kpler split/share features where reliable
JODI reference features only where they improve validation
weather and macro features only after Alex approves those inputs
```

Advanced/probabilistic layer:

```text
quantile forecasts
bootstrap analog paths
conformal prediction intervals for calibrated uncertainty
Bayesian or state-space uncertainty where tractable
neural sequence models only if backtests beat simpler models and the added
complexity is justified
```

The first production model should favor explainability and backtest performance
over novelty. More computationally intensive methods are allowed at build time,
but the browser runtime must stay fast and deterministic.

### 6A.6 Model selection and backtesting

Every product/component model must be selected through rolling-origin backtests.

Minimum backtest outputs:

```text
weekly error by horizon
monthly error by horizon
component-level error
directional accuracy
stock-change error
weighted absolute percentage error where denominator is stable
MAE and RMSE in kbd
interval coverage for probabilistic outputs
model rank by product and component
selected-model reason
```

Backtests should compare the full monthly-to-weekly reconciliation path, not
only raw model predictions.

### 6A.7 Refresh and latest-data requirement

Every build must use the most recent local pipeline outputs available at build
time. Before producing final HTML, the build must record:

```text
latest weekly EIA date by product
latest monthly EIA date by product
latest Kpler manifest timestamp if included
latest JODI manifest timestamp if included
source file modification time
source checksum
forecast build timestamp
documentation/version audit timestamp
```

If a source is stale, the app still builds, but the first viewport and quality
panel must show the stale source clearly.

### 6A.8 Tomorrow-chart placeholder

Alex will add more chart behavior details later. Until then, design the chart
system so new chart rules can be added without changing the balance engine:

```text
chart definitions read from product config
series dependencies read from node IDs
axis/unit/format rules are data-driven
forecast and reconciliation traces are first-class series
chart layout can be changed without changing model calculations
```

---

## 7. Data Storage Strategy

### 7.1 Runtime analytical data should not be JSON

Do not store large runtime datasets as JSON.

Allowed JSON:

```text
small manifest metadata
small build metadata
tiny UI labels
small QA summaries
```

Not allowed as runtime JSON:

```text
forecast tables
historical time series
large chart datasets
scenario matrices
full EIA weekly/monthly tables
Kpler daily flows
JODI reference history
```

### 7.2 Cold and hot formats

Use:

```text
Parquet for cold/reference source data
Arrow IPC or custom typed-array binary for hot startup data
Float64Array for calculation precision
Float32Array for display-only chart traces where acceptable
Uint16Array/Uint32Array for IDs and period indexes
```

Preferred pipeline:

```text
CSV pipeline outputs
        |
        v
build-time normalization
        |
        v
Parquet cold store
        |
        v
product-specific hot binary bundle
        |
        v
WASM memory / typed arrays
```

### 7.3 Product bundle shape

Each product should receive a minimal embedded bundle:

```text
product id
period index table
metric id table
weekly values
monthly values
Kpler split values when available
JODI reference values when used
official adjustment constants
precomputed chart reference lines
quality flags
```

Do not embed all columns from every CSV if only a subset is used.

---

## 8. Calculation Architecture

### 8.1 Rust/WASM owns numeric-heavy work

Most business logic and numeric calculations should live in Rust and compile to
WebAssembly.

Rust owns:

```text
input normalization
unit normalization to kbd
weekly/monthly alignment
base + official + trader layer application
forecast horizon enforcement
dependency graph resolution
dirty node calculation
scenario calculations
sensitivity matrices
Monte Carlo or bootstrap scenario fan calculations
balance sheet calculations
period projections
chart series construction when numeric-heavy
cache keys/checksums
```

TypeScript owns:

```text
DOM events
state patch creation
worker lifecycle
message scheduling
chart registry
chart update scheduling
mode-specific UI presentation
download/export actions
single-file bootstrap
```

### 8.2 Computationally intensive scenario engine

The app should support heavy analysis without freezing the UI:

```text
multi-period forecast recalculation
weekly-to-monthly conversion
monthly-to-weekly interpolation where needed
official and trader layer diffing
rolling averages
seasonal normalization
year-over-year comparisons
z-score and percentile bands
sensitivity grids across demand/import/export/stock variables
bootstrap historical analog paths
Monte Carlo scenario fan generation
stress cases by percentile shocks
correlation matrix calculations for selected inputs
```

All heavy loops must run in a worker through Rust/WASM. The main thread should
stay responsive.

### 8.2A Build-time forecasting engine

The most computationally expensive model training and backtesting should happen
at build time, not inside the static browser file.

Build-time engine responsibilities:

```text
fit monthly component models
fit or calibrate weekly allocation models
run rolling-origin backtests
rank candidate models by product/component/horizon
generate official monthly balance path
derive official weekly EIA forecast path
calibrate uncertainty intervals
precompute scenario fan seeds or reference paths
write selected model metadata
write feature importance or driver summaries where available
write reconciliation diagnostics
```

Browser runtime responsibilities:

```text
load selected official paths
apply official and trader overlays
recalculate balance impacts from sparse changes
render precomputed forecast diagnostics
run fast local sensitivity and bootstrap variants
avoid retraining heavyweight models
```

If a model cannot be reproduced deterministically at build time, do not use it
for the official layer.

### 8.3 Dirty dependency graph

Every derived value and chart series must declare dependencies.

Example nodes:

```rust
pub enum NodeId {
    WeeklyBalance,
    MonthlyBalance,
    MonthlyBalanceForecast,
    MonthlyToWeeklyAllocator,
    WeeklyEiaForecast,
    MonthlyWeeklyReconciliation,
    ProductSupplied,
    ImportSplit,
    ExportSplit,
    StockChange,
    ImpliedDemand,
    ImpliedBalanceResidual,
    ModelBacktestScore,
    PredictionInterval,
    ScenarioDelta,
    PercentileBand,
    SensitivityGrid,
    MainChartSeries,
    BalanceTableRows,
}
```

Runtime rule:

```text
input patch arrives
        |
        v
mark directly affected nodes dirty
        |
        v
walk dependency graph
        |
        v
calculate only dirty nodes
        |
        v
return only changed summary values, tables, and chart series
```

### 8.4 Patch messages only

Never send the full model across the worker boundary for normal updates.

```ts
type InputPatchMessage = {
  type: "INPUT_PATCH";
  product: "gasoline" | "diesel" | "jet";
  revision: number;
  changed: Array<{
    inputId: number;
    periodIdx: number;
    mode: "delta" | "override" | "percent";
    value: number;
  }>;
};
```

### 8.5 Calculation results

Transfer typed buffers instead of copying large arrays.

```ts
type CalcResultMessage = {
  type: "CALC_RESULT";
  product: "gasoline" | "diesel" | "jet";
  revision: number;
  changedOutputs: Array<{
    nodeId: number;
    value: number;
  }>;
  changedTables: Array<{
    tableId: number;
    buffer: ArrayBuffer;
    rowCount: number;
  }>;
  changedChartSeries: Array<{
    chartId: number;
    seriesId: number;
    xBuffer?: ArrayBuffer;
    yBuffer: ArrayBuffer;
    len: number;
    dtype: "f32" | "f64";
  }>;
};
```

---

## 9. Worker Architecture

### 9.1 Thread split

```text
Main thread:
  shell UI
  controls
  summary cards
  chart containers
  keyboard shortcuts
  export/download

Calculation worker:
  Rust/WASM engine
  product bundle load
  typed array workspace
  dependency graph
  calculations
  result buffer creation

Optional data worker:
  Parquet/Arrow decode
  DuckDB-WASM queries if enabled
  large export preparation
```

Use one calculation worker first. Add more workers only if profiling proves a
benefit.

### 9.2 Startup sequence

```text
load shell
render command bar and loading state
start calculation worker
instantiate embedded WASM
load embedded product bundle
apply official adjustments
calculate initial official forecast
render summary values
initialize visible charts
schedule offscreen chart prep during idle time
```

### 9.3 UI responsiveness

Rules:

```text
do not block the main thread during initialization
show data freshness and worker status
drop stale worker revisions
batch rapid input changes
use requestAnimationFrame for chart flushes
use idle callbacks for offscreen work
```

---

## 10. Chart System

### 10.1 Chart library

Default to a Plotly partial bundle that supports the required chart types.

Use:

```text
plotly.js-cartesian-dist-min for most bar/line/heatmap work
plotly.js-gl2d-dist-min only if profiling shows large traces need WebGL
full Plotly only if partial bundles cannot support required charts
```

### 10.2 Required charts per product

Each of gasoline, diesel, and jet should include the same chart set:

```text
official vs trader forecast line
weekly balance components
monthly balance components
stocks and stock-change chart
monthly balance to weekly forecast reconciliation chart
realized weekly vs monthly-derived weekly forecast chart
imports by group
exports by group
Kpler split share chart
seasonal band chart
year-over-year delta chart
sensitivity heatmap
scenario fan chart
forecast error/backtest chart
prediction interval coverage chart
data freshness timeline
```

Charts that rely on unavailable product data should render an unavailable state
with the missing data reason.

### 10.3 Chart registry

Every chart must be registered:

```ts
type ChartRegistryItem = {
  chartId: number;
  product: "gasoline" | "diesel" | "jet";
  elementId: string;
  priority: "critical" | "high" | "normal" | "low";
  visible: boolean;
  nearViewport: boolean;
  initialized: boolean;
  dependsOnNodeIds: number[];
  updateStrategy: "restyle" | "relayout" | "update" | "react" | "extendTraces";
  usesWebGL: boolean;
  maxDisplayPoints?: number;
};
```

### 10.4 Chart update order

Always update in this order:

```text
1. visible summary numbers
2. visible critical charts
3. visible high-priority charts
4. visible normal charts
5. near-viewport charts
6. hidden charts during idle time only
```

### 10.5 Chart update rules

Use `Plotly.newPlot` only once per chart initialization.

After initialization:

```text
restyle for trace data changes
relayout for layout-only changes
update for combined data/layout patches
react for broader replacements
extendTraces for append-only series
```

Do not synchronously redraw every chart after an input change.

### 10.6 Downsampling

Calculation uses full precision. Display uses the smallest trace that still
shows the correct shape.

Rules:

```text
precompute chart-ready series at build time when static
downsample long historical traces
use Float32Array for chart-only values where acceptable
keep export/detail views able to access full data
```

---

## 11. Tables and Grid System

Use virtualized tables for long datasets.

Required grids per product:

```text
weekly balance table
monthly balance table
scenario adjustment table
official adjustment audit table
Kpler split table
data quality table
source column inventory table
```

Table rules:

```text
fixed row heights
sticky headers
numeric alignment to the right
compact units in headers
sort by any visible column
filter by date and metric
copy selected rows
export visible table to CSV
export full product bundle to CSV/Parquet when enabled
```

---

## 12. Source Data Normalization

### 12.1 EIA weekly

Input files:

```text
eia_weekly/gasoline.csv
eia_weekly/diesel.csv
eia_weekly/jet.csv
```

Current shape:

```text
date column: week_ending
gasoline columns: about 105
diesel columns: about 49
jet columns: about 46
```

Normalize to:

```text
product
frequency = weekly
period_start
period_end
period_idx
padd
subregion
metric
flow_group
unit
value
source_column
quality_flag
```

Weekly data is the realized high-frequency target and the presentation cadence.
It should be used to:

```text
anchor the latest observed weekly values
learn intra-month allocation patterns
validate monthly-derived weekly forecasts
calculate short-horizon forecast errors
preserve EIA week-ending dates exactly
```

Do not let weekly-only projections drift away from the monthly balance path.

### 12.2 EIA monthly

Input files:

```text
eia_monthly/gasoline.csv
eia_monthly/diesel.csv
eia_monthly/jet.csv
```

Normalize to the same long schema as weekly data.

Monthly files should be sorted descending in source outputs where the EIA
pipeline requires it, but the frontend bundle should store period indexes in
ascending numeric order for fast typed-array access.

Monthly data is the official balance anchor. Normalize enough monthly columns to
construct and audit the full balance for each product:

```text
supply-side components
demand/product supplied components
imports
exports
stock levels
stock change
regional/PADD components
route/split adjustment fields where they exist
source units and converted kbd values
```

The normalizer must classify monthly columns into balance roles and record any
columns excluded from the hot bundle in the source column inventory.

### 12.3 Kpler

Product mapping:

```text
gasoline -> Light Ends
diesel -> Gasoil/Diesel
jet -> Kero/Jet
```

Kpler-derived frontend fields:

```text
import share by origin group
export share by destination group
PADD 1 A/B vs PADD 1 C share when available
PADD 3 export group splits
PADD 5 import group splits
domestic PADD routes when available
forecast/realized flag
```

Keep `with_intra_country` semantics from the Kpler pipeline in the manifest so
the UI can show whether a route is international-only or domestic-inclusive.

### 12.4 JODI

JODI data can be used as external reference data for Africa and Europe flows,
but Europe-specific pages and screens are out of scope for this pass.

If loaded, normalize to:

```text
product
region
region_detail
country
flow_breakdown
unit
period_month
value
assessment
```

### 12.5 Unit policy

Primary runtime unit:

```text
kbd
```

Rules:

```text
keep original unit in source audit fields
convert barrels/month to kbd using calendar days
convert weekly barrels to kbd using 7 days
avoid storing both thousand barrels and kbd equivalents in the hot bundle unless needed for audit
```

---

## 13. Build Pipeline

### 13.1 Recommended source layout

```text
forecast_static_html/
  AGENTS.md

  rust-core/
    Cargo.toml
    src/
      lib.rs
      model.rs
      products.rs
      periods.rs
      units.rs
      adjustments.rs
      official_adjustments.rs
      horizon.rs
      dependency_graph.rs
      dirty_tracker.rs
      balance_engine.rs
      monthly_balance_engine.rs
      weekly_allocator.rs
      reconciliation.rs
      scenario_engine.rs
      sensitivity_engine.rs
      chart_series.rs
      memory.rs
      ffi.rs

  build-tools/
    Cargo.toml
    src/
      main.rs
      csv_normalizer.rs
      parquet_writer.rs
      hot_bundle_writer.rs
      forecast_validator.rs
      model_backtester.rs
      model_selector.rs
      forecast_trainer.rs
      reconciliation_report.rs
      wasm_embedder.rs
      html_packager.rs

  app/
    src/
      main.ts
      boot/
        bootProduct.ts
      config/
        products.ts
        officialAdjustments.generated.ts
        forecastBundle.generated.ts
      workers/
        calc.worker.ts
        wasmLoader.ts
      state/
        store.ts
        patchQueue.ts
        revisionClock.ts
      charts/
        chartRegistry.ts
        chartScheduler.ts
        plotlyAdapter.ts
        downsample.ts
      tables/
        virtualTable.ts
        tableRegistry.ts
      ui/
        commandBar.ts
        summaryStrip.ts
        scenarioControls.ts
        productWorkspace.ts
        qualityPanel.ts
      styles/
        app.css

  data/
    normalized/
      gasoline.parquet
      diesel.parquet
      jet.parquet
    hot/
      gasoline.bundle.bin
      diesel.bundle.bin
      jet.bundle.bin

  scripts/
    build-product.mjs
    build-all.mjs
    smoke-test.mjs
    benchmark.mjs

  dist/
    gasoline-forecast.html
    diesel-forecast.html
    jet-forecast.html
```

### 13.2 Build sequence

```text
1. Read product registry.
2. Validate source CSV existence for gasoline, diesel, and jet.
3. Record latest source dates, file modification times, and checksums.
4. Normalize weekly EIA data into the long schema.
5. Normalize monthly EIA data into the long schema.
6. Normalize Kpler split data when available.
7. Normalize JODI reference data only where used.
8. Convert normalized data to Parquet cold storage.
9. Build monthly balance tables for each product.
10. Train or refresh monthly component forecasts.
11. Derive weekly EIA forecasts from monthly balance paths.
12. Run monthly-to-weekly reconciliation checks.
13. Run rolling-origin backtests and select model stack.
14. Calibrate uncertainty intervals and scenario fan references.
15. Build compact product-specific hot binary bundles.
16. Validate official adjustments and horizon.
17. Compile Rust core to WASM.
18. Bundle TypeScript and CSS.
19. Bundle selected Plotly partial build.
20. Inline JS, CSS, WASM, and product bundle into each HTML.
21. Smoke-test all three HTML files.
22. Run performance benchmark on all three.
23. Write checksums, model metadata, and build manifest.
```

### 13.3 Version metadata

Every generated HTML must embed:

```text
product
forecast_id
forecast_published_at
build_timestamp
source_git_commit if available
weekly_source_checksum
monthly_source_checksum
kpler_manifest_checksum if available
jodi_manifest_checksum if available
data_bundle_checksum
wasm_checksum
forecast_horizon
official_adjustments_checksum
monthly_balance_checksum
weekly_forecast_checksum
model_selection_checksum
backtest_report_checksum
reconciliation_report_checksum
toolchain_versions
documentation_audit_timestamp
```

### 13.4 Documentation and toolchain audit

Before implementation and before every major rebuild, verify current official
documentation and package versions. Do not rely on stale pinned assumptions.

Required documentation sources:

```text
Vite official release docs and npm package page
TypeScript official release notes
Node.js official release schedule and release notes
Rust stable release channel
wasm-bindgen docs.rs/crates.io release page
Plotly.js npm/package documentation
Apache Arrow JavaScript docs and npm package page
DuckDB-WASM official docs if DuckDB-WASM is enabled
Nixtla/StatsForecast or comparable forecasting docs if Python model training is
used at build time
```

Current audit note as of 2026-05-18:

```text
Use Node LTS for the build baseline, not Node Current, unless a specific build
tool requires Current.
Use TypeScript 6.x behavior deliberately; TypeScript 6.0 changed several
defaults and is intended as a bridge toward TypeScript 7.0.
Use the latest stable Vite release available at implementation time.
Use the latest stable Rust release available at implementation time.
Keep wasm-bindgen crate and CLI versions matched.
Use exact Plotly package versions; do not use CDN "latest" aliases.
Treat DuckDB-WASM as optional because browser memory limits and single-threaded
defaults can matter for large analytical workloads.
```

Every version audit should write:

```text
tool name
resolved version
source URL
audit date
reason for selecting or rejecting the tool
known migration notes
```

Suggested version-resolution commands during implementation:

```text
node --version
npm view vite version
npm view typescript version
npm view plotly.js version
npm view apache-arrow version
npm view @duckdb/duckdb-wasm version
rustc --version
cargo search wasm-bindgen --limit 1
cargo search polars --limit 1
```

Lock exact versions after the audit so a release can be reproduced. Upgrade
deliberately after re-running smoke tests, benchmarks, and reconciliation checks.

---

## 14. Packaging Modes

### 14.1 Default single-file portable mode

Default release:

```text
dist/gasoline-forecast.html
dist/diesel-forecast.html
dist/jet-forecast.html
```

Each HTML embeds:

```text
JavaScript bundle
CSS
Plotly partial bundle
WASM module as compressed/base64 bytes
product hot binary bundle as compressed/base64 bytes
small metadata manifest
```

### 14.2 Optional performance package mode

If single-file HTML becomes too large, also support:

```text
release/
  gasoline-forecast.html
  diesel-forecast.html
  jet-forecast.html
  assets/
    app.wasm
    gasoline.bundle.bin
    diesel.bundle.bin
    jet.bundle.bin
    plotly-cartesian.min.js
```

The default remains single-file unless profiling shows startup time or file size
is unacceptable.

---

## 15. Performance Targets

Initial targets on a normal laptop:

```text
visible shell: under 500 ms when possible
worker ready: under 1.5 s for normal bundle sizes
first summary values: under 2 s
single input recalculation: 16 to 50 ms when possible
visible chart update: next animation frame after worker result
100 chart registry items: no synchronous full-page redraw
scenario fan recalculation: worker-only, progress visible if long
main thread long tasks: avoid tasks above 50 ms
```

Measure with realistic gasoline, diesel, and jet bundles separately.

---

## 16. Optimization Checklist

### 16.1 Calculation optimization

- [ ] Use Rust/WASM for numeric-heavy work.
- [ ] Keep hot data in typed arrays.
- [ ] Use numeric IDs instead of repeated strings in hot loops.
- [ ] Avoid allocations inside hot calculation loops.
- [ ] Use dependency graph dirty recalculation.
- [ ] Send patches, not full state.
- [ ] Cache stable intermediate outputs.
- [ ] Recalculate by affected period range where possible.
- [ ] Precompute static curves at build time.
- [ ] Apply official adjustments once at startup unless Alex changes them.
- [ ] Apply trader adjustments as sparse overlays.
- [ ] Run scenario fans and sensitivity grids in the worker.
- [ ] Train heavyweight forecasting models at build time.
- [ ] Store selected monthly balance forecasts in the hot product bundle.
- [ ] Derive weekly forecasts from monthly paths through audited allocation.
- [ ] Reconcile every weekly forecast back to monthly values.
- [ ] Store model-selection and backtest metadata for the quality panel.

### 16.2 Data optimization

- [ ] Store cold data in Parquet.
- [ ] Normalize CSVs to long schema before bundling.
- [ ] Push projection/filter into Parquet scans at build time.
- [ ] Convert hot columns into typed arrays.
- [ ] Do not decode all source data at startup unless required.
- [ ] Do not query Parquet during every input change.
- [ ] Use Arrow IPC or custom binary for startup-critical data.
- [ ] Use compact period indexes.
- [ ] Split huge datasets by product.
- [ ] Keep gasoline, diesel, and jet bundle schemas identical.
- [ ] Keep monthly balance columns needed for audit even if display bundle is compact.
- [ ] Drop duplicate unit variants from hot data when converted kbd is enough.

### 16.3 Worker optimization

- [ ] Use one calculation worker first.
- [ ] Transfer ArrayBuffers instead of copying.
- [ ] Keep DOM and Plotly off the worker.
- [ ] Use revision numbers to drop stale results.
- [ ] Batch rapid input changes.
- [ ] Add progress messages for long scenario runs.
- [ ] Add cancellation for stale expensive runs.

### 16.4 Chart optimization

- [ ] Initialize visible charts only.
- [ ] Use `Plotly.newPlot` only for first render.
- [ ] Use `restyle`, `relayout`, `update`, `react`, or `extendTraces` appropriately.
- [ ] Use partial Plotly bundles.
- [ ] Use WebGL traces only when profiling supports it.
- [ ] Downsample chart data.
- [ ] Disable animation for calculation-driven updates.
- [ ] Use `requestAnimationFrame` for visible chart flushes.
- [ ] Use idle time for hidden/offscreen chart preparation.
- [ ] Never synchronously update every chart from one input event.

### 16.5 UI optimization

- [ ] Debounce text inputs.
- [ ] Throttle sliders.
- [ ] Update summary values before charts.
- [ ] Use virtualized long tables.
- [ ] Avoid layout thrashing.
- [ ] Avoid repeatedly measuring DOM inside loops.
- [ ] Keep fixed dimensions for toolbars, summary cards, and grid rows.

---

## 17. Required Screens Per Product

### 17.1 Overview

Shows:

```text
latest weekly date
latest monthly date
official forecast total
trader scenario total
scenario delta
key stock/demand/import/export metrics
main official vs scenario chart
monthly-to-weekly reconciliation status
selected model stack
data quality status
```

### 17.2 Balance

Shows:

```text
weekly balance
monthly balance
production
imports
exports
stocks
product supplied/demand where available
implied balance
monthly official forecast path
weekly EIA forecast derived from monthly path
reconciliation difference
calendar alignment notes
```

### 17.3 Flows

Shows:

```text
Kpler import groups
Kpler export groups
domestic PADD route splits when available
EIA aggregate comparison
share calculations
```

### 17.4 Scenario

Shows:

```text
official adjustments
trader runtime adjustments
reset to official
scenario presets
sensitivity heatmap
scenario fan
prediction intervals
model backtest summary
```

### 17.5 Quality

Shows:

```text
source file checksums
latest source dates
missing periods
unit conversions
data freshness
forecast vs realized flags
columns included/excluded
model selection audit
monthly-to-weekly reconciliation report
forecast interval coverage
```

### 17.6 Exports

Exports:

```text
visible chart PNG
visible table CSV
scenario patch CSV
official forecast CSV
trader scenario CSV
build manifest JSON
```

Large runtime analytical data should still avoid JSON, but a small manifest
export is acceptable.

---

## 18. Product-Specific Notes

### 18.1 Gasoline

Use the cleaned gasoline outputs. Gasoline blending components should appear as
the total gasoline blending component series only unless Alex later asks for
subcomponents.

Gasoline balance priority:

```text
monthly finished gasoline/product supplied path
monthly total gasoline blending components only where needed
weekly implied demand/product supplied forecast
PADD import/export split effects on regional balance
stock change and ending stock reconciliation
```

Expected split groups:

```text
PADD 1 imports: Europe, Africa, Middle East, Canada/Other
PADD 2 imports
PADD 3 imports
PADD 4 imports
PADD 5 imports: Asia including India, Other
PADD 3 exports: Africa, Latin America, Other
```

### 18.2 Diesel

Use diesel as the reference structure for distillate-style balances.

Diesel balance priority:

```text
monthly distillate product supplied path
PADD 1 A/B vs PADD 1 C demand approximation
weekly distillate supplied forecast
PADD 3 export and domestic route effects
stock change and ending stock reconciliation
```

Expected split groups:

```text
PADD 1 imports split by available Kpler groups
PADD 1 A/B vs PADD 1 C demand approximation when available
PADD 3 exports by destination group
domestic PADD 3 to PADD 1A/1B, PADD 1C, and PADD 5 when available
```

### 18.3 Jet

Use jet as the reference structure for kerosene-type jet fuel balances.

Jet balance priority:

```text
monthly kerosene-type jet fuel product supplied path
weekly jet supplied forecast
Kero/Jet Kpler import/export split effects
airport/seasonal demand behavior only after Alex approves source inputs
stock change and ending stock reconciliation
```

Expected split groups:

```text
PADD import groups
PADD export groups
Kpler Kero/Jet product splits
domestic PADD routes when available
```

---

## 19. Recommended Runtime Algorithm

```text
BOOT
  load shell
  determine embedded product
  start worker
  instantiate WASM
  load product hot bundle
  load selected monthly balance path
  load monthly-derived weekly EIA forecast path
  load reconciliation diagnostics
  load model selection metadata
  apply official adjustments
  calculate initial official and trader baseline
  render summary
  initialize visible charts

ON_INPUT_CHANGE
  normalize input
  create sparse patch
  debounce or throttle if needed
  enqueue patch
  send patch batch to worker

WORKER_CALC
  apply patch to trader overlay
  mark dirty input nodes
  propagate dirty flags
  calculate dirty nodes only
  prepare changed summary/table/chart buffers
  transfer changed buffers to main thread

MAIN_RESULT
  drop stale revisions
  update summary numbers
  queue visible chart updates
  queue table updates
  leave hidden charts dirty

CHART_FLUSH
  run on requestAnimationFrame
  choose update method per chart
  update only affected visible charts

RESET_TRADER
  clear traderRuntimeAdjustments
  keep base and official layers unchanged
  mark affected nodes dirty
  recalculate active scenario from base + official
  update visible output
```

---

## 20. QA and Acceptance Criteria

The project is complete only when all of these pass:

### 20.1 Artifact checks

- [ ] `dist/gasoline-forecast.html` exists.
- [ ] `dist/diesel-forecast.html` exists.
- [ ] `dist/jet-forecast.html` exists.
- [ ] Each file opens directly in a modern browser.
- [ ] No runtime Python, PowerShell, Rust, Node, or server is required.
- [ ] Each file embeds product-specific metadata and checksums.

### 20.2 Product parity checks

- [ ] Gasoline, diesel, and jet share the same screen structure.
- [ ] Gasoline, diesel, and jet share the same control structure.
- [ ] Gasoline, diesel, and jet share the same chart registry structure.
- [ ] Missing product-specific data renders a clear unavailable state.
- [ ] No Europe-specific frontend pages are included yet.

### 20.3 Calculation checks

- [ ] Official baseline loads first.
- [ ] Trader scenario defaults to official baseline.
- [ ] Trader changes never mutate official values.
- [ ] Reset clears only trader adjustments.
- [ ] Forecast horizon is enforced.
- [ ] Unit conversions to kbd are audited.
- [ ] Weekly and monthly period alignment is validated.
- [ ] Monthly balance is built before weekly forecast outputs.
- [ ] Weekly EIA forecast is derived from the monthly balance path.
- [ ] Weekly forecasts reconcile back to monthly values within tolerance.
- [ ] Balance residuals are visible and audited.
- [ ] Model-selection metadata is present for every forecasted component.
- [ ] Rolling-origin backtest results are available in the quality panel.
- [ ] Prediction interval coverage is measured where intervals are shown.
- [ ] Dirty recalculation updates only dependent nodes.

### 20.4 Performance checks

- [ ] Main thread remains responsive during startup.
- [ ] Heavy scenario and sensitivity runs execute in the worker.
- [ ] ArrayBuffers are transferred for large results.
- [ ] Visible summaries update before charts.
- [ ] Hidden/offscreen charts are deferred.
- [ ] No input change causes a full app redraw.

### 20.5 Data checks

- [ ] Weekly source CSV checksums are recorded.
- [ ] Monthly source CSV checksums are recorded.
- [ ] Latest weekly EIA dates are recorded by product.
- [ ] Latest monthly EIA dates are recorded by product.
- [ ] Stale source warnings render in first viewport and quality panel.
- [ ] Kpler manifest checksum is recorded if Kpler data is included.
- [ ] JODI manifest checksum is recorded if JODI data is included.
- [ ] Large runtime data is not stored as JSON.
- [ ] Source column inventory is available in the quality panel.

### 20.6 Browser smoke tests

Run for all three product files:

```text
open file
confirm shell renders
confirm worker ready state
confirm summary values render
confirm main chart renders nonblank
change one trader adjustment
confirm scenario delta changes
reset to official
confirm scenario delta returns to zero
switch weekly/monthly tabs
export visible table
export scenario patch
```

---

## 21. Implementation Phases

### Phase 1 - Static prototype

```text
create shared source tree
create product registry
build three static HTML shells
load small embedded sample bundles
render overview, balance, scenario, and quality screens
```

### Phase 2 - Data normalization

```text
normalize EIA weekly CSVs
normalize EIA monthly CSVs
add Kpler split normalization
add optional JODI reference normalization
write Parquet cold store
write hot product bundles
```

### Phase 3 - Forecast and balance build engine

```text
classify monthly EIA columns into balance components
build monthly balance tables for gasoline, diesel, and jet
train candidate monthly component forecasts
derive weekly EIA forecasts from monthly paths
run rolling-origin backtests
select official model stack by product/component
write reconciliation and model-selection reports
```

### Phase 4 - Rust/WASM runtime engine

```text
implement period/unit model
implement product balance engine
implement monthly balance runtime reader
implement weekly allocation runtime reader
implement reconciliation diagnostics reader
implement official/trader layers
implement dirty dependency graph
implement sensitivity and scenario fan calculations
expose typed-buffer FFI
```

### Phase 5 - Frontend production UI

```text
build command bar
build summary strip
build chart registry
build virtualized tables
build scenario controls
build monthly balance and weekly forecast views
build reconciliation and model audit views
build data quality panel
build export panel
style all three product apps identically
```

### Phase 6 - Packaging and verification

```text
inline JS/CSS/WASM/product bundle into single-file HTML
write build manifest
run browser smoke tests
run performance benchmarks
verify latest data dates and source freshness warnings
verify monthly-to-weekly reconciliation charts
fix layout across desktop/tablet/mobile
ship three final files
```

---

## 22. What Not To Do

Do not:

```text
build Europe pages in this pass
ship only one product-toggle HTML file
copy/paste three manually maintained apps
use Python, PowerShell, Rust, Node, or a server at user runtime
store large runtime analytical data in JSON
recalculate every output on every input
redraw every chart on every input
use Plotly.newPlot for normal updates
load every source column into the hot runtime bundle
query Parquet on every slider movement
mutate official values from trader actions
ship full Plotly if a partial bundle works
use experimental browser Polars for critical runtime logic
add proxy/VPN/user-agent hiding logic
build weekly forecasts that are not reconciled to monthly balances
hide model errors, stale data, or balance residuals from the quality panel
```

---

## 23. Default Recommendation

Implement the first production version with:

```text
three separate static HTML files
one shared TypeScript UI source tree
one Rust/WASM calculation worker
one build-time monthly balance and forecasting pipeline
Plotly cartesian partial bundle
virtualized tables
Parquet cold source data
custom typed-array hot product bundles
single-file portable packaging
browser smoke tests for all three products
```

The core performance principle is:

```text
latest monthly balance path
  -> derived weekly EIA forecast path
  -> audited reconciliation
  -> embedded official forecast bundle

one input change
  -> sparse patch
  -> dirty dependency walk
  -> Rust recalculates only affected nodes
  -> only changed buffers cross the worker boundary
  -> only dependent visible charts update
```
