# EIA Weekly Petroleum Retrieval Plan

## Objective

Build an extremely fast data pipeline for the EIA Weekly Petroleum Status Report (WPSR) that retrieves tables 2-9, includes every weekly-data tab/sheet available for those tables, merges the data, removes duplicate columns, filters to observations after 2015, and stores both development CSV outputs and a compact client-side format suitable for a future JavaScript/WebAssembly application.

## Source References

- Main WPSR page: https://www.eia.gov/petroleum/supply/weekly/
- EIA Information Releases host: https://ir.eia.gov/
- WPSR release schedule: https://www.eia.gov/petroleum/supply/weekly/schedule.php
- Current direct WPSR file pattern to verify during implementation:
  - `https://ir.eia.gov/wpsr/table2.csv`
  - `https://ir.eia.gov/wpsr/table3.csv`
  - `https://ir.eia.gov/wpsr/table4.csv`
  - `https://ir.eia.gov/wpsr/table5.csv`
  - `https://ir.eia.gov/wpsr/table5a.csv`
  - `https://ir.eia.gov/wpsr/table6.csv`
  - `https://ir.eia.gov/wpsr/table7.csv`
  - `https://ir.eia.gov/wpsr/table8.csv`
  - `https://ir.eia.gov/wpsr/table9.csv`

## Key Source Constraints

- Use `ir.eia.gov` for automated release-file retrieval, not HTML scraping from `www.eia.gov`, because EIA identifies `ir.eia.gov` as the release-data site for WPSR files.
- Follow HTTP redirects because EIA states that requests for latest release files may be redirected to the correct location.
- Send a descriptive `User-Agent` header even though EIA does not require one.
- Expect release timing around Wednesday after 10:30 a.m. Eastern, with holiday exceptions.
- Treat Table 5A as in scope unless explicitly excluded. It is listed between tables 5 and 6 and contains weekly gasoline/ethanol stock data.

## Performance Position

The fastest practical approach is not browser scraping. Fetch direct CSV/XLS files concurrently, parse them with a streaming or zero-copy-friendly parser, normalize into typed columnar arrays, then persist a compact binary artifact for client use.

Recommended architecture:

- Retrieval: parallel HTTPS GET requests against direct `ir.eia.gov/wpsr/table*.csv` and, when needed, corresponding XLS files for multi-sheet/tab discovery.
- Parsing: prefer CSV for speed and simplicity; use XLS only when a table's weekly data is split across sheets that CSV does not expose.
- Transformation: normalize each table into a long, typed schema early, because EIA table layouts are report-oriented and wide.
- Storage: use Apache Arrow IPC for browser/client-side runtime storage. Arrow is columnar, compact for typed data, and has JavaScript support. Keep CSV only as a development/debug artifact.
- Future WASM: if pure JavaScript parsing is not fast enough, move parsing and normalization to Rust compiled to WASM while keeping the output schema and Arrow IPC stable.

## Proposed Workspace Layout

Create this during implementation:

```text
eia_weekly/
  raw.csv
  clean.csv
  raw.arrow
  clean.arrow
  manifest.json
  cache/
    table2.csv
    table3.csv
    table4.csv
    table5.csv
    table5a.csv
    table6.csv
    table7.csv
    table8.csv
    table9.csv
```

File purposes:

- `raw.csv`: full merged development output after duplicate-column removal and date filtering.
- `clean.csv`: future user-defined subset. Until the subset is defined, generate it with the same schema as `raw.csv` or leave it out with a documented placeholder.
- `raw.arrow`: efficient client-side full merged artifact.
- `clean.arrow`: efficient client-side subset artifact once the subset is defined.
- `manifest.json`: source URLs, release date, week-ending date, content hashes, schema version, row counts, column counts, and generation timestamp.
- `cache/`: optional dev-only source snapshots for debugging and reproducibility.

## Retrieval Plan

1. Fetch the WPSR landing page only for metadata and validation.
2. Extract or verify release metadata:
   - `week_ending`
   - `release_date`
   - `next_release_date`
   - available table links
3. Build a deterministic source manifest for tables:
   - tables 2, 3, 4, 5, 5A, 6, 7, 8, 9
   - CSV URL
   - XLS URL
   - table title
   - expected source host
4. Fetch CSV files concurrently with a small fixed concurrency cap.
5. Follow redirects and record final URLs.
6. Use conditional requests once a cache exists:
   - `If-None-Match` when `ETag` is available
   - `If-Modified-Since` when `Last-Modified` is available
7. Hash each response body with a fast hash for local change detection.
8. Retry transient errors with short exponential backoff, but avoid hammering release endpoints.

## Weekly Tab/Sheet Discovery Plan

1. Start with CSV because it is cheaper to fetch and parse.
2. Fetch XLS files during schema discovery or when a CSV cannot represent all weekly-data sheets.
3. Enumerate all workbook sheet names for tables 2-9 and 5A.
4. Classify sheets as weekly data if they contain:
   - week-ending date columns
   - WPSR table title/number
   - petroleum measure rows
   - weekly units such as thousand barrels, thousand barrels per day, percent utilization, or daily imports
5. Exclude notes-only, metadata-only, and formatting-only sheets.
6. Store sheet inventory in `manifest.json` so later runs can detect EIA layout changes.

## Normalization Plan

Convert report-shaped tables into an analysis-shaped long schema:

```text
week_ending,date
release_date,date
source_table,string
source_sheet,string
section,string
metric,string
product,string
region,string
subregion,string
unit,string
period_type,string
value,float64
source_column,string
source_row_index,uint32
```

Rules:

- Parse date columns as dates, not strings.
- Keep values as numeric types where possible.
- Preserve withheld or missing markers separately if needed:
  - `W` as withheld
  - em dash / blank as missing or not applicable
- Add source lineage columns so merged values can be traced back to the original EIA table/sheet.
- Normalize product and region labels with stable dictionaries rather than ad hoc string edits.

## Merge Plan

1. Normalize each table/sheet independently.
2. Concatenate normalized records rather than performing wide joins whenever possible.
3. If a wide export is required, use stable keys:
   - `week_ending`
   - `source_table`
   - `source_sheet`
   - `section`
   - `metric`
   - `product`
   - `region`
   - `unit`
4. Drop duplicate columns by canonical column name after normalization.
5. For duplicate metrics across tables, do not silently discard rows. Deduplicate only when all key fields and values match exactly.
6. If duplicate metric names have different source tables or contexts, keep both and disambiguate through `source_table` and `source_sheet`.
7. Filter to `week_ending >= 2016-01-01`, which satisfies "only keep data after 2015."

## Storage Plan

Development outputs:

- Write `raw.csv` for inspection and diffability.
- Write `clean.csv` only after the clean subset definition exists.

Client-side outputs:

- Primary format: Apache Arrow IPC file or stream.
- Reason: Arrow is columnar, typed, fast to scan, and supported in JavaScript.
- Compression: evaluate gzip/brotli at the HTTP asset layer first. If Arrow files are still too large, evaluate dictionary encoding and narrower integer/float types before introducing heavier storage engines.
- Avoid SQLite unless the client needs ad hoc SQL queries. For simple time-series filtering and plotting, Arrow arrays are likely faster and smaller.
- Avoid Parquet as the first browser target unless there is a confirmed JS/WASM reader requirement. Parquet is excellent for storage, but Arrow IPC is simpler for direct in-browser columnar use.

## Implementation Options

Fastest initial implementation:

- Node.js fetcher using built-in `fetch`/`undici`.
- CSV parser with streaming support.
- XLS parser only for discovery and edge cases.
- Arrow writer for binary client artifact.

Highest-performance future implementation:

- Rust core compiled to WASM.
- Rust handles CSV/XLS parsing, normalization, dedupe, and Arrow IPC writing.
- JavaScript handles orchestration, cache policy, and UI integration.

Pragmatic recommendation:

- Build the first version in Node.js to validate source formats and schema quickly.
- Keep transformation logic deterministic and covered by fixture tests.
- Port hot paths to Rust/WASM only after measuring actual bottlenecks.

## Validation Plan

1. Confirm all expected source files return successful responses after redirects.
2. Confirm the current WPSR page lists the same table numbers and titles expected by the manifest.
3. Validate parsed row counts and column counts against saved manifest values.
4. Assert that all rows have valid `week_ending` dates.
5. Assert that no retained row has `week_ending < 2016-01-01`.
6. Assert duplicate columns are removed from CSV outputs.
7. Assert exact duplicate normalized records are removed.
8. Snapshot output schema to catch unexpected EIA layout changes.
9. Record source body hashes so a downstream bug can be tied to the exact EIA files used.

## Testing Plan

Create tests around fixed local fixtures before relying on live EIA requests:

- URL manifest generation test.
- CSV parser fixture test for each table.
- XLS sheet inventory test.
- Date parsing test.
- Duplicate-column removal test.
- Duplicate-row handling test.
- post-2015 filter test.
- Arrow round-trip test in JavaScript.
- Performance benchmark with cold cache and warm cache.

## Performance Targets

Initial targets for local development:

- Fetch all table CSVs concurrently in under 2 seconds on a normal broadband connection, excluding EIA/server delays.
- Parse and normalize all tables in under 500 ms after files are local.
- Generate `raw.csv` and `raw.arrow` in under 1 second after normalization.
- Keep client artifact size materially smaller than CSV after compression.

These targets should be treated as benchmark goals, not guarantees, until real source sizes and parser behavior are measured.

## Open Decisions

- Define the exact `clean.csv` subset.
- Decide whether Table 5A is mandatory in the final merged output. Current plan includes it.
- Decide whether the final client needs SQL-like querying. If yes, evaluate DuckDB-WASM or SQLite-WASM against Arrow.
- Decide whether source snapshots in `cache/` should be committed or ignored.
- Decide whether historical backfill should use current rolling WPSR files, EIA API series, archived WPSR files, or a hybrid. Current direct WPSR table files appear optimized for the current weekly release, not necessarily full post-2015 history.

## First Implementation Milestone

1. Create `eia_weekly/`.
2. Implement source manifest for tables 2-9 and 5A.
3. Fetch direct CSV files from `ir.eia.gov` with redirects and descriptive User-Agent.
4. Save source snapshots under `eia_weekly/cache/`.
5. Parse and normalize enough fields to prove the schema.
6. Merge normalized records.
7. Drop duplicate columns and exact duplicate records.
8. Filter to dates after 2015.
9. Write `eia_weekly/raw.csv`.
10. Write `eia_weekly/manifest.json`.
11. Benchmark runtime and identify whether JS is already fast enough or Rust/WASM is justified.
