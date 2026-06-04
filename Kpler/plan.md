# Kpler Pull Plan

## Objective

Build a Kpler liquids flows pull inside `Kpler/` that creates daily source datasets and balance-ready weekly and monthly outputs for clean products. The pipeline must support U.S. and Europe external trade flows, plus a separate U.S. PADD domestic movement view. Outputs should be stable, reproducible, and directly usable in balance workbooks without manual reshaping.

The pull should start on `2018-01-01`, use daily granularity, use `KBD`, include forecast/predictive data, and redownload the full history each run unless a later implementation explicitly adds a validated cache layer.

## Documentation Basis

Context7 was attempted first, but it did not resolve Kpler correctly and returned Kepler/astronomy packages instead. The implementation should use Kpler's official Python SDK documentation as the fallback source.

Primary SDK resource:

- Kpler Python SDK `Flows` endpoint, documented as version `1.0.64`.
- Endpoint method:

```python
get(
    flow_direction=None,
    split=None,
    granularity=None,
    start_date=None,
    end_date=None,
    from_installations=None,
    to_installations=None,
    from_zones=None,
    to_zones=None,
    products=None,
    only_realized=None,
    unit=None,
    with_intra_country=None,
    with_intra_region=None,
    with_forecast=None,
    with_freight_view=False,
    vessel_types=None,
    vessel_types_alt=None,
    with_product_estimation=False,
    snapshot_date=None,
)
```

Relevant SDK enum values from the docs:

- `FlowsDirection.Export = "export"`
- `FlowsDirection.Import = "import"`
- `FlowsDirection.NetExport = "netexport"`
- `FlowsDirection.NetImport = "netimport"`
- `FlowsPeriod.Daily = "daily"`
- `FlowsPeriod.Weekly = "weekly"`
- `FlowsPeriod.EiaWeekly = "eia-weekly"`
- `FlowsPeriod.Monthly = "monthly"`
- `FlowsMeasurementUnit.KBD = "kbd"`
- `FlowsSplit.Products = "products"`
- `FlowsSplit.OriginCountries = "origin countries"`
- `FlowsSplit.DestinationCountries = "destination countries"`
- `FlowsSplit.OriginPadds = "origin padds"`
- `FlowsSplit.DestinationPadds = "destination padds"`
- `FlowsSplit.OriginTradingRegions = "origin trading regions"`
- `FlowsSplit.DestinationTradingRegions = "destination trading regions"`
- `FlowsSplit.Total = "total"`

Implementation update: use direct HTTPS requests to `https://api.kpler.com/v1/flows` rather than instantiating the Kpler Python SDK client. The SDK documentation and local SDK source are still useful for confirming request parameters, authentication, and response format. The direct implementation mirrors the SDK's Basic Auth and semicolon-delimited CSV response handling while avoiding the SDK runtime layer.

Use Polars for parsing and transformations. Pandas is not required for this pipeline.

## Target Folder Structure

Create this structure under `Kpler/`:

```text
Kpler/
  plan.md
  README.md
  config/
    products.yml
    regions.yml
    pull_sets.yml
    output_schema.yml
  raw/
    daily/
      external/
      domestic_padd/
  output/
    daily/
    weekly/
    monthly/
  archive/
  logs/
  manifest.json
```

Implementation files should live under `src/` unless a future refactor moves all pipeline code into package folders. Proposed files:

```text
src/kpler_pull.py
src/kpler_config.py
src/kpler_transform.py
src/kpler_validate.py
```

## Authentication And Runtime Configuration

Use environment variables for credentials. Do not commit credentials.

Required:

- `KPLER_EMAIL` or SDK-supported username variable.
- `KPLER_PASSWORD` or SDK-supported password variable.
- If Kpler supports API tokens in the installed SDK version, prefer `KPLER_API_KEY` or the SDK's documented token variable.

Optional:

- `KPLER_START_DATE`, default `2018-01-01`.
- `KPLER_END_DATE`, default current date unless the SDK accepts `None` for latest.
- `KPLER_SNAPSHOT_DATE`, default unset.
- `KPLER_WITH_FORECAST`, default `true`.
- `KPLER_ONLY_REALIZED`, default `false`.
- `KPLER_CONCURRENCY`, default conservative, such as `2`.
- `KPLER_RETRY_COUNT`, default `3`.
- `KPLER_RETRY_BACKOFF_SECONDS`, default `10`.
- `KPLER_FORWARD_DAYS`, default `45`; used when `KPLER_END_DATE` is unset.
- `KPLER_VERIFY_TLS`, default `true`.

The runtime should write a `manifest.json` containing:

- SDK version.
- Generated timestamp.
- Start and end date.
- Snapshot date, if used.
- All Kpler method arguments for each pull.
- Row counts by pull set.
- Min and max daily dates by output.
- Validation checks.
- Any zero-filled date counts.

## Core Kpler Parameters

All standard external trade pull sets should use:

```python
granularity=[FlowsPeriod.Daily]
unit=[FlowsMeasurementUnit.KBD]
with_forecast=True
only_realized=False
with_intra_country=False
with_intra_region=True
with_freight_view=False
with_product_estimation=False
start_date=date(2018, 1, 1)
```

Important notes:

- `with_forecast=True` is the Kpler equivalent of predictive/on.
- `with_intra_country=False` is required for external imports and exports.
- Keep `with_intra_region=True` unless testing shows it suppresses required region-level movements. The Kpler default for flows is documented as true, and the balance use case needs complete region-to-region totals.
- Use daily pulls only. Weekly and monthly outputs should be computed locally from daily data so missing dates can be zero-filled before averaging.

Domestic PADD movement pull sets should use:

```python
granularity=[FlowsPeriod.Daily]
unit=[FlowsMeasurementUnit.KBD]
with_forecast=True
only_realized=False
with_intra_country=True
with_intra_region=True
with_freight_view=False
with_product_estimation=False
start_date=date(2018, 1, 1)
```

## Product Mapping

Use these Kpler product names:

| Balance Commodity | Kpler Product |
| --- | --- |
| Diesel | `Gasoil/Diesel` |
| Jet | `Kero/Jet` |
| Gasoline | `Light Ends` |

All output headings should use balance names: `diesel`, `jet`, `gasoline`. Keep Kpler product names in metadata and raw files.

If Kpler product hierarchy returns multiple child products under `Light Ends`, `Gasoil/Diesel`, or `Kero/Jet`, the first implementation should request the parent product exactly as above. Add a validation report showing returned product values so product drift is visible.

## Required Output Families

There are two major families:

1. External import/export flows:
   - U.S. products with `with_intra_country=False`.
   - Europe products with `with_intra_country=False`.
2. U.S. domestic PADD movements:
   - PADD 3 to PADD 1A plus PADD 1B.
   - PADD 3 to PADD 1C.
   - PADD 3 to PADD 5.
   - All products.
   - `with_intra_country=True`.

Each product/family should produce:

- One cleaned daily dataset.
- One Friday-ending 7-day average weekly dataset.
- One monthly average dataset.

Daily is the source of truth. Weekly and monthly are calculated from daily after date completion and zero filling.

## External U.S. Pull Sets

Create one pull set per product and flow direction for the United States. The final product-level output should merge imports and exports into one file per product.

### US Diesel

Kpler product: `Gasoil/Diesel`

Pulls:

- `us_diesel_imports`
- `us_diesel_exports`

Suggested Kpler calls:

```python
flows.get(
    flow_direction=[FlowsDirection.Import],
    split=[
        FlowsSplit.OriginCountries,
        FlowsSplit.OriginTradingRegions,
        FlowsSplit.Products,
    ],
    granularity=[FlowsPeriod.Daily],
    start_date=START_DATE,
    end_date=END_DATE,
    to_zones=["United States"],
    products=["Gasoil/Diesel"],
    only_realized=False,
    unit=[FlowsMeasurementUnit.KBD],
    with_intra_country=False,
    with_intra_region=True,
    with_forecast=True,
)
```

