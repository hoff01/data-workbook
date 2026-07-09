# Reusable Monthly Five-Year Band Chart — Indicia Implementation Specification

## Purpose

Use this document as the implementation contract for recreating the existing monthly five-year-band chart for **any monthly dataset**. The finished chart must retain the visual hierarchy, spacing, colors, line roles, labels, tooltip behavior, and responsive behavior of the Indicia chart in `US Balances/Build dashboard.ts`, while replacing all dataset-specific wording and field names with generic inputs.

The intended request is:

> Recreate the monthly five-year-band chart for this dataset using `docs/guides/monthly-five-year-band.md`. Use the existing `US Balances/Build dashboard.ts` chart as the read-only visual and behavioral source of truth. Make the metric title and region dynamic. Preserve the current-year, previous-year, five-year-average, and five-year-range styling and logic.

---

## Critical source-fidelity rule

`US Balances/Build dashboard.ts` is the **canonical source of truth** for the original chart. It must be read, not edited.

1. Open and inspect `US Balances/Build dashboard.ts` before implementing a new chart.
2. Do **not** update, reformat, rename, refactor, lint-fix, or otherwise modify that file.
3. Do **not** change the charting library, renderer, dependency versions, component structure, or established helper functions merely to modernize the implementation.
4. Copy the original chart's exact constants and behavior where they exist, including colors, opacity, padding, margins, font settings, line widths, dash patterns, point styles, axis formatting, legend placement, tooltip layout, number formatting, breakpoints, and draw order.
5. When this document and `Build dashboard.ts` differ, `Build dashboard.ts` wins.
6. Put the new implementation in the destination project. Never use the source file as a scratchpad.
7. Before and after the work, verify that `US Balances/Build dashboard.ts` has no diff.

Recommended verification when the source project uses Git:

```bash
git diff --exit-code -- "US Balances/Build dashboard.ts"
```

A successful command produces no diff and exits with code `0`.

> Authoring note: the referenced `US Balances` directory and `Build dashboard.ts` were not exposed in the mounted workspace used to write this guide. Therefore, this document cannot truthfully embed the private file's exact hexadecimal colors or pixel values. The source-extraction procedure below is mandatory whenever that file is available. The explicitly labeled portable values are fallbacks only; they must not replace canonical values found in the source.

---

## Required result

Each chart presents one metric for one optional region across the twelve calendar months. It overlays:

- a filled **five-year historical range**, calculated month by month from the minimum and maximum values in the five historical years;
- a **five-year historical average**, calculated month by month from the same five years;
- the **previous calendar year** as the secondary comparison line; and
- the **current/reference year** as the dominant line.

The chart must remain generic. It must not hardcode a product, geography, country, PADD, basin, unit, source, or year.

### Default year window

For a reference year `Y`:

- Current/reference year: `Y`
- Previous year: `Y - 1`
- Five-year historical window: `Y - 5` through `Y - 1`, inclusive
- Five-year average: mean of those five historical values for each month
- Five-year range: minimum and maximum of those five historical values for each month

The previous year is deliberately visible as its own line even though it is also one of the observations used to calculate the five-year range and average. This gives the reader both the most recent comparison and the wider historical context.

When the original `Build dashboard.ts` uses a different window convention, reproduce the original convention exactly.

---

## Generic language rules

### Title

The title describes **what the data is**, not a specific project or location.

```ts
const chartTitle = metricLabel;
```

Examples:

- `Monthly Refinery Utilization`
- `Crude Oil Imports`
- `Distillate Inventories`
- `Natural Gas Production`
- `Installed Refining Capacity`

Do not include a fixed phrase such as `US Balances`, `PADD 1`, or a hardcoded commodity. Do not append the current year to the title because the legend already identifies years.

### Region and unit line

The region is also dynamic. Build the subtitle from the nonempty values supplied by the caller:

```ts
const subtitle = [regionLabel, unitLabel]
  .map((value) => value?.trim())
  .filter((value): value is string => Boolean(value))
  .join(" · ");
```

Examples:

- `United States · kb/d`
- `Region A · million barrels`
- `Global · metric tonnes/month`
- `kb/d` when no region applies
- no subtitle when neither a region nor a unit is provided

Never invent a region. Omit the region cleanly when the data is not regional.

### Legend labels

Legend text must be generated from the resolved year window:

```ts
const legendLabels = {
  current: String(referenceYear),
  previous: String(referenceYear - 1),
  average: `${referenceYear - 5}–${referenceYear - 1} average`,
  range: `${referenceYear - 5}–${referenceYear - 1} range`,
};
```

Use an en dash in year ranges. If the source chart uses `5-year average` and `5-year range` instead of explicit years, keep the source wording.

---

## Data contract

Use TypeScript throughout the chart implementation. Do not move the chart calculation into Python or another language when the destination dashboard is TypeScript.

### Canonical normalized row

Convert every source format into this minimal shape before calculating the chart:

```ts
export interface MonthlyObservation {
  /** A Date or an ISO-like monthly date such as YYYY-MM or YYYY-MM-DD. */
  date: Date | string;

  /** The actual monthly numeric observation. null means missing, not zero. */
  value: number | null;

  /** Optional identifiers used when one input table contains multiple series. */
  metricKey?: string;
  regionKey?: string;

  /** Optional display metadata. */
  metricLabel?: string;
  regionLabel?: string;
  unitLabel?: string;
}
```

### Chart request

