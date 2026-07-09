# Recreate the US_Balances Monthly Seasonality Chart Pattern for Any Dimension

This guide is intentionally general: apply the same chart architecture to **any** monthly seasonality use case (global portfolios, country sets, product lines, sales regions, etc.), then use the Diesel/Jet section only as a concrete example.

It preserves exact behavior patterns currently used in the US_Balances charts:

- fixed 12-point monthly x-axis
- selectable history-year lines
- statistical band (min/avg/max) from dedicated band years
- optional prior/current/next-year forecast lines
- scenario overlays
- URL-driven state
- tooltips/markers/table/CSV in the same card
- near-viewport lazy hydration

## 1) Core abstraction: “Dimension” instead of “PADD”

Treat every charted entity as `dimensionKey` and only specialize where your dataset requires it.

```ts
type DimensionKey = string;

interface DimensionConfig {
  key: DimensionKey;
  label: string;
  short: string;
  unit: string;
}

interface ChartState {
  frequency: "monthly" | "weekly";
  chartRegion: "all" | DimensionKey;
  metric: string;
  years: number[];
  bandYears: number[];
  priorYear: number;
  currentYear: number;
  nextYear: number;
  ma4?: boolean;
  pw?: boolean;
  bf?: boolean;
  // any extra flags your product requires
}
```

### 1.1 Mandatory generic contracts

```ts
const CHART_METRICS = [
  "balanceKbd",
  "demandKbd",
  "productionKbd",
  "importsKbd",
  "exportsKbd",
  "netReceiptsKbd",
  "stocksKb",
  "daysForwardCover",
  "exPlannedUtilizationPct",
];

const SEASON_YEARS = [2023, 2024, 2025];
const BAND_YEARS = [2019, 2022, 2023, 2024, 2025];

const CHART_ALL_DIMENSION_KEY = "all";
```

`SEASON_YEARS` controls forecast-context lines and default card context.
`BAND_YEARS` controls the envelope calculation only.

## 2) Data model you should use (dimension-first)

Every monthly row must include at least:

```ts
interface MonthlyRow {
  dimension: string;           // e.g. 'us', 'padd1ab', 'EMEA', 'Region A'
  metric: string;              // e.g. 'balanceKbd'
  month: string;               // 'YYYY-MM'
  date: string | Date;         // normalized date
  year: number;
  monthIndex: number;          // 0..11
  scenario: string;            // 'base' | 'actual' | 'forecast' |
                               // any model scenario
  value?: number | null;
  // any source fields your adapters need
}
```

If you currently keep `region` instead of `dimension`, keep that field but map to `dimension` at the chart adapter boundary.

## 3) Generic dimension key definitions (not PADD-specific)

Define your global list and any aggregate rules as config.

```ts
const DIMENSION_META: Record<string, DimensionConfig> = {
  us: { key: "us", label: "U.S.", short: "US", unit: "kb" },
  p123: { key: "p123", label: "PADD 1-3", short: "1-3", unit: "kb" },
  global: { key: "global", label: "Global", short: "Global", unit: "kb" },
  // add all concrete keys you need
};

// Example aggregator config for region-style dims
// Works for global data too: define required members per synthetic aggregate key.
const AGGREGATE_RULES: Record<string, DimensionKey[]> = {
  us: ["northeast", "midwest", "south", "west"],
  p123: ["padd1ab", "padd1c", "padd2", "padd3"],
  global: ["na", "eu", "apac", "latam"],
};

const BASE_DIMENSION_KEYS = ["padd1ab", "padd1c", "padd2", "padd3", "padd4", "padd5"]; // example only
```

For non-PADD contexts, the same keys can be country IDs, sales channels, customer classes, etc. The only requirement is that aggregate formulas are deterministic and explicit.

## 4) Dimension split logic (optional, if your source has composite keys)

The Diesel implementation is a special case of a general pattern: one source key is expanded into two logical dimensions before charting.

```ts
function expandCompositeDimension(rows: MonthlyRow[], sourceKey: string, expandTo: [DimensionKey, DimensionKey], weights: Record<string, number>) {
  return rows.flatMap((row) => {
    if (row.dimension !== sourceKey) return [row];

    const [left, right] = expandTo;
    const leftW = weights[`${sourceKey}->${left}`] ?? 0.5;
    const rightW = weights[`${sourceKey}->${right}`] ?? (1 - leftW);

    const base = Number(row.value ?? 0);
    const make = (dimension: DimensionKey, w: number) => ({
      ...row,
      dimension,
      value: Number.isFinite(base) ? base * w : row.value,
    });

    return [make(left, leftW), make(right, rightW)];
  });
}
```

