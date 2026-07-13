#!/usr/bin/env python3
"""Generate PowerPoint-ready weekly balance statistics images.

The normal workflow is:
1. Run the balance repository's existing full-bundle JSON generator.
2. Build a compact weekly-only JSON contract from that bundle.
3. Render every PNG exclusively from the compact weekly JSON.

The package is intentionally relocatable.  Put ``weekly_call_ouputs`` directly
inside another compatible balance repository and run the Windows launcher.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "weekly_stats_config.json"

INK = "#16181d"
MUTED = "#636b75"
GRID = "#d8dde3"
HEADER = "#24272d"
ACTUAL_FILL = "#eef0f2"
FORECAST_HIGHLIGHT = "#e2cf39"
REGION_FILL = "#d7cdb8"
SECTION_FILL = "#e5e7e9"
POSITIVE = "#17823b"
NEGATIVE = "#d52317"
TITLE_RED = "#ba2828"
WHITE = "#ffffff"

DEFAULT_FORMAT: dict[str, Any] = {
    "font_scale": 1.0,
    "colors": {
        "ink": INK,
        "muted": MUTED,
        "grid": GRID,
        "header": HEADER,
        "actual_fill": ACTUAL_FILL,
        "forecast_highlight": FORECAST_HIGHLIGHT,
        "region_fill": REGION_FILL,
        "section_fill": SECTION_FILL,
        "positive": POSITIVE,
        "negative": NEGATIVE,
        "title_red": TITLE_RED,
        "white": WHITE,
    },
    "table": {
        "width_in": 7.35,
        "height_in": 7.05,
        "title_x": 0.018,
        "title_y": 0.968,
        "title_font_size": 26.0,
        "left": 0.012,
        "right": 0.992,
        "top": 0.905,
        "bottom": 0.018,
        "region_column_share": 0.125,
        "metric_column_share": 0.21,
        "header_font_size": 7.5,
        "region_font_size": 7.0,
        "body_font_size": 6.7,
        "us_section_gap_rows": 0.65,
        "repeat_header_before_us": True,
    },
    "chart": {
        "width_in": 4.25,
        "height_in": 2.55,
        "left": 0.16,
        "right": 0.985,
        "bottom": 0.23,
        "top": 0.76,
        "bar_width": 0.82,
        "title_font_size": 13.5,
        "x_font_size": 8.2,
        "y_font_size": 7.6,
        "value_font_size": 8.0,
        "title_pad": 12.0,
        "value_label_offset_points": 4.0,
    },
    "slide": {
        "width_px": 2400,
        "height_px": 1350,
        "placements": {
            "table": [0.005, 0.015, 0.545, 0.97],
            "forecast_week_1": [0.555, 0.665, 0.215, 0.31],
            "forecast_week_2": [0.775, 0.665, 0.215, 0.31],
            "eia_actuals": [0.555, 0.335, 0.215, 0.31],
        },
        "enforce_equal_chart_size": True,
        "note_title_x": 0.585,
        "note_title_y": 0.255,
        "note_title_font_size": 16.0,
        "note_body_x": 0.585,
        "note_body_y": 0.215,
        "note_body_font_size": 9.5,
        "note_body_line_spacing": 1.45,
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "product": "diesel",
    "forecast_weeks": 5,
    "dpi": 180,
    "run_balance_json_builder": True,
    "output_folder": "outputs",
    "format": DEFAULT_FORMAT,
}

PRODUCT_LAYOUTS: dict[str, dict[str, Any]] = {
    "diesel": {
        "base_regions": ["padd1ab", "padd1c", "padd2", "padd3", "padd4", "padd5"],
        "table_regions": ["padd1ab", "padd2", "padd3", "us"],
        "table_region_labels": {
            "padd1ab": "PADD 1-A/B",
            "padd2": "PADD 2",
            "padd3": "PADD 3",
            "us": "US",
        },
        "table_row_keys": {
            "padd1ab": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "domestic_exports",
                "exports",
                "demand",
                "net_kb",
            ],
            "padd2": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "domestic_exports",
                "exports",
                "demand",
                "net_kb",
            ],
            "padd3": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "domestic_exports",
                "exports",
                "demand",
                "demand_exports",
                "net_kb",
            ],
            "us": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "demand",
                "exports",
                "domestic_exports",
                "net_kb",
            ],
        },
        "crude_region": {
            "padd1ab": "padd1",
            "padd1c": "padd1",
            "padd2": "padd2",
            "padd3": "padd3",
            "padd4": "padd4",
            "padd5": "padd5",
            "us": "us",
        },
        "chart_labels": ["P1\nA/B", "P1 C", "P2", "P3", "P4", "P5", "Total"],
    },
    "jet": {
        "base_regions": ["padd1", "padd2", "padd3", "padd4", "padd5"],
        "table_regions": ["padd1", "padd2", "padd3", "us"],
        "table_region_labels": {
            "padd1": "PADD 1",
            "padd2": "PADD 2",
            "padd3": "PADD 3",
            "us": "US",
        },
        "table_row_keys": {
            "padd1": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "domestic_exports",
                "exports",
                "demand",
                "net_kb",
            ],
            "padd2": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "domestic_exports",
                "exports",
                "demand",
                "net_kb",
            ],
            "padd3": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "domestic_exports",
                "exports",
                "demand",
                "demand_exports",
                "net_kb",
            ],
            "us": [
                "utilization",
                "yield",
                "production",
                "imports",
                "domestic_imports",
                "separator",
                "demand",
                "exports",
                "domestic_exports",
                "net_kb",
            ],
        },
        "crude_region": {
            "padd1": "padd1",
            "padd2": "padd2",
            "padd3": "padd3",
            "padd4": "padd4",
            "padd5": "padd5",
            "us": "us",
        },
        "chart_labels": ["P1", "P2", "P3", "P4", "P5", "Total"],
    },
}


class ExportError(RuntimeError):
    """Raised when the weekly export contract cannot be produced safely."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExportError(f"Required JSON file was not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExportError(f"Invalid JSON in {path}: {exc}") from exc


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: Path) -> dict[str, Any]:
    return deep_merge(DEFAULT_CONFIG, load_json(path) if path.exists() else {})