```ts
export type DuplicateMonthPolicy = "error" | "sum" | "mean" | "last";
export type HistoricalCompletenessPolicy = "strict-five" | "available";

export interface FiveYearBandChartRequest {
  data: readonly MonthlyObservation[];

  /** Generic display text. */
  metricLabel: string;
  regionLabel?: string;
  unitLabel?: string;
  sourceLabel?: string;

  /** Optional selectors when the input contains multiple metrics or regions. */
  metricKey?: string;
  regionKey?: string;

  /**
   * Prefer an explicit year when the dataset contains forecasts, scenarios,
   * or later years that should not become the current line.
   */
  referenceYear?: number;

  /** Defaults to error because duplicate monthly records are usually a data issue. */
  duplicateMonthPolicy?: DuplicateMonthPolicy;

  /**
   * strict-five: render the historical statistics only when all five values exist.
   * available: calculate from the available historical values and expose sampleSize.
   */
  historicalCompleteness?: HistoricalCompletenessPolicy;

  /** Match the source chart's axis behavior. */
  includeZeroOnYAxis?: boolean;
  targetYTickCount?: number;
  valueDecimals?: number;

  /** Optional canonical style snapshot copied from Build dashboard.ts. */
  tokens?: Partial<FiveYearBandTokens>;
}
```

### Supported source shapes

The normalizer should accept the source project's existing monthly conventions without changing upstream files.

#### Long monthly data

```text
date,value,metric,region,unit
2024-01-15,104.2,series_a,region_a,kb/d
2024-02-15,106.8,series_a,region_a,kb/d
```

#### Wide monthly data

```text
Date,Series A (kb/d),Series B (kb/d)
2024-01-15,104.2,88.7
2024-02-15,106.8,90.1
```

#### Existing pipeline date-column conventions

The local data scripts use monthly fields such as:

- `Date`, commonly normalized to a monthly date such as `YYYY-MM-15`;
- `month`, commonly paired with numeric columns such as `*_kbd`; and
- `period_month`, used by monthly capacity outputs.

Treat these as input aliases. Convert them to `MonthlyObservation`; do not rewrite the upstream pipeline solely for the chart.

### Adapter for a wide table

```ts
export type UnknownRow = Record<string, unknown>;

export function observationsFromWideRows(
  rows: readonly UnknownRow[],
  valueColumn: string,
  options: {
    dateColumn?: string;
    metricLabel?: string;
    regionLabel?: string;
    unitLabel?: string;
  } = {},
): MonthlyObservation[] {
  const dateColumn = options.dateColumn ?? "Date";

  return rows.map((row, index) => {
    const rawDate = row[dateColumn];
    if (!(rawDate instanceof Date) && typeof rawDate !== "string") {
      throw new Error(`Row ${index + 1}: ${dateColumn} is not a valid monthly date.`);
    }

    const rawValue = row[valueColumn];
    const value = rawValue === null || rawValue === undefined || rawValue === ""
      ? null
      : Number(rawValue);

    if (value !== null && !Number.isFinite(value)) {
      throw new Error(`Row ${index + 1}: ${valueColumn} is not numeric.`);
    }

    return {
      date: rawDate,
      value,
      metricLabel: options.metricLabel ?? valueColumn,
      regionLabel: options.regionLabel,
      unitLabel: options.unitLabel,
    };
  });
}
```

### Adapter for a long table

```ts
export function observationsFromLongRows(
  rows: readonly UnknownRow[],
  mapping: {
    dateColumn: string;
    valueColumn: string;
    metricColumn?: string;
    regionColumn?: string;
  },
): MonthlyObservation[] {
  return rows.map((row, index) => {
    const rawDate = row[mapping.dateColumn];
    if (!(rawDate instanceof Date) && typeof rawDate !== "string") {
      throw new Error(`Row ${index + 1}: invalid monthly date.`);
    }

    const rawValue = row[mapping.valueColumn];
    const value = rawValue === null || rawValue === undefined || rawValue === ""
      ? null
      : Number(rawValue);

    if (value !== null && !Number.isFinite(value)) {
      throw new Error(`Row ${index + 1}: invalid numeric value.`);
    }

    return {
      date: rawDate,
      value,
      metricKey: mapping.metricColumn
        ? String(row[mapping.metricColumn] ?? "")
        : undefined,
      regionKey: mapping.regionColumn
        ? String(row[mapping.regionColumn] ?? "")
        : undefined,
    };
  });
}
```

---

## Date handling

Monthly charts must be immune to browser timezone shifts. Do not parse `YYYY-MM` with an ambiguous local-time constructor and do not group by day-of-month.

```ts
export interface YearMonth {
  year: number;
  /** Zero-based: January = 0, December = 11. */
  monthIndex: number;
}

export function parseYearMonth(input: Date | string): YearMonth {
  if (input instanceof Date) {
    if (Number.isNaN(input.getTime())) {
      throw new Error("Invalid Date object.");
    }
    return {
      year: input.getUTCFullYear(),
      monthIndex: input.getUTCMonth(),
    };
  }

  const text = input.trim();
  const match = /^(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?(?:[T\s].*)?$/.exec(text);
  if (!match) {
    throw new Error(`Unsupported monthly date: ${JSON.stringify(input)}`);
  }

  const year = Number(match[1]);
  const monthNumber = Number(match[2]);
  if (!Number.isInteger(year) || monthNumber < 1 || monthNumber > 12) {
    throw new Error(`Invalid monthly date: ${JSON.stringify(input)}`);
  }

  return { year, monthIndex: monthNumber - 1 };
}
```

Rules:

- Group all dates by calendar year and calendar month only.
- `2024-01-01`, `2024-01-15`, and `2024-01-31` all map to January 2024.
- Preserve a real zero as `0`.
- Preserve missing data as `null`.
- Never replace missing values with zero to make a line continuous.
- Never interpolate a missing actual unless the source chart explicitly does so and labels it.