For generic reuse, keep splitting in a separate adapter function so the chart engine only consumes final dimension rows.

## 5) Aggregate calculation (critical, generalized)

Use a strict aggregate builder with completeness checks:

```ts
function sumIfAllPresent(sourceRows: MonthlyRow[], required: DimensionKey[], metric: string): number | null {
  const vals = required
    .map((k) => sourceRows.find((r) => r.dimension === k && r.metric === metric))
    .map((r) => r?.value)
    .filter((v) => Number.isFinite(v as number)) as number[];

  if (vals.length !== required.length) return null;
  return vals.reduce((a, b) => a + b, 0);
}

function addDimensionAggregates(rows: MonthlyRow[]) {
  const grouped = groupBy(rows, (r) => `${r.metric}|${r.month}`);
  const out = [...rows];

  for (const group of grouped.values()) {
    for (const [aggKey, members] of Object.entries(AGGREGATE_RULES)) {
      const val = sumIfAllPresent(group, members, group[0].metric);
      if (val == null) continue;
      out.push({ ...group[0], dimension: aggKey, value: val });
    }
  }

  return out;
}
```

This is the same idea as `us`, `p123`, `p13` in your dashboard, but now works for any aggregate tree.

## 6) Build monthly chart bundle (algorithm, product-agnostic)

For one metric, one dimension, one card:

```ts
type BundlePoint = { x: number; y: number; monthLabel: string; year: number; value: number };
type YearSeries = { year: number; points: BundlePoint[] };

type ChartBundle = {
  history: YearSeries[];
  bands: { x: number; min: number | null; avg: number | null; max: number | null; span: number | null }[];
  overlays: YearSeries[];
};

function valueByYearSlot(rows: MonthlyRow[], metric: string): Record<number, BundlePoint[]> {
  const out: Record<number, BundlePoint[]> = {};
  for (const row of rows.filter((r) => r.metric === metric)) {
    if (!Number.isFinite(Number(row.value))) continue;
    const arr = out[row.year] ?? (out[row.year] = []);
    arr.push({
      x: row.monthIndex,
      y: Number(row.value),
      monthLabel: monthLabel(row.monthIndex),
      year: row.year,
      value: Number(row.value),
    });
  }
  Object.keys(out).forEach((k) => {
    out[Number(k)] = out[Number(k)].sort((a, b) => a.x - b.x);
  });
  return out;
}

function chartBundleYearPoints(rowsByYear: ReturnType<typeof valueByYearSlot>, year: number): YearSeries {
  return { year, points: rowsByYear[year] ?? [] };
}

function buildBands(rowsByMonth: ReturnType<typeof valueByYearSlot>): ChartBundle["bands"] {
  const pts = Array.from({ length: 12 }, (_, x) => ({ x, vals: [] as number[] }));
  for (const year of BAND_YEARS) {
    const ptsByYear = rowsByMonth[year] || [];
    for (const p of ptsByYear) {
      if (Number.isFinite(p.value)) pts[p.x].vals.push(p.value);
    }
  }

  return pts.map((slot) => {
    const vals = slot.vals.filter((v) => Number.isFinite(v));
    if (!vals.length) return { x: slot.x, min: null, avg: null, max: null, span: null };
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    return { x: slot.x, min, avg, max, span: Math.max(0.25, max - min) };
  });
}

function chartSeriesBundle(rows: MonthlyRow[], metric: string): ChartBundle {
  const selectedRows = rows.filter((r) => r.metric === metric);
  const rowsByYear = valueByYearSlot(selectedRows, metric);
  return {
    history: Object.keys(rowsByYear).map((k) => chartBundleYearPoints(rowsByYear, Number(k))),
    bands: buildBands(rowsByYear),
    overlays: selectedRows.filter((r) => r.scenario !== "base").length
      ? [] // fill with scenario-specific years in your own data model
      : [],
  };
}
```

## 7) Draw engine behavior (monthly path)

The draw order to copy:

1. Band min/max area and avg line
2. Historical lines
3. Current/prior/next-year emphasis
4. Scenario overlays
5. Markers + hover