def setting(section: dict[str, Any], key: str) -> float:
    value = finite_number(section.get(key), math.nan)
    if not math.isfinite(value):
        raise ExportError(f"Format setting {key!r} must be a number.")
    return value


def font_size(format_config: dict[str, Any], section: dict[str, Any], key: str) -> float:
    return setting(section, key) * setting(format_config, "font_scale")


def find_balance_root(start: Path) -> Path:
    candidates = [start.resolve(), *start.resolve().parents]
    for candidate in candidates:
        if (candidate / "package.json").is_file() and (
            candidate / "src" / "build_balance_dashboards.ts"
        ).is_file():
            return candidate
    raise ExportError(
        "Could not locate a compatible balance repository. Keep this folder inside "
        "the balance repository or pass --balance-root."
    )


def npm_executable() -> str:
    executable = shutil.which("npm.cmd") or shutil.which("npm")
    if not executable:
        raise ExportError(
            "Node.js/npm is required to run the existing balance JSON generator but npm "
            "was not found on PATH."
        )
    return executable


def run_balance_json_builder(balance_root: Path) -> None:
    package = load_json(balance_root / "package.json")
    if "build:balances" not in package.get("scripts", {}):
        raise ExportError(
            f"{balance_root / 'package.json'} does not define the required build:balances script."
        )
    env = os.environ.copy()
    env["BALANCE_WRITE_FULL_BUNDLE"] = "1"
    print("Creating the balance JSON with the existing build:balances function...")
    completed = subprocess.run(
        [npm_executable(), "run", "build:balances"],
        cwd=balance_root,
        env=env,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise ExportError(
            f"The balance JSON generator failed with exit code {completed.returncode}."
        )


def bundle_path(balance_root: Path, product: str) -> Path:
    direct = balance_root / f"{product.title()}_Balance" / "data" / f"{product}_balance_bundle.json"
    if direct.is_file():
        return direct
    matches = sorted(balance_root.glob(f"*/data/{product}_balance_bundle.json"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ExportError(
            f"No {product} full bundle JSON was generated below {balance_root}."
        )
    raise ExportError(
        f"More than one {product} bundle was found; pass a repository containing one active balance."
    )


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ExportError(f"Expected an ISO date but received {value!r}.") from exc


def finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def rounded(value: float, digits: int = 2) -> float:
    return round(finite_number(value), digits)


def mean_or_none(values: Iterable[float]) -> float | None:
    finite = [finite_number(value, math.nan) for value in values]
    finite = [value for value in finite if math.isfinite(value)]
    return fmean(finite) if finite else None


def latest_by_key(rows: Iterable[dict[str, Any]], key_fields: list[str]) -> dict[tuple[str, ...], dict[str, Any]]:
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        existing = result.get(key)
        if existing is None or str(row.get("updatedAt", "")) >= str(existing.get("updatedAt", "")):
            result[key] = row
    return result


def apply_weekly_adjustments(
    bundle: dict[str, Any],
    regional_index: dict[str, dict[str, dict[str, Any]]],
    product: str,
) -> None:
    layout = PRODUCT_LAYOUTS[product]
    base_regions = set(layout["base_regions"])
    aliases = {
        "demandAdjustment": "demand",
        "importsAdjustment": "imports",
        "exportsAdjustment": "exports",
        "yieldAdjustmentPct": "yieldPct",
    }
    field_for_line = {
        "demand": "demandKbd",
        "imports": "importsKbd",
        "exports": "exportsKbd",
        "production": "productionKbd",
    }
    adjustments = latest_by_key(
        (
            row
            for row in bundle.get("settings", {}).get("adjustments", [])
            if row.get("frequency") == "weekly"
        ),
        ["period", "regionKey", "lineId"],
    )
    changed: set[tuple[str, str]] = set()
    for adjustment in adjustments.values():
        period = str(adjustment.get("period", ""))
        region = str(adjustment.get("regionKey", ""))
        if region not in base_regions or period not in regional_index:
            continue
        point = regional_index[period].get(region)
        if not point or point.get("status") != "forecast":
            continue
        line = aliases.get(str(adjustment.get("lineId", "")), str(adjustment.get("lineId", "")))
        if line == "yieldPct":
            point["yieldOverridePct"] = finite_number(adjustment.get("valueKbd"))
            changed.add((period, region))
            continue
        field = field_for_line.get(line)
        if field:
            point[field] = finite_number(adjustment.get("valueKbd"))
            changed.add((period, region))

    for period, region in changed:
        point = regional_index[period][region]
        point["balanceKbd"] = rounded(
            finite_number(point.get("productionKbd"))
            + finite_number(point.get("importsKbd"))
            + finite_number(point.get("netReceiptsKbd"))
            - finite_number(point.get("exportsKbd"))
            - finite_number(point.get("demandKbd"))
        )

    # Aggregate rows are calculated, never manually entered.
    for period, bucket in regional_index.items():
        if not any((period, region) in changed for region in base_regions):
            continue
        parts = [bucket.get(region) for region in layout["base_regions"]]
        if not all(parts):
            continue
        us = bucket.get("us")
        if not us:
            continue
        for field in (
            "productionKbd",
            "importsKbd",
            "exportsKbd",
            "demandKbd",
            "netReceiptsKbd",
            "balanceKbd",
        ):
            us[field] = rounded(sum(finite_number(part.get(field)) for part in parts if part))


def movement_totals(bundle: dict[str, Any]) -> dict[tuple[str, str], dict[str, float]]:
    totals: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"receiptsKbd": 0.0, "shipmentsKbd": 0.0}
    )
    for flow in bundle.get("regionalBalance", {}).get("movementFlows", []):
        source = str(flow.get("fromRegionKey", ""))
        target = str(flow.get("toRegionKey", ""))
        for row in flow.get("weekly", []):
            period = str(row.get("period", ""))
            value = max(0.0, finite_number(row.get("valueKbd")))
            totals[(period, target)]["receiptsKbd"] += value
            totals[(period, source)]["shipmentsKbd"] += value
    return totals


def crude_index(bundle: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in bundle.get("crudeRuns", {}).get("weekly", []):
        result[str(row.get("regionKey", ""))][str(row.get("period", ""))] = row
    return result


def crude_forecast_context(
    crude: dict[str, dict[str, dict[str, Any]]],
    crude_region: str,
    period: str,
    latest_actual: str,
) -> tuple[float, float]:
    """Return forecast operating utilization and implied crude runs.

    Forecast utilization uses the three most recent prior observations for the
    same ISO week.  Capacity comes from the latest available actual.  This keeps
    the export weekly, dynamic, and independent from hard-coded calendar dates.
    """

    region_rows = crude.get(crude_region, {})
    actual_rows = [
        row
        for candidate, row in region_rows.items()
        if candidate <= latest_actual and row.get("status") == "actual"
    ]
    actual_rows.sort(key=lambda row: str(row.get("period", "")))
    if not actual_rows:
        return 0.0, 0.0
    latest_row = actual_rows[-1]
    target_week = parse_date(period).isocalendar().week
    seasonal = [
        row
        for row in actual_rows
        if parse_date(str(row.get("period"))).isocalendar().week == target_week
        and str(row.get("period")) < period
    ][-3:]
    utilization = mean_or_none(
        finite_number(row.get("operatingUtilizationPct", row.get("utilizationPct")))
        for row in seasonal
    )
    if utilization is None:
        utilization = finite_number(
            latest_row.get("operatingUtilizationPct", latest_row.get("utilizationPct"))
        )
    capacity = finite_number(
        latest_row.get("operatingCapacityKbd", latest_row.get("operableCapacityKbd"))
    )
    return rounded(utilization, 1), rounded(capacity * utilization / 100.0, 2)


def crude_metrics_for_period(
    crude: dict[str, dict[str, dict[str, Any]]],
    crude_region: str,
    period: str,
    latest_actual: str,
) -> tuple[float, float]:
    row = crude.get(crude_region, {}).get(period)
    if row and row.get("status") == "actual":
        utilization = finite_number(
            row.get("operatingUtilizationPct", row.get("utilizationPct"))
        )
        runs = finite_number(row.get("crudeRunsKbd"))
        return rounded(utilization, 1), rounded(runs, 2)
    return crude_forecast_context(crude, crude_region, period, latest_actual)


def region_label(bundle: dict[str, Any], key: str) -> str:
    for region in bundle.get("regionalBalance", {}).get("regions", []):
        if region.get("key") == key:
            return str(region.get("label", key))
    return key.upper()


def chart_label_for_region(key: str) -> str:
    return {
        "padd1": "P1",
        "padd1ab": "P1 A/B",
        "padd1c": "P1 C",
        "padd2": "P2",
        "padd3": "P3",
        "padd4": "P4",
        "padd5": "P5",
        "us": "Total",
    }.get(key, key.upper())


def table_row_values(
    point: dict[str, Any],
    period: str,
    latest_actual: str,
    crude: dict[str, dict[str, dict[str, Any]]],
    crude_region: str,
    movement: dict[tuple[str, str], dict[str, float]],
) -> list[dict[str, Any]]:
    utilization, crude_runs = crude_metrics_for_period(
        crude, crude_region, period, latest_actual
    )
    production = finite_number(point.get("productionKbd"))
    yield_pct = (
        finite_number(point.get("yieldOverridePct"))
        if point.get("yieldOverridePct") is not None
        else (production / crude_runs * 100.0 if crude_runs > 0 else 0.0)
    )
    movements = movement.get((period, str(point.get("regionKey", ""))), {})
    demand = finite_number(point.get("demandKbd"))
    exports = finite_number(point.get("exportsKbd"))
    daily_balance = finite_number(
        point.get("stockChangeKbd")
        if point.get("status") == "actual"
        else point.get("balanceKbd")
    )
    return [
        {"key": "utilization", "label": "Utilization", "unit": "percent", "value": rounded(utilization, 1)},
        {"key": "yield", "label": "Yield", "unit": "percent", "value": rounded(yield_pct, 1)},
        {"key": "production", "label": "Production", "unit": "kbd", "value": rounded(production, 1)},
        {"key": "imports", "label": "Imports", "unit": "kbd", "value": rounded(point.get("importsKbd"), 1)},
        {"key": "domestic_imports", "label": "Domestic Imports", "unit": "kbd", "value": rounded(movements.get("receiptsKbd", 0), 1)},
        {"key": "separator", "label": "", "unit": "separator", "value": None},
        {"key": "domestic_exports", "label": "Domestic Exports", "unit": "kbd", "value": rounded(movements.get("shipmentsKbd", 0), 1)},
        {"key": "exports", "label": "Exports", "unit": "kbd", "value": rounded(exports, 1)},
        {"key": "demand", "label": "Demand", "unit": "kbd", "value": rounded(demand, 1)},
        {"key": "demand_exports", "label": "Demand + Exports", "unit": "kbd", "value": rounded(demand + exports, 1)},
        {"key": "net_kb", "label": "Net (KB)", "unit": "kb", "value": rounded(daily_balance * 7.0, 0)},
    ]


def build_weekly_payload(
    bundle: dict[str, Any],
    source_bundle: Path,
    forecast_weeks: int,
) -> dict[str, Any]:
    product = str(bundle.get("product", {}).get("key", "")).lower()
    if product not in PRODUCT_LAYOUTS:
        raise ExportError(f"Unsupported product {product!r}; expected diesel or jet.")
    if forecast_weeks != 5:
        raise ExportError("This slide contract requires exactly five forecast weeks.")

    regional_index: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in bundle.get("regionalBalance", {}).get("weekly", []):
        regional_index[str(row.get("period", ""))][str(row.get("regionKey", ""))] = copy.deepcopy(row)
    if not regional_index:
        raise ExportError("The full bundle does not contain regionalBalance.weekly rows.")
    apply_weekly_adjustments(bundle, regional_index, product)

    actual_periods = sorted(
        period
        for period, bucket in regional_index.items()
        if any(row.get("status") == "actual" for row in bucket.values())
    )
    if not actual_periods:
        raise ExportError("No weekly actual period was found in the balance JSON.")
    latest_actual = actual_periods[-1]
    forecast_periods = sorted(
        period
        for period, bucket in regional_index.items()
        if period > latest_actual and any(row.get("status") == "forecast" for row in bucket.values())
    )[:forecast_weeks]
    if len(forecast_periods) < forecast_weeks:
        raise ExportError(
            f"Expected {forecast_weeks} forecast weeks after {latest_actual}, found {len(forecast_periods)}."
        )
    selected_periods = [latest_actual, *forecast_periods]

    layout = PRODUCT_LAYOUTS[product]
    movement = movement_totals(bundle)
    crude = crude_index(bundle)
    table_regions: list[dict[str, Any]] = []
    for region_key in layout["table_regions"]:
        rows_by_key: dict[str, dict[str, Any]] = {}
        row_order: list[str] = []
        for period in selected_periods:
            point = regional_index.get(period, {}).get(region_key)
            if not point:
                raise ExportError(f"Missing {region_key} weekly row for {period}.")
            rows = table_row_values(
                point,
                period,
                latest_actual,
                crude,
                layout["crude_region"][region_key],
                movement,
            )
            row_map = {row["key"]: row for row in rows}
            rows = [
                row_map[key]
                for key in layout["table_row_keys"][region_key]
                if key in row_map
            ]
            if not row_order:
                row_order = [row["key"] for row in rows]
                rows_by_key = {
                    row["key"]: {
                        "key": row["key"],
                        "label": row["label"],
                        "unit": row["unit"],
                        "values": {},
                    }
                    for row in rows
                }
            for row in rows:
                rows_by_key[row["key"]]["values"][period] = row["value"]
        table_regions.append(
            {
                "key": region_key,
                "label": layout["table_region_labels"][region_key],
                "rows": [rows_by_key[key] for key in row_order],
            }
        )

    chart_regions = [*layout["base_regions"], "us"]

    def inventory_change(period: str) -> dict[str, Any]:
        bucket = regional_index[period]
        values_mb = []
        for region_key in chart_regions:
            point = bucket.get(region_key)
            if not point:
                raise ExportError(f"Missing inventory-change row {region_key} for {period}.")
            daily = finite_number(
                point.get("stockChangeKbd")
                if point.get("status") == "actual"
                else point.get("balanceKbd")
            )
            values_mb.append(rounded(daily * 7.0 / 1000.0, 2))
        return {
            "week_ending": period,
            "status": "actual" if period == latest_actual else "forecast",
            "labels": layout["chart_labels"],
            "region_keys": chart_regions,
            "values_mb": values_mb,
        }

    product_meta = bundle.get("product", {})
    try:
        portable_bundle_path = str(source_bundle.relative_to(source_bundle.parents[2]))
    except (IndexError, ValueError):
        portable_bundle_path = source_bundle.name
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "bundle_json": portable_bundle_path,
            "bundle_generated_at": bundle.get("generatedAt"),
            "balance_latest_weekly": bundle.get("freshness", {}).get("latestWeekly"),
            "forecast_method": bundle.get("forecast", {}).get("method"),
        },
        "product": {
            "key": product,
            "title": product_meta.get("title", product.title()),
            "short_title": product_meta.get("shortTitle", product.title()),
            "stats_title": f"{product_meta.get('shortTitle', product.title())} Stats",
        },
        "periods": [
            {
                "week_ending": period,
                "status": "actual" if period == latest_actual else "forecast",
                "highlight": period == forecast_periods[0],
            }
            for period in selected_periods
        ],
        "table": {
            "frequency": "weekly",
            "regions": table_regions,
        },
        "inventory_changes": {
            "unit": "million barrels",
            "actual": inventory_change(latest_actual),
            "forecasts": [inventory_change(period) for period in forecast_periods[:2]],
        },
    }
    validate_payload(payload)
    return payload