---

## Model returned to the renderer

```ts
export const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const;

export interface FiveYearBandPoint {
  monthIndex: number;
  monthLabel: string;

  current: number | null;
  previous: number | null;

  historicalLow: number | null;
  historicalHigh: number | null;
  historicalAverage: number | null;

  /** Number of historical years contributing to this month. */
  sampleSize: number;
}

export interface FiveYearBandModel {
  title: string;
  subtitle: string;
  sourceLabel?: string;
  unitLabel?: string;

  referenceYear: number;
  previousYear: number;
  historicalYears: readonly number[];

  labels: {
    current: string;
    previous: string;
    average: string;
    range: string;
  };

  points: readonly FiveYearBandPoint[];
}
```

---

## Calculation pipeline

The implementation should read like a small pipeline. Keep data preparation separate from drawing so the calculations can be unit-tested without a browser.

```text
raw rows
  → source-format adapter
  → normalized MonthlyObservation[]
  → metric/region filter
  → date and numeric validation
  → duplicate-month resolution
  → reference-year resolution
  → five-year monthly statistics
  → renderer-ready model
  → canonical Build dashboard.ts renderer/style
```

### Reference TypeScript calculation

```ts
interface NumericBucket {
  values: number[];
}

function aggregateDuplicateValues(
  values: readonly number[],
  policy: DuplicateMonthPolicy,
  key: string,
): number {
  if (values.length === 1) return values[0];

  switch (policy) {
    case "sum":
      return values.reduce((total, value) => total + value, 0);
    case "mean":
      return values.reduce((total, value) => total + value, 0) / values.length;
    case "last":
      return values[values.length - 1];
    case "error":
    default:
      throw new Error(
        `Duplicate monthly observations for ${key}. ` +
        `Choose an explicit aggregation policy instead of silently double-counting.`,
      );
  }
}

function finiteMean(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

export function buildFiveYearBandModel(
  request: FiveYearBandChartRequest,
): FiveYearBandModel {
  const title = request.metricLabel.trim();
  if (!title) throw new Error("metricLabel is required.");

  const selected = request.data.filter((row) => {
    const metricMatches = request.metricKey === undefined
      || row.metricKey === request.metricKey;
    const regionMatches = request.regionKey === undefined
      || row.regionKey === request.regionKey;
    return metricMatches && regionMatches;
  });

  if (selected.length === 0) {
    throw new Error("No monthly observations matched the requested metric and region.");
  }

  const duplicatePolicy = request.duplicateMonthPolicy ?? "error";
  const buckets = new Map<string, NumericBucket>();
  const observedYears = new Set<number>();

  for (const row of selected) {
    const { year, monthIndex } = parseYearMonth(row.date);
    observedYears.add(year);

    if (row.value === null) continue;
    if (!Number.isFinite(row.value)) {
      throw new Error(`Non-finite value at ${year}-${String(monthIndex + 1).padStart(2, "0")}.`);
    }

    const key = `${year}-${monthIndex}`;
    const bucket = buckets.get(key) ?? { values: [] };
    bucket.values.push(row.value);
    buckets.set(key, bucket);
  }

  const years = [...observedYears].sort((a, b) => a - b);
  const referenceYear = request.referenceYear ?? years.at(-1);
  if (referenceYear === undefined) {
    throw new Error("A reference year could not be determined.");
  }
  if (!Number.isInteger(referenceYear)) {
    throw new Error("referenceYear must be an integer calendar year.");
  }

  const previousYear = referenceYear - 1;
  const historicalYears = Array.from(
    { length: 5 },
    (_, index) => referenceYear - 5 + index,
  );

  const valueAt = (year: number, monthIndex: number): number | null => {
    const key = `${year}-${monthIndex}`;
    const bucket = buckets.get(key);
    if (!bucket || bucket.values.length === 0) return null;
    return aggregateDuplicateValues(bucket.values, duplicatePolicy, key);
  };

  const completeness = request.historicalCompleteness ?? "strict-five";

  const points: FiveYearBandPoint[] = MONTH_LABELS.map((monthLabel, monthIndex) => {
    const historicalValues = historicalYears
      .map((year) => valueAt(year, monthIndex))
      .filter((value): value is number => value !== null);

    const hasRequiredHistory = completeness === "available"
      ? historicalValues.length > 0
      : historicalValues.length === historicalYears.length;

    return {
      monthIndex,
      monthLabel,
      current: valueAt(referenceYear, monthIndex),
      previous: valueAt(previousYear, monthIndex),
      historicalLow: hasRequiredHistory
        ? Math.min(...historicalValues)
        : null,
      historicalHigh: hasRequiredHistory
        ? Math.max(...historicalValues)
        : null,
      historicalAverage: hasRequiredHistory
        ? finiteMean(historicalValues)
        : null,
      sampleSize: historicalValues.length,
    };
  });

  const subtitle = [request.regionLabel, request.unitLabel]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value))
    .join(" · ");

  return {
    title,
    subtitle,
    sourceLabel: request.sourceLabel?.trim() || undefined,
    unitLabel: request.unitLabel?.trim() || undefined,
    referenceYear,
    previousYear,
    historicalYears,
    labels: {
      current: String(referenceYear),
      previous: String(previousYear),
      average: `${historicalYears[0]}–${historicalYears.at(-1)} average`,
      range: `${historicalYears[0]}–${historicalYears.at(-1)} range`,
    },
    points,
  };
}
```

### Why `strict-five` is the safe default

A shape labeled as a five-year range should normally contain five observations for every displayed month. Under `strict-five`, a historical month with only four valid values is left blank rather than silently being presented as a five-year statistic.