```ts
function drawSeasonChart(
  svg: SVGElement,
  rows: MonthlyRow[],
  metricKey: string,
  frequency: "monthly" | "weekly",
  dimensionKey = ""
) {
  const filtered = rows.filter((r) => !dimensionKey || r.dimension === dimensionKey);
  const series = chartSeriesBundle(filtered, metricKey);

  // scale = chartScale(...)
  // drawBand(series.bands)
  // drawHistoryLines(series.history)
  // drawOverlays(series.overlays)
  // add hover target circles/lines and tooltip behavior
}
```

## 8) Curve style

Match the non-rigid shape used in the dashboard by using midpoint smoothing with pass-through control points (not a strict step function):

- build midpoint helper points
- produce smooth `d` path through each midpoint
- keep raw monthly point markers visible for tooltips

## 9) Next-year forecast rendering

When enabled:

```ts
if (state.nextYear) {
  const next = chartBundleYearPoints(valueByYearSlot(filtered, metricKey), state.nextYear);
  drawSeries(next, { width: 2, opacity: 0.72, dashArray: "4 4" });
}
```

## 10) URL state: the single source of truth

Keep this pattern so charts are shareable and reproducible.

```ts
function serializeYears(values: number[]) {
  return values.sort((a, b) => a - b).join(",");
}

const defaultState = {
  f: "monthly",
  chr: CHART_ALL_DIMENSION_KEY,
  r: "us",
  m: CHART_METRICS[0],
  y: serializeYears(SEASON_YEARS),
  band: serializeYears(BAND_YEARS),
  ly: "2023",
  cy: "2024",
  ny: "2025",
  ma4: "true",
  pw: "false",
  bf: "false",
};

function readState(search = window.location.search) {
  const params = new URLSearchParams(search);
  return {
    f: params.get("f") ?? defaultState.f,
    chr: params.get("chr") ?? defaultState.chr,
    r: params.get("r") ?? defaultState.r,
    m: params.get("m") ?? defaultState.m,
    y: (params.get("y") ?? defaultState.y).split(",").map(Number),
    band: (params.get("band") ?? defaultState.band).split(",").map(Number),
    ly: Number(params.get("ly") ?? defaultState.ly),
    cy: Number(params.get("cy") ?? defaultState.cy),
    ny: Number(params.get("ny") ?? defaultState.ny),
    ma4: (params.get("ma4") ?? defaultState.ma4) === "true",
    pw: (params.get("pw") ?? defaultState.pw) === "true",
    bf: (params.get("bf") ?? defaultState.bf) === "true",
  };
}

function writeStateUrl(state: ReturnType<typeof readState>) {
  const params = new URLSearchParams(window.location.search);
  params.set("f", state.f);
  params.set("chr", state.chr);
  params.set("r", state.r);
  params.set("m", state.m);
  params.set("y", state.y.join(","));
  params.set("band", state.band.join(","));
  params.set("ly", String(state.ly));
  params.set("cy", String(state.cy));
  params.set("ny", String(state.ny));
  params.set("ma4", String(state.ma4));
  params.set("pw", String(state.pw));
  params.set("bf", String(state.bf));
  history.replaceState({}, "", `?${params.toString()}`);
}
```

## 11) Card DOM shell (reusable)

Use this as your copy/paste base. The same structure works for global dimensions.

```html
<section class="balanceChartCard" data-chart-card data-metric="{{metric}}" data-dimension="{{dimension}}">
  <div class="chartShell">
    <div class="chartHeadingRow">
      <div class="chartTitle">{{metricLabel}} · {{dimensionLabel}}</div>
      <a class="openChartLink" href="{{chartUrl}}" target="_blank" rel="noopener">Open chart</a>
    </div>
    <div class="chartToolbar"></div>
    <div class="seasonChart"></div>
    <div class="chartLegend" data-legend></div>
    <div class="chartNotice" data-notice></div>
    <div class="chartTooltip" data-tooltip hidden>
      <div data-tooltip-title></div>
      <div data-tooltip-body></div>
    </div>
  </div>

  <div class="chartTableWrap">
    <div class="chartTableHeader">Monthly values</div>
    <div class="chartTable"></div>
    <button type="button" data-export-csv>Export CSV</button>
  </div>
</section>
```

## 12) CSS contracts to preserve (important in generic migration)

- `.seasonChart { height: 278px; }`
- `.seasonChart.zoomed { height: 430px; }`
- `.chartGrid` with stable responsive columns/gutters
- `.chartTooltip { position: absolute; pointer-events: none; }`
- `.chartLegend` rows with `.swatch` chips
- `.chartNotice` states for no-data, forecast disabled, etc.
- `.chartTableWrap` scroll and font behavior for long values