```python
flows.get(
    flow_direction=[FlowsDirection.Export],
    split=[
        FlowsSplit.DestinationCountries,
        FlowsSplit.DestinationTradingRegions,
        FlowsSplit.Products,
    ],
    granularity=[FlowsPeriod.Daily],
    start_date=START_DATE,
    end_date=END_DATE,
    from_zones=["United States"],
    products=["Gasoil/Diesel"],
    only_realized=False,
    unit=[FlowsMeasurementUnit.KBD],
    with_intra_country=False,
    with_intra_region=True,
    with_forecast=True,
)
```

Outputs:

- `Kpler/output/daily/us_diesel_daily.csv`
- `Kpler/output/weekly/us_diesel_weekly.csv`
- `Kpler/output/monthly/us_diesel_monthly.csv`

### US Jet

Kpler product: `Kero/Jet`

Pulls:

- `us_jet_imports`
- `us_jet_exports`

Outputs:

- `Kpler/output/daily/us_jet_daily.csv`
- `Kpler/output/weekly/us_jet_weekly.csv`
- `Kpler/output/monthly/us_jet_monthly.csv`

### US Gasoline

Kpler product: `Light Ends`

Pulls:

- `us_gasoline_imports`
- `us_gasoline_exports`

Outputs:

- `Kpler/output/daily/us_gasoline_daily.csv`
- `Kpler/output/weekly/us_gasoline_weekly.csv`
- `Kpler/output/monthly/us_gasoline_monthly.csv`

## U.S. Import And Export Grouping

For all U.S. products, split imports and exports by the same high-level groups used in balance work. The plan should make these groups explicit in `Kpler/config/regions.yml`.

Recommended default groups:

### U.S. Import Origin Groups

| Group | Countries/Regions |
| --- | --- |
| Canada | `Canada` |
| Latin America | Mexico, Central America, Caribbean, South America |
| Europe | Europe countries and European trading regions |
| Asia | Asia, including India where Kpler splits it |
| Middle East | Middle East/Gulf origin countries |
| Africa | Africa countries |
| Other | Anything not mapped above |

### U.S. Export Destination Groups

| Group | Countries/Regions |
| --- | --- |
| Canada | `Canada` |
| Latin America | Mexico, Central America, Caribbean, South America |
| Europe | Europe countries and European trading regions |
| Asia | Asia, including India where Kpler splits it |
| Middle East | Middle East/Gulf destination countries |
| Africa | Africa countries |
| Other | Anything not mapped above |

The final U.S. output columns should include both total imports/exports and grouped columns:

```text
date
commodity
imports_total_kbd
imports_canada_kbd
imports_latin_america_kbd
imports_europe_kbd
imports_asia_kbd
imports_middle_east_kbd
imports_africa_kbd
imports_other_kbd
exports_total_kbd
exports_canada_kbd
exports_latin_america_kbd
exports_europe_kbd
exports_asia_kbd
exports_middle_east_kbd
exports_africa_kbd
exports_other_kbd
net_imports_kbd
net_exports_kbd
```

`net_imports_kbd = imports_total_kbd - exports_total_kbd`.

`net_exports_kbd = exports_total_kbd - imports_total_kbd`.

Keep both net columns because some balance sheets prefer import-positive and some export-positive signs.

## External Europe Pull Sets

Europe should be split into `NWE`, `MED`, and `Other Europe` by country lists. The best implementation is to query Kpler by country zones, not by one broad Europe zone, because the region definitions need to be explicit and auditable.

Create product-level outputs for:

- `europe_diesel`
- `europe_jet`
- `europe_gasoline`

Each product should include import and export flows for every region detail:

- `NWE`
- `MED`
- `Other Europe`

Recommended Kpler calls should loop over region/country groups:

```python
flows.get(
    flow_direction=[FlowsDirection.Import],
    split=[
        FlowsSplit.OriginCountries,
        FlowsSplit.OriginTradingRegions,
        FlowsSplit.Products,
    ],
    granularity=[FlowsPeriod.Daily],
    start_date=START_DATE,
    end_date=END_DATE,
    to_zones=NWE_COUNTRIES,
    products=[PRODUCT],
    only_realized=False,
    unit=[FlowsMeasurementUnit.KBD],
    with_intra_country=False,
    with_intra_region=True,
    with_forecast=True,
)
```