Use `available` only when the product requirement explicitly permits partial history. In that mode, expose `sampleSize` in the tooltip or a note so the user can see when fewer than five years contributed.

---

## Reference-year selection

The chart must not automatically use the computer's current calendar year. The data may lag, contain archived snapshots, or include forecasts.

Use this priority:

1. An explicit `request.referenceYear` supplied by the calling page.
2. Otherwise, the greatest year found in the selected data.

Supply `referenceYear` explicitly when:

- the table contains future forecasts;
- multiple scenarios extend beyond actuals;
- the latest year is an incomplete accidental upload;
- the dashboard has an "as of" year controlled elsewhere; or
- the canonical source chart uses a project-level reference date.

A partial current year is valid. Plot only the observed current-year months. Do not extend the line through missing future months.

---

## Source-style extraction procedure

Before using any fallback style values, inspect `US Balances/Build dashboard.ts` and record the exact source values in a local token object in the destination project.

Search the file for all code related to:

```text
five year
5 year
range
band
current year
previous year
average
legend
tooltip
chart margin
padding
font
stroke
lineWidth
dash
opacity
grid
axis
tick
format
resize
responsive
```

Also inspect imported constants and helper functions. A value that appears to be absent may live in a shared theme import.

Copy or map each discovered value into this interface:

```ts
export interface FiveYearBandTokens {
  cardBackground: string;
  cardBorder: string;
  cardBorderWidth: number;
  cardRadius: number;
  cardPaddingTop: number;
  cardPaddingRight: number;
  cardPaddingBottom: number;
  cardPaddingLeft: number;

  chartMinHeight: number;
  chartAspectRatio: number;
  plotMarginTop: number;
  plotMarginRight: number;
  plotMarginBottom: number;
  plotMarginLeft: number;

  fontFamily: string;
  titleFontSize: number;
  titleFontWeight: number;
  titleLineHeight: number;
  subtitleFontSize: number;
  subtitleFontWeight: number;
  axisFontSize: number;
  legendFontSize: number;
  tooltipFontSize: number;

  textColor: string;
  mutedTextColor: string;
  axisTextColor: string;
  gridColor: string;
  axisColor: string;

  currentColor: string;
  currentLineWidth: number;
  currentPointRadius: number;

  previousColor: string;
  previousLineWidth: number;
  previousPointRadius: number;

  averageColor: string;
  averageLineWidth: number;
  averageDash: string;

  bandFill: string;
  bandStroke: string;
  bandStrokeWidth: number;

  legendGap: number;
  legendItemGap: number;
  tooltipBackground: string;
  tooltipTextColor: string;
  tooltipBorder: string;
  tooltipRadius: number;
  tooltipPadding: number;

  transitionDurationMs: number;
}
```

### Canonical snapshot comment

Keep a brief comment beside the copied token object so future developers know where the values came from:

```ts
/**
 * Exact visual values transcribed from the read-only chart in:
 * US Balances/Build dashboard.ts
 *
 * Do not "improve" these values independently. The source chart is the
 * Indicia visual standard, and changes should be coordinated across charts.
 */
const INDICIA_FIVE_YEAR_BAND_TOKENS: FiveYearBandTokens = {
  // Exact values copied from the canonical source file.
};
```

Do not label guessed values as canonical.

---

## Portable fallback tokens

Use the following only when the canonical source is genuinely unavailable. They preserve the intended visual-role hierarchy: current year in blue, previous year in green, average in dark neutral, and range in translucent gray.

```ts
export const PORTABLE_FIVE_YEAR_BAND_FALLBACK: FiveYearBandTokens = {
  cardBackground: "#FFFFFF",
  cardBorder: "#E5E7EB",
  cardBorderWidth: 1,
  cardRadius: 8,
  cardPaddingTop: 18,
  cardPaddingRight: 20,
  cardPaddingBottom: 16,
  cardPaddingLeft: 20,

  chartMinHeight: 340,
  chartAspectRatio: 1.85,
  plotMarginTop: 18,
  plotMarginRight: 18,
  plotMarginBottom: 42,
  plotMarginLeft: 60,

  fontFamily: "Inter, Arial, Helvetica, sans-serif",
  titleFontSize: 16,
  titleFontWeight: 700,
  titleLineHeight: 1.25,
  subtitleFontSize: 12,
  subtitleFontWeight: 500,
  axisFontSize: 11,
  legendFontSize: 11,
  tooltipFontSize: 12,

  textColor: "#111827",
  mutedTextColor: "#6B7280",
  axisTextColor: "#4B5563",
  gridColor: "#E5E7EB",
  axisColor: "#9CA3AF",

  currentColor: "#2563EB",
  currentLineWidth: 3,
  currentPointRadius: 2.75,

  previousColor: "#16A34A",
  previousLineWidth: 2.25,
  previousPointRadius: 2.25,

  averageColor: "#111827",
  averageLineWidth: 1.5,
  averageDash: "6 4",

  bandFill: "rgba(148, 163, 184, 0.28)",
  bandStroke: "rgba(100, 116, 139, 0)",
  bandStrokeWidth: 0,

  legendGap: 10,
  legendItemGap: 16,
  tooltipBackground: "#111827",
  tooltipTextColor: "#FFFFFF",
  tooltipBorder: "#111827",
  tooltipRadius: 6,
  tooltipPadding: 10,

  transitionDurationMs: 180,
};
```

Merge only caller-supplied overrides:

```ts
const tokens: FiveYearBandTokens = {
  ...INDICIA_FIVE_YEAR_BAND_TOKENS,
  ...request.tokens,
};
```

When the canonical snapshot is unavailable:

```ts
const tokens: FiveYearBandTokens = {
  ...PORTABLE_FIVE_YEAR_BAND_FALLBACK,
  ...request.tokens,
};
```

Do not scatter raw colors and pixel values through rendering code. All style decisions belong in the token object or in existing canonical theme helpers.

---

## Visual hierarchy and draw order

Render back to front in this exact conceptual order unless the source file proves otherwise:

1. Card background and border
2. Plot background
3. Horizontal grid lines
4. Five-year range fill
5. Optional range outline used by the source
6. Five-year average line
7. Previous-year line
8. Current-year line
9. Current/previous markers, if the source uses markers
10. Axes and tick labels
11. Legend
12. Interaction overlay and tooltip
13. Source or data-status note

This order keeps the band in the background and the current-year line visually dominant. Never draw an opaque band over the lines.

### Role-based colors

Assign style by semantic role, not by a hardcoded year number:

```ts
const seriesStyles = {
  current: {
    stroke: tokens.currentColor,
    width: tokens.currentLineWidth,
  },
  previous: {
    stroke: tokens.previousColor,
    width: tokens.previousLineWidth,
  },
  average: {
    stroke: tokens.averageColor,
    width: tokens.averageLineWidth,
    dash: tokens.averageDash,
  },
  range: {
    fill: tokens.bandFill,
    stroke: tokens.bandStroke,
    width: tokens.bandStrokeWidth,
  },
} as const;
```

The same visual roles must remain intact next year without editing colors. For example, when the reference year advances, the new reference year automatically receives the current-year style.

---

## Layout specification

### Card

- One chart per card.
- Use the same background, border, radius, and shadow as the source dashboard.
- Keep the header aligned to the plot's left edge.
- Do not center the title unless the source does.
- Avoid excessive whitespace between title, subtitle, legend, and plot.
- Preserve the source's card-to-card gap when charts appear in a grid.

### Header

Recommended DOM anatomy:

```html
<section class="five-year-band-card">
  <header class="five-year-band-header">
    <div class="five-year-band-heading">
      <h2 class="five-year-band-title"></h2>
      <p class="five-year-band-subtitle"></p>
    </div>
    <div class="five-year-band-legend"></div>
  </header>
  <div class="five-year-band-plot-wrap">
    <svg class="five-year-band-plot"></svg>
    <div class="five-year-band-tooltip" hidden></div>
  </div>
  <footer class="five-year-band-note"></footer>
</section>
```

When `Build dashboard.ts` uses canvas, a chart component, or another markup pattern, retain that pattern instead of forcing this HTML structure.

### Plot size

- Width must follow the container.
- Height must follow the source breakpoint/aspect-ratio behavior.
- The fallback target is approximately `1.85:1`, with a minimum height near `340px`.
- Use a `ResizeObserver` or the source library's responsive mode.
- Debounce only when the source does; avoid a resize loop caused by measuring and writing the same dimension repeatedly.

### Plot margins

Reserve enough left margin for the longest formatted y-axis label and enough bottom margin for month labels. Do not let January or December clip against the card edge.

The plot coordinate system is:

```ts
const innerWidth = width - tokens.plotMarginLeft - tokens.plotMarginRight;
const innerHeight = height - tokens.plotMarginTop - tokens.plotMarginBottom;
```

Month positions should span the full inner width:

```ts
const xForMonth = (monthIndex: number): number =>
  tokens.plotMarginLeft + (monthIndex / 11) * innerWidth;
```

This produces equal Jan-to-Dec spacing. Do not use elapsed milliseconds on the x-axis for a month-of-year comparison; leap years and different day counts would create unwanted spacing differences.

---

## Axes

### X-axis

- Display `Jan` through `Dec` in calendar order.
- Use exactly twelve month positions even when the current year is partial.
- Keep all labels when the source has room for all twelve.
- At narrow widths, use the source's responsive behavior. A safe fallback is every second month, but never reorder months.
- Do not rotate labels unless the source does.
- The x-axis compares month-of-year, not chronological dates across years.

### Y-axis domain

Compute the domain from every visible numeric element:

```ts
function collectVisibleValues(points: readonly FiveYearBandPoint[]): number[] {
  return points.flatMap((point) => [
    point.current,
    point.previous,
    point.historicalLow,
    point.historicalHigh,
    point.historicalAverage,
  ]).filter((value): value is number => value !== null && Number.isFinite(value));
}
```

Domain rules:

1. Include the band low and high, not only line values.
2. Add the same proportional padding used by the canonical source.
3. Do not force zero unless `includeZeroOnYAxis` or the source design requires it.
4. Support negative values.
5. When every value is identical, create a nonzero domain around that value.
6. Use stable "nice" tick steps so the scale does not look arbitrary.
7. Use one number formatter for axis labels, tooltip rows, and any endpoint labels unless the source intentionally differs.

A portable domain fallback:

```ts
export function paddedDomain(
  values: readonly number[],
  includeZero: boolean,
): [number, number] {
  if (values.length === 0) return [0, 1];

  let minimum = Math.min(...values);
  let maximum = Math.max(...values);

  if (includeZero) {
    minimum = Math.min(0, minimum);
    maximum = Math.max(0, maximum);
  }

  if (minimum === maximum) {
    const base = Math.max(Math.abs(minimum), 1);
    const pad = base * 0.08;
    return [minimum - pad, maximum + pad];
  }

  const pad = (maximum - minimum) * 0.08;
  return [minimum - pad, maximum + pad];
}
```

### Grid

- Prefer subtle horizontal grid lines only.
- Do not let grid lines compete with the average line.
- Use the source's exact grid color, width, and opacity.
- Keep the baseline treatment consistent with the source.

