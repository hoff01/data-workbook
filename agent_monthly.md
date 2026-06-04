# EIA Monthly Petroleum Rewrite Plan

## Objective

Completely replace the slow `monthly_eia_pull.py` workflow with a fast, deterministic EIA monthly petroleum data pipeline that preserves only the useful source knowledge from the current script:

- EIA API v2 endpoint URLs.
- EIA facet/product/region codes.
- Existing high-level merge intent.

The new pipeline must produce development CSV outputs and browser-ready columnar assets that can be used by the static forecast HTML app described in `AGENTS_forecast_static_html.md`.

## Relevant Local Files

- Current script to replace: `monthly_eia_pull.py`
- Forecast app architecture: `AGENTS_forecast_static_html.md`
- Weekly retrieval plan: `agent.md`

## Required Current Script Inputs To Preserve

The current script contains the monthly EIA API route set and facet filters. Preserve these, but do not preserve the pandas/request implementation.

Current endpoint set:

```text
https://api.eia.gov/v2/petroleum/move/pipe/data/
https://api.eia.gov/v2/petroleum/pnp/dwns/data/
https://api.eia.gov/v2/petroleum/pnp/refp/data/
https://api.eia.gov/v2/petroleum/pnp/unc/data/
https://api.eia.gov/v2/petroleum/stoc/ts/data/
https://api.eia.gov/v2/petroleum/move/tb/data/
https://api.eia.gov/v2/petroleum/move/ptb/data/
https://api.eia.gov/v2/petroleum/cons/psup/data/
```

Current key facet codes:

```text
product: EPD0
duoarea: NUS, R10, R1X, R1Y, R1Z, R20, R30, R40, R50
movement duoarea pairs:
  R10-R20, R10-R30, R10-R40, R10-R50
  R1X-R30, R1Y-R30, R1Z-R30
  R20-R10, R20-R30, R20-R40, R20-R50
  R30-R10, R30-R20, R30-R40, R30-R50
  R40-R10, R40-R20, R40-R30, R40-R50
  R50-R10, R50-R20, R50-R30, R50-R40
```

## EIA API Constraints

The EIA API v2 supports:

- REST-style dataset routes ending in `/data`.
- Query parameters such as `frequency`, `data[]`, `facets[...][]`, `start`, `end`, `sort`, `offset`, and `length`.
- JSON by default.
- Pagination with `offset` and `length`.
- Response metadata including `response.total`, `response.dateFormat`, `response.frequency`, and `response.data`.

Important implementation implications:

- Keep `length=5000` because EIA documents 5,000 rows as the JSON page limit.
- Fetch the first page per endpoint to discover `total`, then fetch remaining offsets concurrently.
- Use `frequency=monthly`, `data[]=value`, and `start=2016-01` unless a later start is explicitly requested.
- Sort by `period` deterministically.
- Record API warnings in `manifest.json`.
- Use a descriptive `User-Agent`.

## Architecture Decision

Do not make the browser app retrieve and clean raw EIA API data at runtime by default.

Reason:

- The static forecast app requirement is local-first and should run without Python, Node, Rust, or a server.
- EIA API calls require an API key. Embedding a private key in a client-side page is not acceptable for anything distributed.
- API pagination, dedupe, schema validation, and cleaning are build-time data engineering work, not interactive chart work.

Recommended model:

```text
build-time fetch/clean/benchmark
        ↓
eia_monthly/raw.csv for development
eia_monthly/clean.csv after subset is defined
eia_monthly/raw.parquet for cold client/reference storage
eia_monthly/raw.arrow or typed binary bundle for hot startup
        ↓
static HTML app loads binary assets
        ↓
Rust/WASM + typed arrays handle calculations
```

If live client refresh is later required, add it as an optional advanced mode where the user supplies an API key locally at runtime. Do not hardcode a private API key into released HTML.

## Output Layout

Create this during implementation:

```text
eia_monthly/
  raw.csv
  clean.csv
  raw.parquet
  clean.parquet
  raw.arrow
  clean.arrow
  manifest.json
  benchmark.json
  cache/
    move_pipe.jsonl
    pnp_dwns.jsonl
    pnp_refp.jsonl
    pnp_unc.jsonl
    stoc_ts.jsonl
    move_tb.jsonl
    move_ptb.jsonl
    cons_psup.jsonl
```

File purposes:

- `raw.csv`: full merged monthly development output after cleaning, duplicate handling, and date filtering.
- `clean.csv`: future user-defined subset. Until defined, generate it as a documented placeholder or mirror of selected columns only if Alex approves.
- `raw.parquet`: primary cold/reference artifact for the static app.
- `raw.arrow`: hot browser-readable artifact for fast startup and direct typed-array conversion.
- `manifest.json`: endpoint definitions, query params, facets, response totals, warnings, body hashes, schema version, generated timestamp, row/column counts.
- `benchmark.json`: required runtime benchmark for download, parse, clean, merge, CSV write, Parquet write, Arrow write, JS viability, and Rust/WASM recommendation.
- `cache/`: raw endpoint snapshots in newline-delimited JSON or compact JSON chunks for reproducibility.

## Retrieval Plan

1. Build a static endpoint manifest from the current script's endpoints and facet codes.
2. Validate each endpoint metadata route before pulling data:
   - available frequencies
   - available facets
   - available data columns
3. For each endpoint, request page zero:
   - `frequency=monthly`
   - `data[0]=value`
   - `start=2016-01`
   - `sort[0][column]=period`
   - `sort[0][direction]=asc`
   - `offset=0`
   - `length=5000`
4. Read `response.total`.
5. Schedule remaining offsets concurrently with a conservative per-host concurrency cap.
6. Retry transient HTTP/network failures with bounded exponential backoff.
7. Hash every raw response body.
8. Store raw rows per endpoint in `cache/` only if dev caching is enabled.
9. Preserve response warnings in the manifest.

## Performance Retrieval Strategy

Use JavaScript/TypeScript first for the rewrite because the final application is JavaScript-facing and this lets us benchmark honestly.

Recommended first implementation:

- Node.js 22+ or current LTS with native `fetch`.
- `AbortController` timeouts.
- Fixed concurrency queue.
- Streaming write for cache files.
- No pandas.
- No synchronous per-row logging.
- No repeated wide DataFrame pivots.

Rust/WASM escalation rule:

- If Node.js fetch + parse + normalize + write is fast enough and the browser only consumes prebuilt binary assets, do not port retrieval to Rust.
- If parsing/normalization dominates runtime or client-side filtering requires heavy computation, port the hot transformation path to Rust and expose it to JS through WASM.
- Keep network retrieval in JS unless measured evidence shows another runtime materially improves end-to-end performance.

## Cleaning And Normalization Plan

Normalize monthly records into a long canonical schema first:

```text
period_month,date
period_idx,uint16
source_endpoint,string
series,string
series_description,string
product_code,string
product_name,string
duoarea_code,string
duoarea_name,string
origin_code,string
destination_code,string
unit,string
value,float64
value_status,string
```

Rules:

- Convert EIA `period` values from `YYYY-MM` to a stable month date, preferably first day of month for indexing.
- Keep only records with `period >= 2016-01`.
- Parse numeric values once into `float64`.
- Preserve missing, withheld, or nonnumeric statuses separately from numeric value.
- Normalize region and movement codes into dictionary IDs for browser assets.
- Preserve source endpoint and series code for lineage.
- Avoid wide format as the primary runtime model.

## Merge Plan

Preferred runtime shape:

- Long fact table with dictionary-encoded dimensions.
- Separate dimension tables for series, products, areas, endpoints, and units.
- Typed arrays for `period_idx`, `series_id`, and `value`.

Development CSV shape:

- `raw.csv` can be wide or long, but long is preferred for correctness and smaller duplicate risk.
- If Alex needs wide CSV for inspection, generate it as a secondary `raw_wide.csv`.

Duplicate policy:

- Drop duplicate columns only in wide development exports.
- Drop exact duplicate rows when all canonical key fields and value match.
- Do not drop rows merely because descriptions are similar; disambiguate with endpoint, series, area, product, and movement fields.
- If two series produce identical full value vectors, record that in the manifest before dropping either one.

## Storage Plan For Forecast Static HTML

Follow `AGENTS_forecast_static_html.md`:

- Do not use JSON for analytical runtime data.
- Use Parquet for cold/reference storage.
- Use Arrow IPC or typed binary arrays for hot startup.
- Convert only needed data into typed arrays for WASM calculations.
- Keep JSON limited to small metadata such as manifest and checksums.

Recommended monthly artifacts:

- `raw.parquet`: source-quality reference with full lineage.
- `clean.parquet`: reduced production bundle after the clean subset is defined.
- `raw.arrow`: direct browser ingest/testing artifact.
- Generated typed-array bundle later if the forecast app only needs a small fixed subset.

DuckDB-WASM decision:

- Use DuckDB-WASM only if the browser app needs ad hoc SQL/filtering over Parquet/Arrow.
- If the app only plots known series and feeds the Rust calculation engine, skip DuckDB-WASM and load Arrow/typed arrays directly.