```python
flows.get(
    flow_direction=[FlowsDirection.Export],
    split=[
        FlowsSplit.DestinationCountries,
        FlowsSplit.DestinationTradingRegions,
        FlowsSplit.Products,
    ],
    granularity=[FlowsPeriod.Daily],
    start_date=START_DATE,
    end_date=END_DATE,
    from_zones=NWE_COUNTRIES,
    products=[PRODUCT],
    only_realized=False,
    unit=[FlowsMeasurementUnit.KBD],
    with_intra_country=False,
    with_intra_region=True,
    with_forecast=True,
)
```

Repeat for `MED_COUNTRIES` and `OTHER_EUROPE_COUNTRIES`.

### Europe Country Lists

Use Kpler country names exactly. Validate these names with a metadata/discovery call or one small test query before the full pull.

#### NWE

```text
Austria
Belgium
Czechia
Denmark
Estonia
Finland
France
Germany
Iceland
Ireland
Latvia
Lithuania
Luxembourg
Netherlands
Norway
Poland
Slovakia
Sweden
Switzerland
United Kingdom
```

#### MED

```text
Albania
Bulgaria
Croatia
Cyprus
Greece
Italy
Malta
Montenegro
North Macedonia
Portugal
Romania
Serbia
Slovenia
Spain
Turkey
```

#### Other Europe

```text
Armenia
Azerbaijan
Belarus
Bosnia and Herzegovina
Georgia
Hungary
Moldova
Russia
Ukraine
```

Notes:

- Hungary can be treated as `Other Europe` to match the existing JODI-style split used in this repo. If balance conventions treat Hungary as NWE/Central Europe, adjust in `regions.yml`.
- Russia should remain explicit because sanctions and product-flow interpretation may require review.
- Turkey is placed in `MED` for Mediterranean refined-products balances.
- The region file should support comments and overrides so this can be changed without editing code.

### Europe Output Columns

Each Europe product output should include region detail columns:

```text
date
commodity
nwe_imports_total_kbd
nwe_exports_total_kbd
nwe_net_imports_kbd
nwe_net_exports_kbd
med_imports_total_kbd
med_exports_total_kbd
med_net_imports_kbd
med_net_exports_kbd
other_europe_imports_total_kbd
other_europe_exports_total_kbd
other_europe_net_imports_kbd
other_europe_net_exports_kbd
europe_imports_total_kbd
europe_exports_total_kbd
europe_net_imports_kbd
europe_net_exports_kbd
```

Outputs:

- `Kpler/output/daily/europe_diesel_daily.csv`
- `Kpler/output/weekly/europe_diesel_weekly.csv`
- `Kpler/output/monthly/europe_diesel_monthly.csv`
- `Kpler/output/daily/europe_jet_daily.csv`
- `Kpler/output/weekly/europe_jet_weekly.csv`
- `Kpler/output/monthly/europe_jet_monthly.csv`
- `Kpler/output/daily/europe_gasoline_daily.csv`
- `Kpler/output/weekly/europe_gasoline_weekly.csv`
- `Kpler/output/monthly/europe_gasoline_monthly.csv`

## Domestic U.S. PADD Movement Pull Sets

Create a separate domestic family using `with_intra_country=True`.

Required routes:

- PADD 3 to PADD 1A plus PADD 1B.
- PADD 3 to PADD 1C.
- PADD 3 to PADD 5.

Products:

- Diesel: `Gasoil/Diesel`
- Jet: `Kero/Jet`
- Gasoline: `Light Ends`

Preferred route strategy:

1. Use Kpler PADD split fields if the SDK returns them reliably:
   - `split=[FlowsSplit.OriginPadds, FlowsSplit.DestinationPadds, FlowsSplit.Products]`
   - Filter after retrieval to origin `PADD 3` and the requested destination PADDs.