---

## Paths and missing values

A missing month must break a line. It must not connect December to February across an absent January value, and a band must not bridge across a month where its low or high is missing.

Renderer-neutral line segmentation:

```ts
export function contiguousSegments<T>(
  values: readonly T[],
  isValid: (value: T) => boolean,
): T[][] {
  const segments: T[][] = [];
  let active: T[] = [];

  for (const value of values) {
    if (isValid(value)) {
      active.push(value);
    } else if (active.length > 0) {
      segments.push(active);
      active = [];
    }
  }

  if (active.length > 0) segments.push(active);
  return segments;
}
```

For an SVG renderer, create a separate path per contiguous line segment. For the band, trace the upper edge from left to right and the lower edge from right to left, then close the path.

Do not use smoothing that overshoots the historical minimum or maximum. Use the exact source interpolation. When the source is unknown, a straight linear path is safer than a spline.

---

## Legend

Default order:

1. Current year
2. Previous year
3. Five-year average
4. Five-year range

Legend swatches must visually match their marks:

- current: solid thick line in the current-year color;
- previous: solid medium line in the previous-year color;
- average: thin/dashed dark line;
- range: filled gray rectangle or area swatch.

The legend should not imply that the band is another line. Use a filled rectangular swatch for the range.

Keep the legend within the card. Allow it to wrap as complete items on narrow screens. Do not split a swatch from its label.

---

## Tooltip

The tooltip should answer "what happened in this month?" without forcing the reader to decode the chart.

Recommended order:

```text
March
2026                    112.4 kb/d
2025                    108.9 kb/d
2021–2025 average       103.6 kb/d
2021–2025 range         94.1–115.8 kb/d
```

Rules:

- Heading: full month name or the exact source format.
- Use the same series order and colors as the legend.
- Hide a row whose value is missing; do not display `0`, `NaN`, or `undefined` as a substitute.
- Keep a true value of zero visible.
- Display the range as `low–high`.
- Append the unit once per row or in the tooltip heading, matching the source.
- Apply the configured decimal precision consistently.
- Under `available` history, add `n = 4` when fewer than five observations contributed.
- Clamp the tooltip inside the plot/card so it does not clip at January or December.
- Support pointer and keyboard focus when the renderer allows it.

Example formatter:

```ts
export function createValueFormatter(
  decimals: number,
  unitLabel?: string,
): (value: number | null) => string {
  const numberFormatter = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

  return (value) => {
    if (value === null) return "—";
    const formatted = numberFormatter.format(value);
    return unitLabel ? `${formatted} ${unitLabel}` : formatted;
  };
}
```

Use the source formatter when it has magnitude abbreviations, significant-digit rules, or unit-specific formatting.

---

## Current-year emphasis

The current year must be the first thing the eye sees.

- Give it the strongest color contrast.
- Use the thickest line.
- Render it after the average and previous-year lines.
- Use markers only when the canonical source does.
- For a partial year, end the line at the most recent actual month.
- Do not use a dashed current line unless the data is explicitly forecast and the source distinguishes forecasts that way.

The previous year is secondary but still clearly visible. The average is contextual and should not compete with either actual-year line. The range is background context.

---

## Optional actual-versus-forecast behavior

Do not introduce forecast styling unless the data supplies an explicit status field or cutoff. Never infer that every month after the latest actual is a forecast merely because values are present.

When the destination data includes a status such as `actual` or `forecast`, preserve the canonical source's behavior. A safe pattern is:

- current actual: solid current-year line;
- current forecast: same hue with the source's dashed pattern;
- one continuous semantic legend item unless the source uses separate legend entries;
- tooltip labels forecast observations explicitly.

Forecast values should not enter the historical five-year band unless the source definition says they should.

---

## Empty, incomplete, and invalid states

### No selected observations

Show the source dashboard's empty-state component. Fallback text:

```text
No monthly data available for this metric and region.
```

Do not render an empty axis that looks like a valid zero series.

### Fewer than five historical years

Under `strict-five`, leave the band and average absent for months without five values and show a concise note:

```text
Five complete historical years are required for the range and average.
```

The current and previous lines may still render when valid.

### Mixed units

Reject the request or require the caller to select one unit. Never place barrels, percentages, and kb/d on a single y-axis.

### Duplicate months

Default to an error. Use `sum`, `mean`, or `last` only when the metric's aggregation semantics are known.

Examples:

- Monthly flows already expressed as average daily rates: usually do not sum duplicate rows without understanding their dimensions.
- Components intended to form a total: `sum` may be valid.
- Multiple daily-derived monthly estimates of the same observation: `mean` may be valid only if explicitly required.
- Revisions ordered from oldest to newest: `last` may select the latest revision, but ordering must be deterministic.

### Negative values

Support them. Do not clip the range at zero unless the source metric is mathematically constrained and the canonical chart does so.

### Extreme outliers

Do not silently winsorize or truncate. The chart should reflect the supplied data, with data-quality handling performed explicitly upstream.

---

## Accessibility

Match the source dashboard, and at minimum provide:

- a chart-level accessible name containing the metric and optional region;
- semantic title text outside the SVG/canvas;
- line-style differences in addition to color differences;
- adequate text/background contrast;
- keyboard-accessible month inspection when practical;
- a textual summary or accessible table when required by the host application;
- no information communicated solely by band opacity.

Suggested accessible name:

```ts
const ariaLabel = [
  `${model.title} monthly five-year-band chart`,
  model.subtitle,
  `Current year ${model.referenceYear}`,
  `Historical range ${model.historicalYears[0]} to ${model.historicalYears.at(-1)}`,
].filter(Boolean).join(". ");
```

