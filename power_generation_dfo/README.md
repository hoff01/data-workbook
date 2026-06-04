# Power Generation DFO

This folder pulls and estimates PADD 1 Northeast power-sector DFO consumption from EIA data.

## Method

1. Pull monthly EIA facility fuel consumption for PADD 1 states and fuels `DFO` and `RFO`.
2. Pull from 2018 forward by default.
3. Aggregate `DFO` consumption across all requested PADD 1 states by month, using only `primeMover=ALL` to avoid double counting facility-fuel rows.
4. Pull daily EIA RTO oil generation for `MIDA` and `NE` in Central time.
5. Sum `MIDA` and `NE` daily generation to create a PADD 1 Northeast oil-generation proxy.
6. Build monthly calibration observations from actual DFO and same-month daily oil MWh.
7. Score each month with a rolling local Pearson correlation between monthly DFO consumption and same-month MIDA+NE oil MWh.
8. Recalculate the global DFO-per-oil-MWh factor by year using all available months through that year. Calendar month is not used in the factor.
9. Select 20 high-correlation months that keep the weighted DFO-to-MWh factor close to the configured target, currently `1.15`.
10. Estimate daily DFO consumption by multiplying daily MIDA+NE oil MWh by the annual recalibrated factor.

The latest annual factor uses 20 locally correlated calibration months optimized toward the target factor from the 2018-forward history.

## Run

```bash
python3 power_generation_dfo/pull_power_generation_dfo.py
python3 power_generation_dfo/hourly_dfo_forecast.py
```

Optional environment variables:

- `EIA_API_KEY`, `EIA_API_TOKEN`, or `EIA_KEY`: EIA API key override.
- `POWER_DFO_START_YEAR`: override the default start year of `2018`.
- `POWER_DFO_SELECT_TOP_CORRELATED_MONTHS`: override the default selected-month count of `20`.
- `POWER_DFO_CORRELATION_WINDOW_MONTHS`: override the rolling correlation window; defaults to `12`.
- `POWER_DFO_TARGET_FACTOR`: override the DFO-per-oil-MWh target; defaults to `1.15`.
- `POWER_DFO_END_DATE`: override the daily RTO end date in `YYYY-MM-DD`.
- `POWER_DFO_PAGE_LENGTH`: override API page size; defaults to `5000`.

## Outputs

- `facility_fuel_raw.csv`: raw EIA facility-fuel rows.
- `rto_oil_daily_raw.csv`: raw EIA daily RTO oil-generation rows.
- `monthly_padd1_facility_fuel.csv`: monthly PADD 1 state-summed DFO/RFO consumption.
- `daily_padd1_ne_oil_generation.csv`: daily MIDA+NE oil MWh.
- `calibration_months.csv`: monthly actual DFO and same-month oil-generation calibration observations.
- `annual_calibration_factors.csv`: yearly recalibrated DFO-per-oil-MWh factors.
- `estimated_daily_dfo.csv`: daily estimated DFO consumption.
- `estimated_daily_dfo_2026.csv`: 2026-only daily estimated DFO consumption.
- `estimated_monthly_dfo.csv`: monthly sums of the daily estimates.
- `daily_distillate_burn_2026.jpg`: 2026 daily DFO burn chart.
- `manifest.json`: run metadata.
- `hourly_region_data_raw.csv`: raw hourly EIA region data for MIDA and NE.
- `hourly_oil_generation_raw.csv`: raw hourly EIA oil generation for MIDA and NE.
- `hourly_dfo_model_input.csv`: merged hourly load, day-ahead forecast, oil generation, and DFO estimate history.
- `weather_14d_padd1_cities.csv`: 14-day hourly temperatures and HDD/CDD features for one major city in each PADD 1 state/DC.
- `dfo_generation_forecast_24h.csv`: next 24 hours of forecast DFO generation.
- `dfo_generation_forecast_24h.jpg`: next-24-hour forecast chart.
- `hourly_forecast_manifest.json`: hourly forecast run metadata.

The hourly forecast script uses AutoGluon Chronos-2 when `autogluon.timeseries` is installed. If Chronos-2 is not available, it falls back to a transparent hourly load/weather/profile model and records that in the manifest.