2. If Kpler allows PADD names directly in `from_zones` and `to_zones`, use targeted calls:
   - `from_zones=["PADD 3"]`
   - `to_zones=["PADD 1A", "PADD 1B"]`
   - Repeat for `PADD 1C` and `PADD 5`.
3. Validate exact Kpler names before full production:
   - `PADD 1A` versus `PADD 1 A`
   - `PADD 1B` versus `PADD 1 B`
   - `PADD 1C` versus `PADD 1 C`
   - `PADD 3`
   - `PADD 5`

Suggested broad pull:

```python
flows.get(
    flow_direction=[FlowsDirection.Export],
    split=[
        FlowsSplit.OriginPadds,
        FlowsSplit.DestinationPadds,
        FlowsSplit.Products,
    ],
    granularity=[FlowsPeriod.Daily],
    start_date=START_DATE,
    end_date=END_DATE,
    from_zones=["United States"],
    to_zones=["United States"],
    products=["Gasoil/Diesel", "Kero/Jet", "Light Ends"],
    only_realized=False,
    unit=[FlowsMeasurementUnit.KBD],
    with_intra_country=True,
    with_intra_region=True,
    with_forecast=True,
)
```

Then filter to:

```text
origin_padd == "PADD 3"
destination_padd in ["PADD 1A", "PADD 1B", "PADD 1C", "PADD 5"]
```

Domestic output columns:

```text
date
commodity
padd3_to_padd1ab_kbd
padd3_to_padd1c_kbd
padd3_to_padd5_kbd
padd3_total_selected_kbd
```

Outputs:

- `Kpler/output/daily/us_padd_movements_daily.csv`
- `Kpler/output/weekly/us_padd_movements_weekly.csv`
- `Kpler/output/monthly/us_padd_movements_monthly.csv`

If balance users need one file per commodity instead, also produce:

- `Kpler/output/weekly/us_diesel_padd_movements_weekly.csv`
- `Kpler/output/monthly/us_diesel_padd_movements_monthly.csv`
- `Kpler/output/weekly/us_jet_padd_movements_weekly.csv`
- `Kpler/output/monthly/us_jet_padd_movements_monthly.csv`
- `Kpler/output/weekly/us_gasoline_padd_movements_weekly.csv`
- `Kpler/output/monthly/us_gasoline_padd_movements_monthly.csv`

## Daily Normalization Schema

Every raw Kpler response should be normalized into long-form daily rows before pivoting.

Canonical daily long schema:

```text
date
pull_set
family
geography
commodity
kpler_product
flow_direction
origin_country
destination_country
origin_trading_region
destination_trading_region
origin_padd
destination_padd
region_detail
balance_group
route_group
unit
value_kbd
with_intra_country
with_intra_region
with_forecast
only_realized
snapshot_date
source_hash
```

Rules:

- `date` is daily and timezone-free.
- `value_kbd` is numeric.
- Missing values from Kpler should be treated as null in raw-normalized files, then zero-filled only in balance-ready daily/weekly/monthly files.
- Keep `kpler_product` separate from balance `commodity`.
- Preserve Kpler split columns even if an output only uses totals.

## Daily Completion And Zero Fill

Before weekly or monthly aggregation, complete the date index for every output series.

For each output file:

1. Determine `start_date = 2018-01-01`.
2. Determine `end_date`:
   - Default to today, or the latest date returned by Kpler if the SDK returns future forecast dates.
   - If forecast dates are included beyond today, keep them and record max date in manifest.
3. Build a full daily calendar from start to end.
4. For every expected output column, left join observed Kpler data onto the calendar.
5. Fill missing numeric flow values with `0.0`.
6. Add optional QA columns only in a separate QA file, not in clean balance outputs:
   - `observed_days`
   - `filled_zero_days`
   - `source_row_count`

This is required so monthly averages represent full-month KBD averages, not averages over only days with movements.

## Weekly Aggregation

Weekly output means 7-day average ending Friday.

Algorithm:

1. Use completed daily series.
2. Assign each date to the next Friday on or after that date.
3. For each Friday week ending date, include exactly 7 calendar days.
4. For the first partial week starting `2018-01-01`, either:
   - Include only once there are 7 available days, recommended for strict 7-day average, or
   - Backfill missing pre-start dates with `0.0`, if the balance requires a week ending immediately after `2018-01-01`.
5. Default recommendation: strict 7-day windows only.
6. Weekly value is arithmetic mean of the 7 daily `KBD` values.

Output date column:

```text
week_ending
```

The week ending date must always be Friday.

## Monthly Aggregation

Monthly output means full calendar month average.

Algorithm:

1. Use completed daily series.
2. Group by calendar month.
3. Include every calendar day in the month.
4. Fill missing daily values with `0.0` before averaging.
5. For the current/future partial month:
   - If the daily calendar only extends to available Kpler max date, average through that date and mark the manifest as partial.
   - If the balance requires full-month forecast average, extend through month-end and fill missing forecast days with `0.0` unless Kpler provides forecast values.
6. Default recommendation: extend through the latest Kpler returned date, not month-end beyond available data.

Output date column:

```text
month
```

Use `YYYY-MM-01` for monthly rows.

## Clean Heading Rules

Output headings must be lowercase snake case, with units at the end.

Examples:

```text
imports_total_kbd
exports_total_kbd
imports_latin_america_kbd
nwe_net_imports_kbd
padd3_to_padd1ab_kbd
```

Do not include Kpler enum names in final clean headings. Keep Kpler details in manifest and raw-normalized files.

## Pull Execution Order

Recommended order:

1. Load config.
2. Authenticate Kpler SDK client.
3. Run a small discovery/validation query:
   - Confirm product names.
   - Confirm country zone names.
   - Confirm PADD names.
   - Confirm returned columns for each split.
4. Pull external U.S. products.
5. Pull external Europe products.
6. Pull domestic PADD movements.
7. Write raw response files.
8. Normalize to daily long schema.
9. Build balance-ready daily wide outputs.
10. Complete dates and zero-fill numeric series.
11. Create weekly Friday-ending 7-day averages.
12. Create monthly averages.
13. Run validations.
14. Write manifest.

## Validation Requirements

Fail the run if:

- Required credentials are missing.
- Kpler SDK import fails.
- Any required product name returns no data for the full date range.
- Any configured Europe country name is rejected by Kpler.
- Required daily date column cannot be found.
- Required value column cannot be found.
- Weekly output contains a non-Friday `week_ending`.
- Monthly output has duplicate `month` rows for a product file.
- Any balance-ready CSV has duplicate date rows.
- `value_kbd` cannot be parsed as numeric.

Warn but do not fail if:

- Current/future forecast dates are absent.
- A region group has no flows for a product on a given day.
- A future month is partial.
- PADD name variants need fallback matching.

Manifest validation checks:

```json
{
  "start_date_ok": true,
  "all_weekly_dates_friday": true,
  "daily_dates_completed": true,
  "missing_daily_values_zero_filled": true,
  "with_forecast_true": true,
  "external_with_intra_country_false": true,
  "domestic_with_intra_country_true": true,
  "unit_kbd": true
}
```

## Testing Plan

Add focused tests once implementation begins:

1. Unit tests for product mapping:
   - `Gasoil/Diesel -> diesel`
   - `Kero/Jet -> jet`
   - `Light Ends -> gasoline`
2. Unit tests for Europe country mapping:
   - NWE, MED, and Other Europe membership.
3. Unit tests for U.S. import/export group mapping.
4. Unit tests for daily date completion:
   - Missing dates become `0.0`.
   - Existing values are preserved.
5. Unit tests for Friday week assignment.
6. Unit tests for monthly averaging over full calendar days.
7. Integration smoke test with a short date range:
   - One product.
   - One geography.
   - Seven to ten days.
8. Full dry run:
   - All pull sets from `2018-01-01`.
   - Confirm output row counts and date ranges.

## Open Items To Confirm During Implementation