---

## Responsive behavior

Use the exact breakpoints from `Build dashboard.ts`. When they are unavailable, apply these principles:

- Keep all twelve data positions.
- Reduce outer padding before reducing plot readability.
- Allow the legend to wrap.
- Keep the y-axis labels readable.
- At very narrow widths, show alternate x-axis labels rather than rotating every label.
- Keep touch targets large enough to inspect a month.
- Preserve line-width hierarchy; do not make all series equally thin on mobile.
- Recalculate the tooltip boundary after resize.

Do not redraw continuously when the measured width has not changed.

```ts
let previousWidth = -1;
const observer = new ResizeObserver((entries) => {
  const width = Math.round(entries[0]?.contentRect.width ?? 0);
  if (width <= 0 || width === previousWidth) return;
  previousWidth = width;
  render(width);
});
```

Use the source's lifecycle cleanup to disconnect observers and remove event listeners.

---

## Recommended single-file TypeScript structure

When the canonical implementation keeps all dashboard logic in `Build dashboard.ts`, preserve that organizational style in the destination dashboard file. Do not split the chart into a new framework or package solely because this specification separates concepts into sections.

Recommended order inside the destination TypeScript file:

```ts
// 1. Existing imports; do not change the charting library.

// 2. Shared chart types.
//    MonthlyObservation
//    FiveYearBandChartRequest
//    FiveYearBandPoint
//    FiveYearBandModel
//    FiveYearBandTokens

// 3. Canonical Indicia style constants copied from the source.

// 4. Month constants and generic formatters.

// 5. Source-shape adapters.
//    observationsFromWideRows
//    observationsFromLongRows

// 6. Pure data functions.
//    parseYearMonth
//    aggregateDuplicateValues
//    buildFiveYearBandModel
//    paddedDomain / tick helpers

// 7. Renderer helpers that match the source library.
//    scale creation
//    band generation
//    line generation
//    axis construction
//    legend construction
//    tooltip construction

// 8. Public chart builder.
//    buildMonthlyFiveYearBandChart(container, request)

// 9. Existing dashboard composition.
//    Convert each monthly dataset to a request and call the builder.
```

Public API:

```ts
export function buildMonthlyFiveYearBandChart(
  container: HTMLElement,
  request: FiveYearBandChartRequest,
): () => void {
  const model = buildFiveYearBandModel(request);

  // Render with the same library and helper patterns used by the canonical
  // Build dashboard.ts implementation.
  //
  // Return a cleanup function that removes listeners/observers/tooltips.

  return () => {
    // Canonical cleanup.
  };
}
```

The chart builder should be reusable. Dataset-specific code should be limited to selecting columns and filling the request:

```ts
const observations = observationsFromWideRows(monthlyRows, selectedValueColumn, {
  dateColumn: "Date",
  metricLabel: selectedMetricLabel,
  regionLabel: selectedRegionLabel,
  unitLabel: selectedUnitLabel,
});

const destroyChart = buildMonthlyFiveYearBandChart(chartContainer, {
  data: observations,
  metricLabel: selectedMetricLabel,
  regionLabel: selectedRegionLabel,
  unitLabel: selectedUnitLabel,
  referenceYear: selectedReferenceYear,
  historicalCompleteness: "strict-five",
  duplicateMonthPolicy: "error",
});
```

Avoid one-off copies such as `buildCrudeChart`, `buildGasChart`, and `buildPadd1Chart` when the only differences are title, region, unit, and input column.

---

## Renderer mapping checklist

Use the source's actual renderer. The following mapping applies regardless of whether it is SVG, Canvas, D3, Plotly, Chart.js, ECharts, or another library.

| Semantic element | Data | Required visual role |
|---|---|---|
| Historical range | `historicalLow` to `historicalHigh` | translucent neutral area, behind every line |
| Historical average | `historicalAverage` | thin dark/neutral line, usually dashed |
| Previous year | `previous` | secondary comparison color and medium width |
| Current year | `current` | primary accent and greatest width |
| X-axis | `monthLabel` | Jan–Dec, equal month spacing |
| Y-axis | all visible values | shared numeric scale and unit formatter |
| Tooltip | one `FiveYearBandPoint` | current, previous, average, range |

Do not switch libraries when recreating the chart. A library change can alter anti-aliasing, curves, padding, fonts, legend dimensions, tooltip behavior, and responsive sizing even when the nominal colors are identical.

---

## Number-formatting rules

Extract the exact formatter from the source. When none is available, use these defaults:

- Percentages: one decimal and `%`, unless the source uses whole percentages.
- Large whole-number stocks/capacity: grouped thousands with zero or one decimal.
- Rates such as `kb/d`: one decimal unless the data is inherently integral.
- Very small values: enough decimals to avoid displaying meaningful nonzero values as `0`.
- Axis ticks may use compact notation only when the tooltip shows the unambiguous full value.
- Do not put a unit in both every tick and the axis title when that creates clutter; follow the source.

The title should remain unit-free when the subtitle already presents the unit.

---

## Validation and tests

### Pure calculation tests

At minimum, test:

1. **Reference-year selection** — explicit year wins over the latest data year.
2. **Five-year window** — `Y - 5` through `Y - 1` is selected.
3. **Average** — calculated from the correct five values for each month.
4. **Range** — low and high are the minimum and maximum for each month.
5. **Previous line** — exactly `Y - 1`.
6. **Partial current year** — future missing months remain `null`.
7. **Real zeros** — zeros remain visible and enter statistics.
8. **Missing history under strict mode** — band and average are `null`.
9. **Available mode** — statistics use only valid values and expose `sampleSize`.
10. **Duplicate policy** — error, sum, mean, and last behave deterministically.
11. **Timezone safety** — `YYYY-MM-15` and a UTC Date group to the same month.
12. **Metric/region filters** — unrelated series do not enter calculations.
13. **Negative values** — domain and statistics preserve them.
14. **Mixed invalid values** — `NaN` and infinities fail validation.