def validate_payload(payload: dict[str, Any]) -> None:
    periods = payload.get("periods", [])
    if len(periods) != 6:
        raise ExportError(f"Weekly image JSON must contain 6 periods; found {len(periods)}.")
    if periods[0].get("status") != "actual":
        raise ExportError("The first period must be the latest EIA actual.")
    if any(period.get("status") != "forecast" for period in periods[1:]):
        raise ExportError("The five periods after the actual must all be forecasts.")
    highlights = [period for period in periods if period.get("highlight")]
    if len(highlights) != 1 or highlights[0] != periods[1]:
        raise ExportError("Only the first forecast period may be highlighted.")
    actual = payload.get("inventory_changes", {}).get("actual", {})
    forecasts = payload.get("inventory_changes", {}).get("forecasts", [])
    if len(forecasts) != 2:
        raise ExportError("The JSON must contain the first two forecast inventory plots.")
    for chart in [actual, *forecasts]:
        if len(chart.get("labels", [])) != len(chart.get("values_mb", [])):
            raise ExportError(f"Chart labels and values do not align for {chart.get('week_ending')}.")
        if not chart.get("values_mb"):
            raise ExportError(f"Chart {chart.get('week_ending')} contains no values.")
    table_regions = payload.get("table", {}).get("regions", [])
    if len(table_regions) != 4:
        raise ExportError(f"Expected four table sections; found {len(table_regions)}.")