## Benchmark Requirement

Benchmarking is mandatory for both monthly and weekly EIA pipelines.

Add a shared benchmark contract:

```text
pipeline_name
runtime
runtime_version
git_commit
source_count
network_cold_ms
network_warm_ms
parse_ms
normalize_ms
dedupe_ms
merge_ms
csv_write_ms
parquet_write_ms
arrow_write_ms
total_cold_ms
total_warm_ms
raw_csv_bytes
parquet_bytes
arrow_bytes
compressed_bytes
row_count
column_count
series_count
peak_memory_mb
js_fast_enough
rust_wasm_recommended
recommendation_reason
```

Decision threshold:

- JS is acceptable if total warm build time, parse/normalize time, and browser load time meet the target without UI-blocking behavior.
- Rust/WASM is justified if JS transformation or browser startup is measurably slow, memory-heavy, or blocks interaction.
- The recommendation must be based on measured timings, not preference.

Suggested initial targets:

- Monthly warm run after cache: under 2 seconds for parse, normalize, merge, and artifact generation.
- Monthly cold run: dominated by network; should parallelize endpoint/page retrieval and avoid unnecessary serial waits.
- Browser startup for selected clean bundle: under 500 ms for data decode and typed-array handoff.
- Full raw bundle can be slower, but should not be loaded for normal trader/official startup unless needed.

## Replacement Implementation Plan

Phase 1: Discovery and fixtures.

1. Extract endpoint manifest from `monthly_eia_pull.py`.
2. Query EIA metadata for each route.
3. Save small fixed fixture responses for tests.
4. Confirm exact returned fields per endpoint.

Phase 2: Fast JS data puller.

1. Create a TypeScript/Node CLI.
2. Implement concurrent paginated EIA API retrieval.
3. Add response hashing, warning capture, and manifest output.
4. Add local cache mode.
5. Add benchmark timing around every stage.

Phase 3: Normalization and cleaning.

1. Normalize raw rows into canonical long records.
2. Dictionary-encode endpoint, series, product, area, unit, and movement dimensions.
3. Drop exact duplicates.
4. Filter to `period >= 2016-01`.
5. Write `raw.csv` and `manifest.json`.

Phase 4: Browser-ready artifacts.

1. Write `raw.parquet`.
2. Write `raw.arrow`.
3. Measure artifact sizes and load/decode time.
4. Decide whether clean subset should be Arrow, Parquet, typed arrays, or both.

Phase 5: Forecast app integration.

1. Map monthly series IDs into forecast-app data IDs.
2. Generate a minimal clean bundle for the official/trader app.
3. Load clean bundle in a worker.
4. Transfer typed arrays into WASM or worker-owned memory.
5. Keep raw/reference data out of the normal startup path unless required.

Phase 6: Rust/WASM decision.

1. Compare Node/JS benchmark results against target thresholds.
2. Prototype only the measured hot path in Rust if needed.
3. Re-run the same benchmark contract for Rust/WASM.
4. Keep the faster and simpler measured approach.

## Validation Plan

1. Assert every endpoint returns data.
2. Assert every endpoint response frequency is monthly.
3. Assert every row has a valid period.
4. Assert no retained period is before `2016-01`.
5. Assert all numeric values parse or have a recorded nonnumeric status.
6. Assert row counts match EIA `response.total` across paginated pages.
7. Assert exact duplicate rows are removed.
8. Assert duplicate wide columns are removed if a wide CSV is generated.
9. Assert manifest hashes match cached source bodies.
10. Assert Parquet and Arrow artifacts round-trip with identical row counts and numeric checksums.
11. Assert benchmark output exists and includes a JS-vs-Rust/WASM recommendation.

## Open Decisions Before Implementation

- Define the exact clean monthly subset.
- Decide whether monthly `raw.csv` should be long only or also produce `raw_wide.csv`.
- Decide whether EIA API key should come only from environment variables or whether local config fallback is still acceptable.
- Decide whether raw cache files should be committed or gitignored.
- Decide whether final static HTML will embed monthly data directly or ship a performance package with separate binary assets.

## First Implementation Milestone

1. Do not modify `monthly_eia_pull.py` behavior yet.
2. Create the new monthly pipeline beside it.
3. Preserve endpoint URLs and facet codes from the Python file.
4. Generate `eia_monthly/raw.csv`.
5. Generate `eia_monthly/raw.parquet` and `eia_monthly/raw.arrow`.
6. Generate `eia_monthly/manifest.json`.
7. Generate `eia_monthly/benchmark.json`.
8. Report measured JS performance and whether Rust/WASM is justified.