Example deterministic fixture:

```ts
const fixture: MonthlyObservation[] = [];
for (let year = 2020; year <= 2025; year += 1) {
  for (let monthIndex = 0; monthIndex < 12; monthIndex += 1) {
    fixture.push({
      date: `${year}-${String(monthIndex + 1).padStart(2, "0")}-15`,
      value: year * 100 + monthIndex,
    });
  }
}

const model = buildFiveYearBandModel({
  data: fixture,
  metricLabel: "Test Metric",
  regionLabel: "Test Region",
  unitLabel: "units",
  referenceYear: 2025,
});

// January history is 2020–2024.
console.assert(model.points[0].historicalLow === 202000);
console.assert(model.points[0].historicalHigh === 202400);
console.assert(model.points[0].historicalAverage === 202200);
console.assert(model.points[0].previous === 202400);
console.assert(model.points[0].current === 202500);
```

### Visual regression tests

Compare the recreation with the canonical chart at the same dimensions and with equivalent data.

Check:

- card bounds and radius;
- title and subtitle baseline;
- plot margins;
- Jan and Dec positions;
- y-axis tick count and formatting;
- grid opacity;
- band opacity and outline;
- line colors, widths, caps, joins, and dash pattern;
- legend order, swatches, spacing, and wrapping;
- tooltip typography, padding, row order, and edge clamping;
- desktop and narrow widths;
- partial-current-year endpoint;
- missing-month breaks;
- source note placement.

Do not approve a chart based only on matching colors. Spacing, typography, axes, layering, and interaction are equally part of the template.

### Source immutability test

After implementation:

```bash
git diff --exit-code -- "US Balances/Build dashboard.ts"
```

Also review the complete change list to ensure no file in `US Balances` was modified accidentally.

---

## Acceptance criteria

A recreation is complete only when all of the following are true:

- [ ] `US Balances/Build dashboard.ts` was inspected read-only and remains byte-for-byte or Git-diff unchanged.
- [ ] The destination uses the same rendering library and implementation pattern as the source.
- [ ] The title comes from `metricLabel` and contains no fixed dataset name.
- [ ] The region comes from `regionLabel` and is omitted cleanly when absent.
- [ ] The unit is dynamic and consistently formatted.
- [ ] The reference year is explicit or derived from the selected data, not the system clock.
- [ ] The current year, previous year, five-year average, and five-year range use the correct monthly values.
- [ ] The five-year range is min-to-max for each calendar month.
- [ ] The five-year average uses the same five historical years as the range.
- [ ] Missing values are not converted to zero or silently interpolated.
- [ ] A partial current year ends at the latest valid month.
- [ ] Colors are assigned by role, so the styling advances automatically with the year.
- [ ] Exact source colors, dimensions, typography, opacity, dashes, and spacing were copied when available.
- [ ] The band is behind all lines and does not obscure them.
- [ ] The current-year line is visually dominant.
- [ ] The legend order and swatches match the source.
- [ ] The tooltip displays month, current, previous, average, and range clearly.
- [ ] The y-axis includes all visible range and line values.
- [ ] The chart responds to its container without clipping.
- [ ] Empty, incomplete, duplicate, and invalid data states are handled explicitly.
- [ ] Calculation tests and visual checks pass.

---

## Ready-to-paste implementation instruction

Use the following wording in another project:

```text
Recreate the Indicia monthly five-year-band chart for the supplied monthly data.
Follow `docs/guides/monthly-five-year-band.md` as the implementation contract.

Before writing code, read US Balances/Build dashboard.ts as the canonical,
read-only source. Do not edit, reformat, refactor, or update that file or any
file in the US Balances folder. Use the same language, charting library,
renderer structure, helpers, colors, typography, spacing, margins, opacity,
line widths, dash patterns, axes, legend, tooltip, responsiveness, and draw
order found there. Copy exact source values rather than approximating them.

Make the chart generic:
- title = the supplied metric label;
- region = the supplied region label, omitted when absent;
- unit = the supplied unit label;
- no hardcoded commodity, geography, project name, or year.

Normalize the data to monthly { date, value } observations. Resolve the
reference year from an explicit input or, otherwise, the latest selected data
year. Plot the reference/current year and previous year. Calculate the
five-year monthly range and average from referenceYear - 5 through
referenceYear - 1. Preserve real zeros, keep missing values null, break paths
at missing months, and do not extend a partial current year into future months.
Default to requiring all five historical observations for each month's band.

Keep the calculation separate from rendering and make one reusable TypeScript
builder that accepts metricLabel, regionLabel, unitLabel, referenceYear, and
monthly observations. Use semantic style roles so the current-year and
previous-year colors advance automatically when the year changes.

After implementation, prove that US Balances/Build dashboard.ts and the rest
of the US Balances folder are unchanged. Validate the calculations and compare
the new chart visually with the canonical chart at desktop and narrow widths.
```

---

## Final implementation principle

This chart is not merely a gray band plus three lines. The reusable template consists of the complete contract: monthly alignment, year-window semantics, missing-data behavior, source-derived style tokens, visual hierarchy, chart geometry, typography, number formatting, legend, tooltip, responsiveness, accessibility, and source immutability. Recreate all of those together so every monthly dataset produces an unmistakably consistent Indicia five-year-band chart.
