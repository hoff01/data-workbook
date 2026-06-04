# Backend Optimization Plan: Balance Dashboards

## Objective

Make the Diesel and Jet balance dashboards faster, more correct, and reliable
enough to run refreshes more often. The key product requirement is that every
dashboard route opens already calculated, with no blank tables, no silent
zeroes from missing source data, and no duplicated calculation logic that can
drift between build-time and browser runtime.

This plan is based on:

- Local inspection of `src/build_balance_dashboards.ts`,
  `src/update_pipeline.ts`, `src/dashboard_update_server.ts`, and
  `src/verify_dashboard_freshness.ts`.
- Two sub-agent audits: one focused on performance, one focused on calculation
  correctness and data-loading risk.
- Current local timing and artifact-size evidence.

## Current Baseline

- `npm run build:balances` currently succeeds and took about `5.52s` wall time
  in the local sandbox.
- Existing pre-test telemetry reports `durationMs=3845`, `maxRssMb=2319.8`,
  `heapUsedMb=2397.9` for the balance dashboard build.
- Current generated artifact sizes:
  - `Diesel_Balance/data/diesel_balance_bundle.json`: about `4.7M`
  - `Diesel_Balance/data/diesel_balance_runtime_base.js`: about `944K`
  - `Diesel_Balance/data/diesel_balance_runtime_weekly.js`: about `3.5M`
  - `Jet_Balance/data/jet_balance_bundle.json`: about `4.6M`
  - `Jet_Balance/data/jet_balance_runtime_weekly.js`: about `3.4M`
- Runtime data is split into base, weekly, and reference chunks, but the build
  still serializes a full bundle plus each runtime chunk.
- `verify_dashboard_freshness.ts` checks freshness, checksums, and lazy chunk
  row counts, but does not yet prove that dashboard cells are semantically
  calculated or that missing sources did not become zero-valued rows.

## Highest-Return Optimizations

### 1. Stop reparsing full JODI CSVs during every dashboard build

`buildJodiContext()` reads full Europe/Africa product CSVs only to calculate the
latest regional context cards. The performance audit found JODI inputs are large
enough to dominate memory churn: roughly 56 MB / 316k rows for diesel context
and 111 MB / 632k rows for jet context.

Plan:

- Add a compact `Jodi_Data/context_summary.json` from `src/jodi_secondary.py`,
  containing only latest-period demand/import/export aggregates, row counts,
  assessed share, and generated metadata.
- Make `buildJodiContext()` read that summary instead of materializing all JODI
  CSV rows.
- Keep a streaming fallback only when the summary is absent.

Expected impact:

- Cuts a large source of object allocation from the balance build.
- Makes `build:balances` less sensitive to JODI data growth.
- Improves the chance that refreshes can run more often without memory spikes.

### 2. Replace silent-zero calculations with a shared calculation engine

The correctness audit found that `num()` and `valueByColumn()` coerce blank,
missing, unavailable, and invalid values to `0`. That makes the workbook look
calculated even when the source coverage is missing. The current Jet PADD 1
split is the concrete risk: the source hub marks the split as missing, but the
regional split path can still emit zero-valued PADD 1C rows.

Plan:

- Extract calculation logic from the HTML generator into importable pure
  modules, starting with regional balance construction and weekly/monthly
  forecast reconciliation.
- Add typed source coverage states: `required`, `optional`, `missing`, and
  `unavailable`.
- Use strict numeric parsing in calculation modules:
  - actual zero remains `0`;
  - blank/missing source values become explicit missing values;
  - validators decide whether a missing value is allowed.
- Apply overrides through the shared calculation path rather than recalculating
  adjusted values only in browser code.

Expected impact:

- Eliminates a major source of incorrect blank/zero cells.
- Gives build, verifier, and runtime one set of formulas.
- Makes "everything opens calculated" testable instead of visual-only.

## Phased Implementation Plan

## Phase 0: Measurement And Guardrails

Purpose: prove every later optimization with numbers and catch calculation
regressions before UI inspection.

Tasks:

- Add a repeatable build profile command that writes JSON to `tmp/perf/`.
- Extend dashboard verification with semantic checks:
  - all generated runtime chunks referenced by the active route are present;
  - monthly, weekly, and crude rows have expected non-empty calculated cells;
  - base PADD rows aggregate to U.S., PADDs 1/2/3, and PADDs 1/3 within a
    defined tolerance;
  - no required source field silently resolves to zero when the source is
    missing.
- Add a small generated runtime manifest per product with row counts,
  first/last periods, chunk hashes, calculation version, and source coverage
  statuses.

Validation:

- `npm run typecheck`
- `npm run validate`
- `npm run data:check`
- `npm run verify:dashboard`
- browser performance trace where localhost binding is allowed:
  - initial load;
  - weekly switch;
  - direct weekly URL;
  - chart sheet;
  - crude sheet.

## Phase 1: Quick Build-Speed Wins

Purpose: reduce current build memory and time without changing formulas.

Tasks:

- Implement `Jodi_Data/context_summary.json` and make dashboard build consume it.
- Precompute normalized CSV header maps once per parsed CSV. Avoid repeated
  `Object.keys(row).find(...)` and header normalization in `valueByColumn()` and
  `hasColumn()`.