def display_week(period: str) -> str:
    return parse_date(period).strftime("%d-%b")


def title_week(period: str) -> str:
    return parse_date(period).strftime("%m/%d/%y")


def format_table_value(value: Any, unit: str) -> str:
    if value is None:
        return ""
    number = finite_number(value)
    if unit == "percent":
        return f"{number:.1f}%"
    if unit == "kb":
        magnitude = f"{abs(number):,.0f}"
        return f"({magnitude})" if number < 0 else magnitude
    if abs(number) >= 1000:
        return f"{number:,.1f}"
    if abs(number - round(number)) < 0.05:
        return f"{number:,.0f}"
    return f"{number:,.1f}"


def render_weekly_table(
    payload: dict[str, Any],
    output_path: Path,
    dpi: int,
    format_config: dict[str, Any],
) -> None:
    periods = payload["periods"]
    regions = payload["table"]["regions"]
    data_row_count = sum(len(region["rows"]) for region in regions)
    table_format = format_config["table"]
    colors = format_config["colors"]
    us_gap_rows = max(0.0, setting(table_format, "us_section_gap_rows"))
    repeat_us_header = bool(table_format.get("repeat_header_before_us", True))
    total_rows = (
        data_row_count
        + 1
        + us_gap_rows
        + (1 if repeat_us_header else 0)
    )

    fig = plt.figure(
        figsize=(setting(table_format, "width_in"), setting(table_format, "height_in")),
        facecolor=colors["white"],
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        setting(table_format, "title_x"),
        setting(table_format, "title_y"),
        payload["product"]["stats_title"],
        ha="left",
        va="top",
        fontsize=font_size(format_config, table_format, "title_font_size"),
        color=colors["title_red"],
        fontweight="normal",
    )

    left = setting(table_format, "left")
    right = setting(table_format, "right")
    top = setting(table_format, "top")
    bottom = setting(table_format, "bottom")
    width = right - left
    table_height = top - bottom
    row_h = table_height / total_rows
    region_share = setting(table_format, "region_column_share")
    metric_share = setting(table_format, "metric_column_share")
    if region_share <= 0 or metric_share <= 0 or region_share + metric_share >= 1:
        raise ExportError("Table column shares must be positive and total less than 1.0.")
    col_widths = [region_share, metric_share] + [
        (1.0 - region_share - metric_share) / 6.0
    ] * 6
    x_edges = [left]
    for col_width in col_widths:
        x_edges.append(x_edges[-1] + col_width * width)

    def cell(
        x0: float,
        y0: float,
        w: float,
        h: float,
        face: str,
        edge: str = colors["grid"],
        linewidth: float = 0.45,
    ) -> None:
        ax.add_patch(
            Rectangle(
                (x0, y0),
                w,
                h,
                facecolor=face,
                edgecolor=edge,
                linewidth=linewidth,
            )
        )

    def draw_period_header(header_y: float, left_label: str) -> None:
        cell(
            x_edges[0],
            header_y,
            x_edges[2] - x_edges[0],
            row_h,
            colors["header"],
            colors["ink"],
            0.8,
        )
        ax.text(
            (x_edges[0] + x_edges[2]) / 2,
            header_y + row_h / 2,
            left_label,
            ha="center",
            va="center",
            color=colors["white"],
            fontsize=font_size(format_config, table_format, "header_font_size"),
            fontweight="bold",
        )
        for index, period in enumerate(periods):
            x0, x1 = x_edges[index + 2], x_edges[index + 3]
            face = (
                colors["forecast_highlight"]
                if period.get("highlight")
                else colors["header"]
            )
            cell(x0, header_y, x1 - x0, row_h, face, colors["ink"], 0.8)
            ax.text(
                (x0 + x1) / 2,
                header_y + row_h / 2,
                display_week(period["week_ending"]),
                ha="center",
                va="center",
                color=(
                    colors["ink"] if period.get("highlight") else colors["white"]
                ),
                fontsize=font_size(format_config, table_format, "header_font_size"),
                fontweight="bold",
            )

    header_y = top - row_h
    draw_period_header(header_y, "")

    current_y = header_y
    for region in regions:
        if region["key"] == "us":
            gap_height = row_h * us_gap_rows
            if gap_height:
                ax.add_patch(
                    Rectangle(
                        (left, current_y - gap_height),
                        right - left,
                        gap_height,
                        facecolor=colors["white"],
                        edgecolor=colors["white"],
                        linewidth=0,
                    )
                )
                current_y -= gap_height
            if repeat_us_header:
                repeated_header_y = current_y - row_h
                draw_period_header(repeated_header_y, "")
                current_y = repeated_header_y
        region_top = current_y
        region_height = row_h * len(region["rows"])
        cell(
            x_edges[0],
            region_top - region_height,
            x_edges[1] - x_edges[0],
            region_height,
            colors["region_fill"],
            colors["ink"],
            0.85,
        )
        region_text = region["label"]
        ax.text(
            (x_edges[0] + x_edges[1]) / 2,
            region_top - region_height / 2,
            region_text,
            ha="center",
            va="center",
            fontsize=font_size(format_config, table_format, "region_font_size"),
            color=colors["ink"],
            fontweight="bold",
        )
        for row_index, row in enumerate(region["rows"]):
            y0 = current_y - row_h
            separator = row["unit"] == "separator"
            metric_face = colors["section_fill"] if separator else colors["white"]
            cell(x_edges[1], y0, x_edges[2] - x_edges[1], row_h, metric_face)
            if row["label"]:
                ax.text(
                    x_edges[2] - 0.008,
                    y0 + row_h / 2,
                    row["label"],
                    ha="right",
                    va="center",
                    fontsize=font_size(format_config, table_format, "body_font_size"),
                    color=colors["ink"],
                    fontstyle="italic",
                    fontweight="bold",
                )
            for period_index, period in enumerate(periods):
                x0, x1 = x_edges[period_index + 2], x_edges[period_index + 3]
                face = (
                    colors["section_fill"]
                    if separator
                    else colors["forecast_highlight"]
                    if period.get("highlight")
                    else colors["actual_fill"]
                    if period_index == 0
                    else colors["white"]
                )
                cell(x0, y0, x1 - x0, row_h, face)
                value = row["values"].get(period["week_ending"])
                text = format_table_value(value, row["unit"])
                color = (
                    colors["negative"]
                    if row["unit"] == "kb" and finite_number(value) < 0
                    else colors["ink"]
                )
                ax.text(
                    (x0 + x1) / 2,
                    y0 + row_h / 2,
                    text,
                    ha="center",
                    va="center",
                    fontsize=font_size(format_config, table_format, "body_font_size"),
                    color=color,
                    fontweight="bold" if row["key"] == "net_kb" else "normal",
                )
            current_y = y0
        ax.plot(
            [left, right],
            [current_y, current_y],
            color=colors["ink"],
            linewidth=1.05,
        )

    fig.savefig(output_path, dpi=dpi, facecolor=colors["white"])
    plt.close(fig)