## 13) Interaction checklist (dimension-agnostic)

- Dimension selector updates only active card state, rebuilds that card.
- Metric selector updates title and series.
- Multi-year history checkbox/pill controls update line visibility.
- Band-year controls recompute band lines/area.
- Hover: marker + tooltip + year/metric context.
- Click out/blur clears tooltip.
- Open chart in new tab retains the exact same URL state.
- Lazy hydration triggers when card is near viewport.
- Render signature memoization avoids re-render on no-op changes.

## 14) Lazy hydration model

Use a card-level signature check:

```ts
function chartRenderSignature(state: ReturnType<typeof readState>, metric: string, dimension: string, scenarioHash = "") {
  return [
    metric,
    dimension,
    state.f,
    state.chr,
    state.r,
    state.y.join("|"),
    state.band.join("|"),
    state.ly,
    state.cy,
    state.ny,
    state.ma4,
    state.pw,
    state.bf,
    scenarioHash,
  ].join("::");
}

function hydrateBalanceChartCard(card: HTMLElement) {
  const key = card.dataset.chartCard;
  const metric = card.dataset.metric;
  const dimension = card.dataset.dimension;
  const state = readState();
  const signature = chartRenderSignature(state, metric!, dimension!);
  // if signature changed => rerender; else skip
}
```

Use IntersectionObserver to hydrate only near viewport, then detach the observer for that card after rendering.

## 15) Chart table + CSV (must mirror chart dataset)

```ts
function rowsForCard(allRows: MonthlyRow[], metric: string, dimension: string, years: number[]) {
  return allRows
    .filter((r) => r.metric === metric && r.dimension === dimension && years.includes(r.year))
    .sort((a, b) => a.monthIndex - b.monthIndex || a.year - b.year);
}

function chartTableHtml(rows: MonthlyRow[]) {
  // create same order as draw points
  // format null as \u2014
}

function toCsv(rows: MonthlyRow[]) {
  const header = ["dimension", "metric", "year", "month", "value", "scenario"];
  // keep exact order from rowsForCard()
}
```

## 16) Diesel + Jet as concrete examples (not a limit)

### Diesel-style (composite dimension)

- Base dimensions include split keys: `padd1ab`, `padd1c`, `padd2`, `padd3`, `padd4`, `padd5`
- Aggregates `us`, `p123`, `p13` are built from `padd1ab + padd1c` plus other legs.
- No plain `padd1` base row in chart domain.

### Jet-style (non-composite)

- Base dimensions include `padd1`, `padd2`, `padd3`, `padd4`, `padd5`
- Aggregates use standard member lists.

For non-energy/global contexts: treat these as just dimension values and keep the same pipeline.

## 17) Globalizing this to non-energy datasets

1. Replace `region` field names with `dimension` at the chart adapter boundary only.
2. Keep month/year normalization identical.
3. Keep two year-group selectors:
   - `historyYears` (visual lines)
   - `bandYears` (envelope stats)
4. Keep aggregates explicit and deterministic.
5. Keep URL state as canonical contract.
6. Keep hover/tooltip/table/CSV on identical filtered subset.
7. Keep card shell + style class contracts identical and swap labels only.

## 18) Quality checklist before using in another product

- [ ] Dimensions are abstracted (`dimension` key, metadata map)
- [ ] Composite split logic is adapter-local, not chart-core
- [ ] Aggregate rows require complete base members
- [ ] Band min/avg/max uses only `BAND_YEARS`
- [ ] Current/next/projection line semantics preserved
- [ ] URL state is deterministic and shared with `replaceState`
- [ ] Tooltip appears on hover and clears cleanly
- [ ] Table and CSV are derived from exactly the same filtered rows as rendering
- [ ] Chart shell styles match the target height and legend hierarchy
- [ ] Hydration batching is enabled (near viewport / signature cache)
- [ ] `Open chart` URL round-trips full visible chart state

## 19) Copy-paste integration skeleton

Use this as your starting implementation skeleton for any context:

```ts
function buildMonthlySeasonalityCards(rawRows: MonthlyRow[], productName: string, dimensions: string[]) {
  // 1) adapt source rows to dimension rows
  // 2) apply any composite split function if needed
  // 3) append aggregate rows from AGGREGATE_RULES
  // 4) bind card shells and chart controls
  // 5) on each interaction, read state, filter, build bundle, draw chart, render table
  // 6) encode state in URL
}
```

