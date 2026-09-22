# Distillate split charts

The Diesel Charts tab ends with a separate **Distillate split** section. It uses
`eia_monthly/distillate_sulfur_stocks.json`, an optional chart-only payload. Existing
balance rows, adjustments, saved views, and forecasts do not consume this data.
Older payloads containing only inventories still work.

- Inventories: thousand barrels; production, imports, exports: thousand barrels/day.
- Categories: 0–15 ppm, >15–500 ppm, >500 ppm, and combined >15 ppm.
- Production is refiner/refinery **and blender net production**. Negative values
  are retained. Refinery-only series and four-week averages are excluded.
- Monthly data comes from the local PET bulk file; weekly data comes from cached
  historical workbooks and WPSR tables, with WPSR taking precedence.
- Weekly >500 ppm imports sum the reported >500–2000 and >2000 ppm buckets.
- Missing observations and incomplete component sums remain gaps, never zero.
- EIA publishes sulfur-specific exports monthly, not weekly. Weekly views include
  a notice instead of estimated or monthly-to-weekly export charts.
- Northeast inventories sum A+B, with total PADD 1 minus C as the fallback.
  Current sulfur flow series are not split into A/B and C. Both regional views
  show clearly labeled **PADD 1** flow charts, including in zoom and exports.
- Aggregates sum the corresponding PADD components only when every component is
  reported. U.S. observations use the reported U.S. series.

`src/export_sulfur_stocks.py` is called by the existing weekly/monthly export
pipeline. It selects exact total series names and units, excluding country flows,
bonded subsets, overlapping sulfur categories, and rolling averages. Series IDs
are retained under `sources` in the payload. No chart includes forecasts.

EIA references: [monthly sulfur exports](https://www.eia.gov/dnav/pet/pet_move_exp_a_epdm10_eex_mbblpd_m.htm)
and [weekly supply estimates](https://www.eia.gov/dnav/pet/pet_sum_sndw_dcus_nus_w.htm).