def chart_axis_limits(values: list[float]) -> tuple[float, float]:
    data_min = min([0.0, *values])
    data_max = max([0.0, *values])
    magnitude = max(abs(data_min), abs(data_max), 0.25)
    span = max(data_max - data_min, magnitude)
    pad = max(span * 0.22, magnitude * 0.14, 0.18)
    lower = data_min - pad
    upper = data_max + pad
    if data_min >= 0:
        lower = -pad * 0.12
    if data_max <= 0:
        upper = pad * 0.12
    return lower, upper


def signed_tick(value: float, _position: int) -> str:
    if abs(value) < 0.005:
        return "0.00"
    return f"({abs(value):.2f})" if value < 0 else f"{value:.2f}"


def render_inventory_chart(
    chart: dict[str, Any],
    output_path: Path,
    dpi: int,
    format_config: dict[str, Any],
) -> None:
    chart_format = format_config["chart"]
    colors_config = format_config["colors"]
    values = [finite_number(value) for value in chart["values_mb"]]
    colors = [
        colors_config["positive"] if value >= 0 else colors_config["negative"]
        for value in values
    ]
    fig, ax = plt.subplots(
        figsize=(setting(chart_format, "width_in"), setting(chart_format, "height_in")),
        facecolor=colors_config["white"],
    )
    fig.subplots_adjust(
        left=setting(chart_format, "left"),
        right=setting(chart_format, "right"),
        bottom=setting(chart_format, "bottom"),
        top=setting(chart_format, "top"),
    )
    positions = list(range(len(values)))
    bars = ax.bar(
        positions,
        values,
        width=setting(chart_format, "bar_width"),
        color=colors,
        edgecolor=colors,
        linewidth=0.8,
        zorder=3,
    )
    lower, upper = chart_axis_limits(values)
    ax.set_ylim(lower, upper)
    ax.set_xlim(-0.62, len(values) - 0.38)
    ax.axhline(0, color="#8b9097", linewidth=0.85, zorder=2)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_formatter(FuncFormatter(signed_tick))
    ax.yaxis.grid(True, color=colors_config["grid"], linewidth=0.65, zorder=0)
    ax.set_xticks(
        positions,
        chart["labels"],
        fontsize=font_size(format_config, chart_format, "x_font_size"),
    )
    ax.tick_params(axis="x", length=0, pad=7)
    ax.tick_params(
        axis="y",
        labelsize=font_size(format_config, chart_format, "y_font_size"),
        length=0,
        pad=4,
    )
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#b6bbc2")
    ax.spines["bottom"].set_visible(False)
    status = "EIA Actuals" if chart["status"] == "actual" else "Forecast"
    title = f"{status} W/E {title_week(chart['week_ending'])} (MB)"
    ax.set_title(
        title,
        fontsize=font_size(format_config, chart_format, "title_font_size"),
        color=colors_config["ink"],
        pad=setting(chart_format, "title_pad"),
        fontweight="bold",
    )

    label_offset = setting(chart_format, "value_label_offset_points")
    for bar, value in zip(bars, values):
        ax.annotate(
            f"{value:.2f}",
            xy=(bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, label_offset if value >= 0 else -label_offset),
            textcoords="offset points",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=font_size(format_config, chart_format, "value_font_size"),
            color=colors_config["ink"],
            fontweight="bold",
            clip_on=False,
        )
    fig.savefig(output_path, dpi=dpi, facecolor=colors_config["white"])
    plt.close(fig)