- Index seasonal and period rows before loops:
  - weekly actuals by month and week-of-month;
  - monthly regional actuals by region and month;
  - movement rows by definition and month;
  - reconciliation weeks by month.
- Stop writing the full multi-megabyte debug bundle by default after verifier
  coverage is moved to runtime manifests. Keep it behind an environment flag
  such as `BALANCE_WRITE_FULL_BUNDLE=1` if still useful for debugging.
- Precompute `.gz` files for large runtime chunks during build and have
  `dashboard_update_server.ts` serve them when the client accepts gzip.

Targets:

- Reduce build peak RSS by at least 50 percent from the current pre-test
  baseline.
- Reduce `build:balances` wall time materially on warm local data.
- Reduce repeated serialization of the same data.

## Phase 2: Correct Calculation Engine

Purpose: make the calculations authoritative, testable, and eager before the
browser renders.

Tasks:

- Move core types and formulas out of the generated inline script and into
  importable source modules:
  - input normalization;
  - monthly balance forecast;
  - weekly forecast and reconciliation;
  - regional monthly/weekly rollups;
  - movement flows;
  - crude run and outage/capacity calculations;
  - override application.
- Define a calculation output contract that includes values plus coverage:
  `{ value, status, sourceRole, reason }` where needed.
- Decide and encode Jet PADD 1 split behavior:
  - either display only P1 East Coast when no split source exists;
  - or calculate a documented split from available PADD 1 weekly/monthly series;
  - but never emit a split row that is zero only because source data is missing.
- Make weekly allocation explicit:
  - document which fields are true weekly EIA values;
  - document which fields are monthly values allocated to weeks;
  - define how split weeks and partial forecast horizons are weighted.
- Apply all persisted overrides in the backend calculation output, then let the
  browser edit and persist new overrides without owning the only adjusted
  calculation path.

Validation:

- Fixture tests for Diesel and Jet monthly/weekly calculations.
- Fixture test for missing Jet PADD 1 split coverage.
- Fixture test for overrides and forecast-only locking.
- Aggregate reconciliation tests for base regions and derived regions.

## Phase 3: Runtime Loading That Cannot Open Blank

Purpose: keep the page fast while ensuring direct URLs and sheet switches render
only after required data is present.

Tasks:

- Split the weekly chunk into smaller chunks:
  - weekly balance rows and weekly movement flows;
  - weekly crude rows;
  - reference/source data.
- Update bootstrap so a route waits for the chunks required by that route before
  rendering the sheet.
- Fail closed on chunk errors:
  - do not render empty calculated tables;
  - show a clear local-runner or chunk-load failure state;
  - keep prior good table content if this happens during an interaction.
- Add subset hashes so validators can compare runtime chunks to calculation
  manifests without loading the old full bundle.

Validation:

- Direct monthly balance URL opens calculated.
- Direct weekly balance URL opens calculated.
- Direct crude URL opens calculated.
- Chart sheet has calculated data after route load and after sheet switches.
- No blank body rows when a required chunk is present.

## Phase 4: Faster And More Frequent Refresh Pipeline

Purpose: make updates cheap enough to run more often and avoid unnecessary
dashboard rebuilds.

Tasks:

- Add source checksum skip logic:
  - if weekly/monthly/Kpler/JODI/capacity inputs did not change, skip dependent
    rebuild work.
- Add product-scoped builds where possible:
  - changes only affecting Diesel should not regenerate Jet;
  - shared crude or capacity changes still regenerate both.
- Keep existing parallel `update:all` phases, but record step duration summaries
  to a machine-readable run manifest.
- Add server-side status details for skipped steps and build profile deltas.

Validation:

- Weekly-only update skips monthly-only work.
- Monthly-only update skips weekly-only work.
- Unchanged source checksums skip balance rebuild.
- Changed shared source regenerates both products.
- Changed product-specific source regenerates only that product.

## Phase 5: Data Model Upgrade If Needed

Purpose: handle larger data growth if quick wins are not enough.

Tasks:

- Normalize build inputs into compact typed records before dashboard build.
- Evaluate Arrow or compact typed-array runtime assets only after Phase 1 and
  Phase 2 measurements prove JSON chunks remain a bottleneck.
- Keep CSVs as development/source artifacts, not the hot runtime data model.

## Verification Checklist For Completion

A backend optimization implementation should not be considered done until all
items below are proven from current state:

- `npm run build:balances` succeeds.
- `npm run typecheck` succeeds.
- `npm run validate` succeeds.
- `npm run data:check` succeeds.
- `npm run verify:dashboard` succeeds and includes semantic calculation checks.
- Diesel and Jet monthly routes open calculated.
- Diesel and Jet weekly routes open calculated.
- Diesel and Jet crude routes open calculated.
- No required source fields silently resolve to zero because of missing columns
  or missing files.
- Build profile records duration, heap, RSS, and output sizes.
- Browser trace records route load and interaction timings.
- Runtime manifests prove chunk row counts, first/last periods, source
  checksums, and calculation version.

## Recommended Next Implementation Order

1. Add runtime manifest plus semantic verifier extension.
2. Add JODI context summary and switch the dashboard build to use it.
3. Add CSV header maps and seasonal indexes while preserving formulas.
4. Extract calculation modules and typed source coverage.
5. Move override application into the shared calculation path.
6. Split weekly/crude chunks and fail closed on missing route data.
7. Add checksum-based update skipping and product-scoped builds.