These should be resolved with Kpler SDK discovery calls before production use:

- Exact Kpler Basic Auth credential behavior for the direct HTTP endpoint in the account being used.
- Exact country spellings accepted by `from_zones` and `to_zones`.
- Whether `from_zones=["United States"]` and `to_zones=["United States"]` works for domestic PADD movement when `with_intra_country=True`.
- Whether PADD route filters work directly in `from_zones` and `to_zones`, or whether broad U.S. domestic pulls plus `OriginPadds` and `DestinationPadds` split is required.
- Exact response column names for daily date and value.
- Whether `with_forecast=True` returns future dates beyond today, or only forecast-labeled current flows.
- Whether Kpler returns `Light Ends` as a parent product only or includes child product splits.

## Initial Implementation Checklist

- [ ] Add Kpler dependency to `requirements.txt` after verifying package name and version.
- [ ] Add config files under `Kpler/config/`.
- [ ] Add `src/kpler_pull.py`.
- [ ] Add `src/kpler_config.py`.
- [ ] Add `src/kpler_transform.py`.
- [ ] Add `src/kpler_validate.py`.
- [ ] Add `npm` script or direct Python command:
  - `kpler`: `python3 src/kpler_pull.py`
- [ ] Run discovery query.
- [ ] Generate raw daily files.
- [ ] Generate clean daily files.
- [ ] Generate weekly files.
- [ ] Generate monthly files.
- [ ] Write manifest.
- [ ] Validate outputs.

## Expected Final Output Inventory

External U.S.:

```text
Kpler/output/daily/us_diesel_daily.csv
Kpler/output/weekly/us_diesel_weekly.csv
Kpler/output/monthly/us_diesel_monthly.csv
Kpler/output/daily/us_jet_daily.csv
Kpler/output/weekly/us_jet_weekly.csv
Kpler/output/monthly/us_jet_monthly.csv
Kpler/output/daily/us_gasoline_daily.csv
Kpler/output/weekly/us_gasoline_weekly.csv
Kpler/output/monthly/us_gasoline_monthly.csv
```

External Europe:

```text
Kpler/output/daily/europe_diesel_daily.csv
Kpler/output/weekly/europe_diesel_weekly.csv
Kpler/output/monthly/europe_diesel_monthly.csv
Kpler/output/daily/europe_jet_daily.csv
Kpler/output/weekly/europe_jet_weekly.csv
Kpler/output/monthly/europe_jet_monthly.csv
Kpler/output/daily/europe_gasoline_daily.csv
Kpler/output/weekly/europe_gasoline_weekly.csv
Kpler/output/monthly/europe_gasoline_monthly.csv
```

Domestic PADD:

```text
Kpler/output/daily/us_padd_movements_daily.csv
Kpler/output/weekly/us_padd_movements_weekly.csv
Kpler/output/monthly/us_padd_movements_monthly.csv
```

Optional domestic per-product files:

```text
Kpler/output/weekly/us_diesel_padd_movements_weekly.csv
Kpler/output/monthly/us_diesel_padd_movements_monthly.csv
Kpler/output/weekly/us_jet_padd_movements_weekly.csv
Kpler/output/monthly/us_jet_padd_movements_monthly.csv
Kpler/output/weekly/us_gasoline_padd_movements_weekly.csv
Kpler/output/monthly/us_gasoline_padd_movements_monthly.csv
```

## Success Criteria

The implementation is complete when:

- All configured pull sets run from `2018-01-01`.
- External U.S. and Europe pulls use `with_intra_country=False`.
- Domestic PADD pulls use `with_intra_country=True`.
- All pulls use daily granularity and `KBD`.
- Forecast/predictive data is included with `with_forecast=True`.
- Weekly outputs are 7-day averages ending Friday.
- Monthly outputs are calendar-month averages from completed daily data.
- Missing daily dates are included and numeric values are zero-filled before weekly/monthly averaging.
- Every product/geography set has one weekly and one monthly clean balance-ready CSV.
- The manifest records every Kpler argument and every output row count.