def render_composite_slide(
    payload: dict[str, Any],
    table_path: Path,
    actual_path: Path,
    forecast_paths: list[Path],
    output_path: Path,
    dpi: int,
    format_config: dict[str, Any],
) -> None:
    # Keep the composite on an exact 16:9 PowerPoint canvas at every configured DPI.
    slide_format = format_config["slide"]
    colors = format_config["colors"]
    width_px = int(setting(slide_format, "width_px"))
    height_px = int(setting(slide_format, "height_px"))
    if width_px < 1280 or height_px < 720:
        raise ExportError("Slide canvas must be at least 1280 x 720 pixels.")
    placements_config = slide_format.get("placements", {})
    fig = plt.figure(
        figsize=(width_px / dpi, height_px / dpi),
        facecolor=colors["white"],
    )
    placements = [
        (table_path, placements_config.get("table")),
        (forecast_paths[0], placements_config.get("forecast_week_1")),
        (forecast_paths[1], placements_config.get("forecast_week_2")),
        (actual_path, placements_config.get("eia_actuals")),
    ]
    if bool(slide_format.get("enforce_equal_chart_size", True)):
        chart_bounds = [bounds for _, bounds in placements[1:]]
        if any(not isinstance(bounds, list) or len(bounds) != 4 for bounds in chart_bounds):
            raise ExportError(
                "Every slide chart placement must be [left, bottom, width, height]."
            )
        chart_sizes = {(float(bounds[2]), float(bounds[3])) for bounds in chart_bounds}
        if len(chart_sizes) != 1:
            raise ExportError(
                "Actuals and Forecast slide placements must use the same width and height."
            )
    for image_path, bounds in placements:
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ExportError(
                "Every slide placement must be [left, bottom, width, height]."
            )
        ax = fig.add_axes(bounds)
        ax.imshow(mpimg.imread(image_path))
        ax.axis("off")

    source = payload.get("source", {})
    actual_week = payload["periods"][0]["week_ending"]
    fig.text(
        setting(slide_format, "note_title_x"),
        setting(slide_format, "note_title_y"),
        f"Weekly {payload['product']['short_title']} Balance Statistics",
        fontsize=font_size(format_config, slide_format, "note_title_font_size"),
        color=colors["ink"],
        fontweight="bold",
        va="top",
    )
    fig.text(
        setting(slide_format, "note_body_x"),
        setting(slide_format, "note_body_y"),
        f"Latest EIA actual: W/E {title_week(actual_week)}\n"
        f"Forecast charts: first two weeks after the latest actual\n"
        f"Source bundle generated: {source.get('bundle_generated_at', 'n/a')}",
        fontsize=font_size(format_config, slide_format, "note_body_font_size"),
        color=colors["muted"],
        linespacing=setting(slide_format, "note_body_line_spacing"),
        va="top",
    )
    fig.savefig(output_path, dpi=dpi, facecolor=colors["white"])
    plt.close(fig)


