#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "weekly_call_outputs" / "generate_weekly_images.py"
MODULE_SOURCE = MODULE_PATH.read_text(encoding="utf-8")
assert "def apply_weekly_adjustments(" not in MODULE_SOURCE, "legacy weekly adjustment calculator must stay removed"
assert 'dashboard_state.get("materialized", {})' in MODULE_SOURCE, "weekly output must use materialized dashboard state"
SPEC = importlib.util.spec_from_file_location("weekly_images", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
weekly_images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(weekly_images)


def point(period: str, status: str, region: str, *, exports: float, balance: float) -> dict[str, Any]:
    destinations = {
        "exportsLatinAmericaKbd": 100.0,
        "exportsEuropeKbd": 50.0,
        "exportsAfricaKbd": 25.0,
        "exportsOtherKbd": 10.0,
    }
    if status == "actual":
        # Actual destination values deliberately disagree with the solved total.
        destinations = {
            "exportsLatinAmericaKbd": 1.0,
            "exportsEuropeKbd": 2.0,
            "exportsAfricaKbd": 3.0,
            "exportsOtherKbd": 4.0,
        }
    demand = 125.0 if status == "actual" else 300.0 + 40.0 + 20.0 - 10.0 - exports - balance
    daily_build_draw = 300.0 + 40.0 + 20.0 - 10.0 - exports - demand
    return {
        "period": period,
        "status": status,
        "regionKey": region,
        "productionKbd": 300.0,
        "importsKbd": 40.0,
        "receiptsKbd": 20.0,
        "shipmentsKbd": 10.0,
        "netReceiptsKbd": 10.0,
        "exportsKbd": exports,
        "demandKbd": demand,
        "balanceKbd": balance,
        "stockChangeKbd": -7.0 if status == "actual" else balance,
        "periodBuildDrawKb": -49.0 if status == "actual" else balance * 7.0,
        "dailyBuildDrawKbd": daily_build_draw,
        "crudeRunsKbd": 600.0,
        "operatingUtilizationPct": 88.0,
        "yieldPct": 50.0,
        **destinations,
    }


periods = ["2026-07-17", "2026-07-24", "2026-07-31", "2026-08-07", "2026-08-14", "2026-08-21"]
base_regions = ["padd1ab", "padd1c", "padd2", "padd3", "padd4", "padd5"]
resolved_rows: list[dict[str, Any]] = []
raw_rows: list[dict[str, Any]] = []
for index, period in enumerate(periods):
    status = "actual" if index == 0 else "forecast"
    for region in base_regions:
        exports = 1_000.0 if status == "actual" and region == "padd3" else 185.0
        if status == "forecast" and period == "2026-07-24" and region == "padd3":
            exports = 205.0
        balance = 30.0 + index
        row = point(period, status, region, exports=exports, balance=balance)
        if exports == 205.0:
            row["exportsEuropeKbd"] = 70.0
        if period == "2026-07-24" and region == "padd2":
            row["productionKbd"] = 1237.85
            row["operatingUtilizationPct"] = 92.05
            row["yieldPct"] = 32.05
            row["demandKbd"] = row["productionKbd"] + row["importsKbd"] + row["receiptsKbd"] - row["shipmentsKbd"] - row["exportsKbd"] - row["balanceKbd"]
            row["dailyBuildDrawKbd"] = row["balanceKbd"]
        resolved_rows.append(row)
        raw_rows.append({**row, "exportsKbd": 9999.0, "balanceKbd": 9999.0, "periodBuildDrawKb": 69993.0})
    us_parts = [row for row in resolved_rows if row["period"] == period and row["regionKey"] in base_regions]
    resolved_rows.append(
        point(
            period,
            status,
            "us",
            exports=sum(float(row["exportsKbd"]) for row in us_parts),
            balance=sum(float(row["balanceKbd"]) for row in us_parts),
        )
    )
    raw_rows.append(point(period, status, "us", exports=9999.0, balance=9999.0))

bundle = {
    "generatedAt": "2026-07-20T12:00:00Z",
    "product": {"key": "diesel", "title": "Diesel", "shortTitle": "Diesel"},
    "freshness": {"latestWeekly": periods[0]},
    "forecast": {"method": "flat monthly step hold"},
    "checksums": {"eia_weekly": "synthetic-weekly", "eia_monthly": "synthetic-monthly"},
    "settings": {
        "forecastEnd": "2027-06-01",
        "revision": "revision-1",
        "adjustments": [{"frequency": "monthly"}],
        "crudeOutages": [],
        "refineryCapacityAdjustments": [],
    },
    "regionalBalance": {
        "regions": [{"key": key, "label": key} for key in [*base_regions, "us"]],
        "weekly": raw_rows,
        "movementFlows": [],
    },
    "crudeRuns": {"weekly": []},
}
dashboard_state = {
    "schema": "us-balances.dashboard-state",
    "schemaVersion": 1,
    "id": "synthetic-state",
    "product": "diesel",
    "savedAt": "2026-07-20T12:00:00Z",
    "fingerprint": "synthetic-fingerprint",
    "provenance": {"latestWeekly": periods[0], "sourceChecksums": bundle["checksums"]},
    "settings": {
        "forecastEnd": "2027-06-01",
        "revision": "revision-1",
        "adjustments": [{"frequency": "monthly"}],
        "crudeOutages": [],
        "refineryCapacityAdjustments": [],
    },
    "materialized": {
        "regionalBalance": {
            "monthly": [{"period": "2026-07", "regionKey": "padd3"}],
            "weekly": resolved_rows,
        }
    },
}

validated = weekly_images.validate_dashboard_state(dashboard_state, "diesel", bundle)
payload = weekly_images.build_weekly_payload(
    bundle,
    ROOT / "Diesel_Balance" / "data" / "diesel_balance_bundle.json",
    5,
    validated,
)

assert [row["week_ending"] for row in payload["periods"]] == periods
assert payload["periods"][1]["highlight"] is True
p3 = next(region for region in payload["table"]["regions"] if region["key"] == "padd3")
exports_row = next(row for row in p3["rows"] if row["key"] == "exports")
net_row = next(row for row in p3["rows"] if row["key"] == "net_kb")
p2 = next(region for region in payload["table"]["regions"] if region["key"] == "padd2")
p2_production = next(row for row in p2["rows"] if row["key"] == "production")
p2_utilization = next(row for row in p2["rows"] if row["key"] == "utilization")
p2_yield = next(row for row in p2["rows"] if row["key"] == "yield")
assert exports_row["values"][periods[0]] == 1000.0, "actual export total must remain solved"
assert exports_row["values"][periods[1]] == 205.0, "first weekly destination edit must be exact"
assert exports_row["values"][periods[2]] == 185.0, "neighboring week must not be recalibrated"
assert net_row["values"][periods[0]] == -49.0, "actual build/draw must use solved stock change"
assert net_row["values"][periods[1]] == 217.0, "forecast build/draw must use exact adjusted daily balance"
assert payload["inventory_changes"]["forecasts"][0]["values_mb"][3] == 0.22
assert payload["dashboard_state"]["id"] == "synthetic-state"
assert payload["source"]["dashboard_state_fingerprint"] == "synthetic-fingerprint"
assert p2_production["values"][periods[1]] == 1237.9, "weekly output must use dashboard half-up rounding"
assert p2_utilization["values"][periods[1]] == 92.1, "utilization must match dashboard half-up rounding"
assert p2_yield["values"][periods[1]] == 32.1, "formatter must prefer the saved materialized yield"

print("weekly dashboard-state contract ok")