def render_outputs(
    payload_path: Path,
    output_dir: Path,
    dpi: int,
    format_config: dict[str, Any],
) -> list[Path]:
    payload = load_json(payload_path)
    validate_payload(payload)
    product = payload["product"]["key"]
    individual_dir = output_dir / "individual_outputs"
    individual_dir.mkdir(parents=True, exist_ok=True)
    table_path = individual_dir / f"{product}_weekly_balance_table.png"
    actual_path = individual_dir / f"{product}_eia_actuals.png"
    forecast_paths = [
        individual_dir / f"{product}_forecast_week_1.png",
        individual_dir / f"{product}_forecast_week_2.png",
    ]
    slide_path = output_dir / f"{product}_weekly_stats_slide.png"

    # Remove files from the older flat layout after the dedicated individual
    # output folder has been introduced. The composite slide and JSON stay at
    # the week-repository root.
    for legacy_name in (
        f"{product}_weekly_balance_table.png",
        f"{product}_eia_actuals.png",
        f"{product}_forecast_week_1.png",
        f"{product}_forecast_week_2.png",
    ):
        legacy_path = output_dir / legacy_name
        if legacy_path.is_file():
            legacy_path.unlink()

    render_weekly_table(payload, table_path, dpi, format_config)
    render_inventory_chart(
        payload["inventory_changes"]["actual"], actual_path, dpi, format_config
    )
    for chart, path in zip(payload["inventory_changes"]["forecasts"], forecast_paths):
        render_inventory_chart(chart, path, dpi, format_config)
    render_composite_slide(
        payload,
        table_path,
        actual_path,
        forecast_paths,
        slide_path,
        dpi,
        format_config,
    )
    return [table_path, actual_path, *forecast_paths, slide_path]


def image_dimensions(path: Path) -> tuple[int, int]:
    image = mpimg.imread(path)
    return int(image.shape[1]), int(image.shape[0])


def write_manifest(
    payload_path: Path,
    images: list[Path],
    output_path: Path,
    dpi: int,
    format_config: dict[str, Any],
) -> None:
    payload = load_json(payload_path)
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "actual_week_ending": payload["periods"][0]["week_ending"],
        "product": payload["product"]["key"],
        "weekly_json": payload_path.name,
        "dpi": dpi,
        "format": format_config,
        "images": [
            {
                "file": image.relative_to(output_path.parent).as_posix(),
                "width_px": image_dimensions(image)[0],
                "height_px": image_dimensions(image)[1],
            }
            for image in images
        ],
    }
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def find_archive_payload(
    output_root: Path,
    product: str,
    requested_week: str | None,
) -> tuple[Path, Path]:
    if requested_week:
        parse_date(requested_week)
        archive_dir = output_root / requested_week
        payload_path = archive_dir / f"{product}_weekly_stats.json"
        if not payload_path.is_file():
            raise ExportError(f"No {product} weekly JSON exists for {requested_week}.")
        return archive_dir, payload_path

    candidates: list[tuple[str, Path, Path]] = []
    if output_root.is_dir():
        for archive_dir in output_root.iterdir():
            if not archive_dir.is_dir():
                continue
            try:
                parse_date(archive_dir.name)
            except ExportError:
                continue
            payload_path = archive_dir / f"{product}_weekly_stats.json"
            if payload_path.is_file():
                candidates.append((archive_dir.name, archive_dir, payload_path))
    if not candidates:
        raise ExportError(
            f"--render-only found no archived {product} weekly JSON below {output_root}."
        )
    _, archive_dir, payload_path = max(candidates, key=lambda item: item[0])
    return archive_dir, payload_path


def update_output_catalog(output_root: Path) -> Path:
    entries: list[dict[str, Any]] = []
    for archive_dir in sorted(output_root.iterdir(), reverse=True):
        if not archive_dir.is_dir():
            continue
        try:
            parse_date(archive_dir.name)
        except ExportError:
            continue
        for payload_path in sorted(archive_dir.glob("*_weekly_stats.json")):
            payload = load_json(payload_path)
            entries.append(
                {
                    "actual_week_ending": payload["periods"][0]["week_ending"],
                    "product": payload["product"]["key"],
                    "folder": archive_dir.name,
                    "weekly_json": payload_path.name,
                    "generated_at": payload.get("generated_at"),
                }
            )
    catalog_path = output_root / "index.json"
    catalog = {
        "schema_version": 1,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "weeks": entries,
    }
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return catalog_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate weekly balance table and inventory-change PNGs."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--balance-root", type=Path)
    parser.add_argument("--product", choices=["diesel", "jet"])
    parser.add_argument("--forecast-weeks", type=int)
    parser.add_argument("--dpi", type=int)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override the archive root; the actual week is still added below it.",
    )
    parser.add_argument(
        "--week",
        help="With --render-only, render this archived actual week (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Use an already-generated full bundle JSON without invoking npm.",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render from the existing weekly-only JSON in the output folder.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config.resolve())
    product = args.product or str(config.get("product", "diesel")).lower()
    if product not in PRODUCT_LAYOUTS:
        raise ExportError(f"Configuration product must be diesel or jet, not {product!r}.")
    forecast_weeks = args.forecast_weeks or int(config.get("forecast_weeks", 5))
    dpi = args.dpi or int(config.get("dpi", 180))
    if dpi < 96:
        raise ExportError("DPI must be at least 96 for readable slide output.")
    output_root = (
        args.output_dir.resolve()
        if args.output_dir
        else (PACKAGE_DIR / str(config.get("output_folder", "outputs"))).resolve()
    )
    output_root.mkdir(parents=True, exist_ok=True)
    format_config = config["format"]

    if not args.render_only:
        balance_root = (
            args.balance_root.resolve()
            if args.balance_root
            else find_balance_root(PACKAGE_DIR.parent)
        )
        should_build = bool(config.get("run_balance_json_builder", True)) and not args.skip_build
        existing_full_bundles = {
            path.resolve() for path in balance_root.glob("*/data/*_balance_bundle.json")
        }
        try:
            if should_build:
                run_balance_json_builder(balance_root)
            source_bundle = bundle_path(balance_root, product)
            bundle = load_json(source_bundle)
            payload = build_weekly_payload(bundle, source_bundle, forecast_weeks)
        finally:
            if should_build:
                # Full dashboard bundles are intermediate. Keep the durable weekly
                # archive and avoid leaving new debug files in the balance folders.
                for generated_bundle in balance_root.glob("*/data/*_balance_bundle.json"):
                    if generated_bundle.resolve() not in existing_full_bundles:
                        generated_bundle.unlink()
        actual_week = payload["periods"][0]["week_ending"]
        output_dir = output_root / actual_week
        output_dir.mkdir(parents=True, exist_ok=True)
        payload_path = output_dir / f"{product}_weekly_stats.json"
        payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Created weekly JSON: {payload_path}")
    else:
        output_dir, payload_path = find_archive_payload(output_root, product, args.week)

    images = render_outputs(payload_path, output_dir, dpi, format_config)
    manifest_path = output_dir / "manifest.json"
    write_manifest(payload_path, images, manifest_path, dpi, format_config)
    catalog_path = update_output_catalog(output_root)
    print("Created images:")
    for image in images:
        width, height = image_dimensions(image)
        print(f"  {image.name} ({width} x {height})")
    print(f"Created manifest: {manifest_path}")
    print(f"Updated weekly archive catalog: {catalog_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
