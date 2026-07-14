from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.request import Request, urlopen
from zipfile import ZipFile

from env_loader import load_env_files


load_env_files()


OUT_DIR = Path("eia_capacity")
RAW_DIR = OUT_DIR / "raw"
RAW_ZIP = RAW_DIR / "PET_capacity_bulk.zip"
DEFAULT_BULK_URL = "https://api.eia.gov/bulk/PET.zip"
BULK_URL = os.environ.get("EIA_CAPACITY_BULK_URL", "").strip() or DEFAULT_BULK_URL
START_MONTH = os.environ.get("EIA_CAPACITY_START", "").strip() or "2016-01"
END_MONTH = os.environ.get("EIA_CAPACITY_END", "").strip() or date.today().strftime("%Y-%m")
MATCH_PHRASE = "Downstream Charge Capacity as of January 1"
USER_AGENT = "python-pulls-eia-capacity/0.1 (monthly downstream capacity pull)"

LONG_OUTPUT = OUT_DIR / "downstream_charge_capacity_monthly.csv"
WIDE_OUTPUT = OUT_DIR / "downstream_charge_capacity_monthly_wide.csv"
ANNUAL_OUTPUT = OUT_DIR / "downstream_charge_capacity_annual_raw.csv"
HIGH_LEVEL_OUTPUT = OUT_DIR / "downstream_charge_capacity_high_level_monthly.csv"
HIGH_LEVEL_WIDE_OUTPUT = OUT_DIR / "downstream_charge_capacity_high_level_monthly_wide.csv"
GROUP_MAP_OUTPUT = OUT_DIR / "capacity_group_map.csv"
MANUAL_INPUT = OUT_DIR / "manual_capacity.csv"
MANUAL_TEMPLATE = OUT_DIR / "manual_capacity_template.csv"
MANIFEST = OUT_DIR / "manifest.json"

STATE_NAMES = {
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "District of Columbia",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
}

GEOGRAPHY_CODE_LABELS = {
    "NUS": ("U.S.", "us"),
    "R10": ("East Coast (PADD 1)", "padd"),
    "R1X": ("New England (PADD 1A)", "subpadd"),
    "R1Y": ("Central Atlantic (PADD 1B)", "subpadd"),
    "R1Z": ("Lower Atlantic (PADD 1C)", "subpadd"),
    "R20": ("Midwest (PADD 2)", "padd"),
    "R30": ("Gulf Coast (PADD 3)", "padd"),
    "R40": ("Rocky Mountain (PADD 4)", "padd"),
    "R50": ("West Coast (PADD 5)", "padd"),
}

LONG_COLUMNS = [
    "period_month",
    "series_id",
    "series_name",
    "geography_code",
    "geography",
    "geography_type",
    "capacity_type",
    "capacity_detail",
    "capacity_basis",
    "unit",
    "value_kbd",
    "source_value",
    "source_unit",
    "source_year",
    "last_updated",
    "capacity_group_id",
    "capacity_group",
    "source",
    "aggregate_eligible",
]

ANNUAL_COLUMNS = [
    "series_id",
    "series_name",
    "geography_code",
    "geography",
    "geography_type",
    "capacity_type",
    "capacity_detail",
    "capacity_basis",
    "source_year",
    "source_value",
    "source_unit",
    "value_kbd",
    "last_updated",
    "capacity_group_id",
    "capacity_group",
    "source",
    "aggregate_eligible",
]

MANUAL_COLUMNS = [
    "series_id",
    "period_month",
    "source_year",
    "geography_code",
    "geography",
    "geography_type",
    "capacity_group",
    "capacity_detail",
    "capacity_basis",
    "value_kbd",
    "source_value",
    "source_unit",
    "last_updated",
    "series_name",
    "aggregate_eligible",
]

HIGH_LEVEL_COLUMNS = [
    "period_month",
    "geography_code",
    "geography",
    "geography_type",
    "capacity_group_id",
    "capacity_group",
    "capacity_basis",
    "unit",
    "value_kbd",
    "source_series_count",
    "source",
    "source_series_ids",
    "last_updated",
]

GROUP_MAP_COLUMNS = [
    "capacity_type",
    "capacity_detail",
    "capacity_group_id",
    "capacity_group",
    "aggregate_eligible",
    "source_series_count",
]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def parse_month(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if not match:
        raise RuntimeError(f"Invalid month {value!r}; use YYYY-MM")
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise RuntimeError(f"Invalid month {value!r}; use YYYY-MM")
    return year, month


def normalize_period_month(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        parse_month(text)
        return f"{text}-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        parse_month(text[:7])
        return f"{text[:7]}-01"
    raise RuntimeError(f"Invalid period_month {value!r}; use YYYY-MM or YYYY-MM-DD")


def month_tuple(period_month: str) -> tuple[int, int]:
    normalized = normalize_period_month(period_month)
    return int(normalized[:4]), int(normalized[5:7])


def month_range(start: str, end: str) -> list[str]:
    start_year, start_month = parse_month(start)
    end_year, end_month = parse_month(end)
    if (end_year, end_month) < (start_year, start_month):
        raise RuntimeError(f"EIA_CAPACITY_END {end!r} is before EIA_CAPACITY_START {start!r}")
    months: list[str] = []
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}-01")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def fetch_bulk_zip() -> bytes:
    request = Request(BULK_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=180) as response:
        return response.read()


def parse_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {".", "--"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed == parsed else None


def series_geography_code(series_id: str) -> str:
    parts = series_id.split("_")
    if len(parts) < 2:
        return ""
    return parts[-2]


def infer_geography(series_id: str, name: str) -> tuple[str, str, str]:
    code = series_geography_code(series_id)
    if code in GEOGRAPHY_CODE_LABELS:
        label, geography_type = GEOGRAPHY_CODE_LABELS[code]
        return code, label, geography_type

    prefix = name.split(" Refinery ", 1)[0].strip()
    prefix = re.sub(r"\s+", " ", prefix)
    if prefix in STATE_NAMES:
        return code, prefix, "state"
    if prefix == "United States" or prefix == "U.S.":
        return code, "U.S.", "us"
    return code, prefix or "Other", "other"


def clean_series_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace(", Annual", "")).strip()


def capacity_detail(name: str) -> str:
    clean = clean_series_name(name)
    match = re.search(r" Refinery (.+?) Downstream Charge Capacity as of January 1", clean)
    if not match:
        return "Downstream Charge Capacity"
    return match.group(1).strip()


def snake(value: str) -> str:
    text = value.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def capacity_basis(unit: str) -> str:
    if unit == "Barrels per Calendar Day":
        return "calendar_day"
    if unit == "Barrels per Stream Day":
        return "stream_day"
    return snake(unit) or "unknown"


def value_kbd(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 1000.0, 3)


def parse_bool(value: object, default: bool = True) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    raise RuntimeError(f"Invalid boolean value {value!r}")


def capacity_group_for_detail(detail: str) -> tuple[str, str]:
    capacity_type = snake(detail)
    if "catalytic_cracking" in capacity_type:
        return "fcc_capacity", "FCC Capacity"
    if "catalytic_hydrocracking" in capacity_type:
        return "hydrocracking_capacity", "Hydrocracking Capacity"
    if "catalytic_reforming" in capacity_type:
        return "reforming_capacity", "Reforming Capacity"
    if "thermal_cracking" in capacity_type and "coking" in capacity_type:
        return "coking_capacity", "Coking Capacity"
    if "thermal_cracking" in capacity_type and "visbreaking" in capacity_type:
        return "visbreaking_capacity", "Visbreaking Capacity"
    if capacity_type == "thermal_cracking":
        return "thermal_cracking_capacity", "Thermal Cracking Capacity"
    if "catalytic_hydrotreating" in capacity_type:
        return "hydrotreating_capacity", "Hydrotreating Capacity"
    if "desulfurization" in capacity_type:
        return "desulfurization_capacity", "Desulfurization Capacity"
    if "vacuum_distillation" in capacity_type:
        return "vacuum_distillation_capacity", "Vacuum Distillation Capacity"
    if "fuels_solvent_deasp" in capacity_type:
        return "solvent_deasphalting_capacity", "Solvent Deasphalting Capacity"
    label = re.sub(r"\s+", " ", detail.replace("/", " ")).strip() or "Other"
    return f"{capacity_type or 'other'}_capacity", f"{label} Capacity"


def aggregate_eligible_for_detail(detail: str) -> bool:
    capacity_type = snake(detail)
    if "catalytic_cracking" in capacity_type:
        return "fresh_feed" in capacity_type
    if capacity_type.startswith("catalytic_hydrocracking"):
        return capacity_type == "catalytic_hydrocracking"
    if capacity_type.startswith("catalytic_reforming"):
        return capacity_type == "catalytic_reforming"
    if "thermal_cracking" in capacity_type and "coking" in capacity_type:
        return capacity_type == "thermal_cracking_coking"
    if capacity_type in {"thermal_cracking", "thermal_cracking_visbreaking"}:
        return True
    return True


def group_metadata(detail: str, override_group: str = "", aggregate_eligible: object = "") -> dict[str, str]:
    if override_group.strip():
        group_name = re.sub(r"\s+", " ", override_group.strip())
        group_id = snake(group_name)
        if not group_id.endswith("capacity"):
            group_id = f"{group_id}_capacity"
    else:
        group_id, group_name = capacity_group_for_detail(detail)
    eligible = aggregate_eligible_for_detail(detail) if str(aggregate_eligible or "").strip() == "" else parse_bool(aggregate_eligible)
    return {
        "capacity_group_id": group_id,
        "capacity_group": group_name,
        "aggregate_eligible": "true" if eligible else "false",
    }


def iter_bulk_items(zip_path: Path):
    with ZipFile(zip_path) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise RuntimeError(f"{zip_path} must contain exactly one txt file")
        with archive.open(names[0]) as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"{zip_path}:{line_number} is not valid JSON") from exc


def selected_capacity_items(zip_path: Path) -> list[dict[str, Any]]:
    items = []
    for item in iter_bulk_items(zip_path):
        name = str(item.get("name", ""))
        if item.get("f") != "A" or MATCH_PHRASE not in name:
            continue
        units = str(item.get("units", "")).strip()
        if units not in {"Barrels per Calendar Day", "Barrels per Stream Day"}:
            continue
        items.append(item)
    return sorted(items, key=lambda item: (infer_geography(str(item.get("series_id", "")), str(item.get("name", "")))[1], str(item.get("name", "")), str(item.get("series_id", ""))))


def annual_rows_for_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[int, dict[str, Any]]]]:
    rows: list[dict[str, Any]] = []
    values_by_series: dict[str, dict[int, dict[str, Any]]] = {}
    for item in items:
        series_id = str(item.get("series_id", "")).strip()
        name = clean_series_name(str(item.get("name", "")))
        units = str(item.get("units", "")).strip()
        geography_code, geography, geography_type = infer_geography(series_id, name)
        detail = capacity_detail(name)
        annual_values: dict[int, dict[str, Any]] = {}
        for period, raw_value in item.get("data", []):
            year_text = str(period).strip()
            if not re.fullmatch(r"\d{4}", year_text):
                continue
            source_value = parse_number(raw_value)
            year = int(year_text)
            group = group_metadata(detail)
            row = {
                "series_id": series_id,
                "series_name": name,
                "geography_code": geography_code,
                "geography": geography,
                "geography_type": geography_type,
                "capacity_type": snake(detail),
                "capacity_detail": detail,
                "capacity_basis": capacity_basis(units),
                "source_year": year,
                "source_value": "" if source_value is None else source_value,
                "source_unit": units,
                "value_kbd": "" if source_value is None else f"{value_kbd(source_value):.3f}",
                "last_updated": str(item.get("last_updated", "")),
                "capacity_group_id": group["capacity_group_id"],
                "capacity_group": group["capacity_group"],
                "source": "eia",
                "aggregate_eligible": group["aggregate_eligible"],
            }
            annual_values[year] = row
            rows.append(row)
        values_by_series[series_id] = annual_values
    rows.sort(key=lambda row: (row["geography"], row["capacity_detail"], row["capacity_basis"], row["source_year"], row["series_id"]))
    return rows, values_by_series


def monthly_rows_for_items(items: list[dict[str, Any]], values_by_series: dict[str, dict[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    months = month_range(START_MONTH, END_MONTH)
    for item in items:
        series_id = str(item.get("series_id", "")).strip()
        annual_values = values_by_series.get(series_id, {})
        if not annual_values:
            continue
        years = sorted(annual_values)
        latest: dict[str, Any] | None = None
        year_index = 0
        for period_month in months:
            year = int(period_month[:4])
            while year_index < len(years) and years[year_index] <= year:
                latest = annual_values[years[year_index]]
                year_index += 1
            if latest is None:
                continue
            rows.append(
                {
                    "period_month": period_month,
                    "series_id": series_id,
                    "series_name": latest["series_name"],
                    "geography_code": latest["geography_code"],
                    "geography": latest["geography"],
                    "geography_type": latest["geography_type"],
                    "capacity_type": latest["capacity_type"],
                    "capacity_detail": latest["capacity_detail"],
                    "capacity_basis": latest["capacity_basis"],
                    "unit": "Thousand Barrels per Day",
                    "value_kbd": latest["value_kbd"],
                    "source_value": latest["source_value"],
                    "source_unit": latest["source_unit"],
                    "source_year": latest["source_year"],
                    "last_updated": latest["last_updated"],
                    "capacity_group_id": latest["capacity_group_id"],
                    "capacity_group": latest["capacity_group"],
                    "source": "eia",
                    "aggregate_eligible": latest["aggregate_eligible"],
                }
            )
    rows.sort(key=lambda row: (row["period_month"], row["geography"], row["capacity_detail"], row["capacity_basis"], row["series_id"]))
    return rows


def ensure_manual_files() -> None:
    if not MANUAL_INPUT.exists():
        write_csv(MANUAL_INPUT, MANUAL_COLUMNS, [])
    if not MANUAL_TEMPLATE.exists():
        write_csv(
            MANUAL_TEMPLATE,
            MANUAL_COLUMNS,
            [
                {
                    "series_id": "manual_us_fcc_capacity_stream_day",
                    "period_month": "2026-01",
                    "source_year": "2026",
                    "geography_code": "NUS",
                    "geography": "U.S.",
                    "geography_type": "us",
                    "capacity_group": "FCC Capacity",
                    "capacity_detail": "Catalytic Cracking, Fresh Feed",
                    "capacity_basis": "stream_day",
                    "value_kbd": "0.000",
                    "source_value": "0.000",
                    "source_unit": "Thousand Barrels per Day",
                    "last_updated": "",
                    "series_name": "Manual U.S. Refinery Catalytic Cracking, Fresh Feed Downstream Charge Capacity",
                    "aggregate_eligible": "true",
                }
            ],
        )


def infer_manual_geography(row: dict[str, str]) -> tuple[str, str, str]:
    code = str(row.get("geography_code", "")).strip()
    geography = re.sub(r"\s+", " ", str(row.get("geography", "")).strip())
    geography_type = snake(str(row.get("geography_type", "")).strip())
    if code in GEOGRAPHY_CODE_LABELS:
        label, inferred_type = GEOGRAPHY_CODE_LABELS[code]
        return code, geography or label, geography_type or inferred_type
    if geography in STATE_NAMES:
        return code, geography, geography_type or "state"
    if geography in {"U.S.", "United States"}:
        return code or "NUS", "U.S.", geography_type or "us"
    if geography:
        return code, geography, geography_type or "other"
    raise RuntimeError("Manual capacity rows must include geography or a known geography_code")


def manual_capacity_basis(row: dict[str, str]) -> str:
    basis = snake(str(row.get("capacity_basis", "")).strip())
    if basis:
        return basis
    source_unit = str(row.get("source_unit", "")).strip()
    if source_unit:
        return capacity_basis(source_unit)
    return "stream_day"


def manual_value(row: dict[str, str]) -> tuple[float, str, str]:
    value = parse_number(row.get("value_kbd"))
    source_value = parse_number(row.get("source_value"))
    source_unit = str(row.get("source_unit", "")).strip() or "Thousand Barrels per Day"
    if value is not None:
        return round(value, 3), "" if source_value is None else f"{source_value:.3f}", source_unit
    if source_value is None:
        raise RuntimeError("Manual capacity rows must include value_kbd or source_value")
    if source_unit in {"Barrels per Calendar Day", "Barrels per Stream Day"}:
        converted = value_kbd(source_value)
        if converted is None:
            raise RuntimeError("Manual source_value could not be converted to kbd")
        return converted, f"{source_value:.3f}", source_unit
    if source_unit in {"Thousand Barrels per Day", "kbd", "KBD"}:
        return round(source_value, 3), f"{source_value:.3f}", source_unit
    raise RuntimeError(f"Manual capacity source_unit {source_unit!r} is not supported")


def manual_period_month(row: dict[str, str]) -> str:
    period_month = str(row.get("period_month", "")).strip()
    if period_month:
        return normalize_period_month(period_month)
    source_year = str(row.get("source_year", "")).strip()
    if re.fullmatch(r"\d{4}", source_year):
        return f"{source_year}-01-01"
    raise RuntimeError("Manual capacity rows must include period_month or source_year")


def manual_series_id(
    row: dict[str, str],
    geography_code: str,
    geography: str,
    capacity_group_id: str,
    capacity_basis_value: str,
) -> str:
    explicit = str(row.get("series_id", "")).strip()
    if explicit:
        return explicit
    base = f"{geography_code or geography}_{capacity_group_id}_{capacity_basis_value}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"manual_{snake(base)}_{digest}"


def manual_base_rows(generated_at: str) -> list[dict[str, Any]]:
    ensure_manual_files()
    rows: list[dict[str, Any]] = []
    with MANUAL_INPUT.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for line_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            try:
                geography_code, geography, geography_type = infer_manual_geography(row)
                detail = re.sub(r"\s+", " ", str(row.get("capacity_detail", "")).strip())
                if not detail:
                    detail = re.sub(r"\s+", " ", str(row.get("capacity_group", "")).replace("Capacity", "").strip())
                if not detail:
                    detail = "Manual Downstream Charge Capacity"
                group = group_metadata(detail, str(row.get("capacity_group", "")).strip(), row.get("aggregate_eligible", ""))
                basis = manual_capacity_basis(row)
                kbd, source_value, source_unit = manual_value(row)
                period_month = manual_period_month(row)
                source_year = str(row.get("source_year", "")).strip() or period_month[:4]
                series_id = manual_series_id(row, geography_code, geography, group["capacity_group_id"], basis)
                series_name = str(row.get("series_name", "")).strip()
                if not series_name:
                    series_name = f"Manual {geography} Refinery {detail} Downstream Charge Capacity"
                rows.append(
                    {
                        "period_month": period_month,
                        "series_id": series_id,
                        "series_name": series_name,
                        "geography_code": geography_code,
                        "geography": geography,
                        "geography_type": geography_type,
                        "capacity_type": snake(detail),
                        "capacity_detail": detail,
                        "capacity_basis": basis,
                        "unit": "Thousand Barrels per Day",
                        "value_kbd": f"{kbd:.3f}",
                        "source_value": source_value if source_value else f"{kbd:.3f}",
                        "source_unit": source_unit,
                        "source_year": source_year,
                        "last_updated": str(row.get("last_updated", "")).strip() or generated_at,
                        "capacity_group_id": group["capacity_group_id"],
                        "capacity_group": group["capacity_group"],
                        "source": "manual",
                        "aggregate_eligible": group["aggregate_eligible"],
                        "_line_number": line_number,
                    }
                )
            except RuntimeError as exc:
                raise RuntimeError(f"{MANUAL_INPUT}:{line_number}: {exc}") from exc
    return rows


def manual_monthly_rows(base_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not base_rows:
        return []
    rows: list[dict[str, Any]] = []
    months = month_range(START_MONTH, END_MONTH)
    points_by_series: dict[str, list[dict[str, Any]]] = {}
    for row in base_rows:
        points_by_series.setdefault(str(row["series_id"]), []).append(row)
    for series_id, points in points_by_series.items():
        points.sort(key=lambda row: (month_tuple(str(row["period_month"])), int(row.get("_line_number", 0))))
        latest: dict[str, Any] | None = None
        point_index = 0
        for period_month in months:
            current = month_tuple(period_month)
            while point_index < len(points) and month_tuple(str(points[point_index]["period_month"])) <= current:
                latest = points[point_index]
                point_index += 1
            if latest is None:
                continue
            out = {key: value for key, value in latest.items() if not key.startswith("_")}
            out["period_month"] = period_month
            rows.append(out)
    rows.sort(key=lambda row: (row["period_month"], row["geography"], row["capacity_detail"], row["capacity_basis"], row["series_id"]))
    return rows


def merge_monthly_rows(eia_rows: list[dict[str, Any]], manual_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {
        (str(row["period_month"]), str(row["series_id"])): row for row in eia_rows
    }
    for row in manual_rows:
        rows_by_key[(str(row["period_month"]), str(row["series_id"]))] = row
    rows = list(rows_by_key.values())
    rows.sort(key=lambda row: (row["period_month"], row["geography"], row["capacity_detail"], row["capacity_basis"], row["series_id"]))
    return rows


def detail_wide_column_names(monthly_rows: list[dict[str, Any]]) -> dict[str, str]:
    series_rows: dict[str, dict[str, Any]] = {}
    for row in monthly_rows:
        series_id = str(row["series_id"])
        series_rows.setdefault(series_id, row)
    base_names: dict[str, str] = {}
    counts: dict[str, int] = {}
    for series_id, row in series_rows.items():
        basis = str(row["capacity_basis"]).replace("_", " ")
        base = f"{row['geography']} {row['capacity_detail']} ({basis} kbd)"
        base_names[series_id] = base
        counts[base] = counts.get(base, 0) + 1
    return {series_id: base if counts[base] == 1 else f"{base} [{series_id}]" for series_id, base in base_names.items()}


def write_wide(monthly_rows: list[dict[str, Any]]) -> int:
    names_by_series = detail_wide_column_names(monthly_rows)
    series_rows: dict[str, dict[str, Any]] = {}
    for row in monthly_rows:
        series_rows.setdefault(str(row["series_id"]), row)
    series_order = sorted(
        names_by_series,
        key=lambda series_id: (
            series_rows[series_id]["geography"],
            series_rows[series_id]["capacity_detail"],
            series_rows[series_id]["capacity_basis"],
            series_id,
        ),
    )
    fieldnames = ["period_month", *[names_by_series[series_id] for series_id in series_order]]
    rows_by_month: dict[str, dict[str, Any]] = {}
    for row in monthly_rows:
        period_month = str(row["period_month"])
        out = rows_by_month.setdefault(period_month, {"period_month": period_month})
        out[names_by_series[str(row["series_id"])]] = row["value_kbd"]
    for row in rows_by_month.values():
        for fieldname in fieldnames:
            row.setdefault(fieldname, "")
    rows = [rows_by_month[period] for period in sorted(rows_by_month)]
    write_csv(WIDE_OUTPUT, fieldnames, rows)
    return len(rows)


def high_level_rows(monthly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str, str], dict[str, Any]] = {}
    source_series: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
    sources: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
    for row in monthly_rows:
        if str(row.get("aggregate_eligible", "")).lower() != "true":
            continue
        value = parse_number(row.get("value_kbd"))
        if value is None:
            continue
        key = (
            str(row["period_month"]),
            str(row["geography_code"]),
            str(row["geography"]),
            str(row["geography_type"]),
            str(row["capacity_group_id"]),
            str(row["capacity_group"]),
            str(row["capacity_basis"]),
        )
        out = grouped.setdefault(
            key,
            {
                "period_month": row["period_month"],
                "geography_code": row["geography_code"],
                "geography": row["geography"],
                "geography_type": row["geography_type"],
                "capacity_group_id": row["capacity_group_id"],
                "capacity_group": row["capacity_group"],
                "capacity_basis": row["capacity_basis"],
                "unit": "Thousand Barrels per Day",
                "_value": 0.0,
                "last_updated": "",
            },
        )
        out["_value"] += value
        source_series.setdefault(key, set()).add(str(row["series_id"]))
        sources.setdefault(key, set()).add(str(row.get("source", "eia")))
        if str(row.get("last_updated", "")) > str(out.get("last_updated", "")):
            out["last_updated"] = row.get("last_updated", "")
    rows: list[dict[str, Any]] = []
    for key, row in grouped.items():
        source_labels = sorted(sources.get(key, set()))
        series_ids = sorted(source_series.get(key, set()))
        rows.append(
            {
                "period_month": row["period_month"],
                "geography_code": row["geography_code"],
                "geography": row["geography"],
                "geography_type": row["geography_type"],
                "capacity_group_id": row["capacity_group_id"],
                "capacity_group": row["capacity_group"],
                "capacity_basis": row["capacity_basis"],
                "unit": row["unit"],
                "value_kbd": f"{row['_value']:.3f}",
                "source_series_count": len(series_ids),
                "source": source_labels[0] if len(source_labels) == 1 else "mixed",
                "source_series_ids": ";".join(series_ids),
                "last_updated": row["last_updated"],
            }
        )
    rows.sort(key=lambda row: (row["period_month"], row["geography"], row["capacity_group"], row["capacity_basis"]))
    return rows


def high_level_wide_column_names(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], str]:
    base_names: dict[tuple[str, str, str, str], str] = {}
    counts: dict[str, int] = {}
    for row in rows:
        key = (
            str(row["geography_code"]),
            str(row["geography"]),
            str(row["capacity_group_id"]),
            str(row["capacity_basis"]),
        )
        basis = str(row["capacity_basis"]).replace("_", " ")
        base = f"{row['geography']} {row['capacity_group']} ({basis} kbd)"
        if key not in base_names:
            base_names[key] = base
            counts[base] = counts.get(base, 0) + 1
    return {key: base if counts[base] == 1 else f"{base} [{key[0]}]" for key, base in base_names.items()}


def write_high_level_wide(rows: list[dict[str, Any]]) -> int:
    names_by_key = high_level_wide_column_names(rows)
    key_order = sorted(names_by_key, key=lambda key: (key[1], names_by_key[key], key[0], key[3]))
    fieldnames = ["period_month", *[names_by_key[key] for key in key_order]]
    rows_by_month: dict[str, dict[str, Any]] = {}
    for row in rows:
        period_month = str(row["period_month"])
        key = (
            str(row["geography_code"]),
            str(row["geography"]),
            str(row["capacity_group_id"]),
            str(row["capacity_basis"]),
        )
        out = rows_by_month.setdefault(period_month, {"period_month": period_month})
        out[names_by_key[key]] = row["value_kbd"]
    for row in rows_by_month.values():
        for fieldname in fieldnames:
            row.setdefault(fieldname, "")
    output_rows = [rows_by_month[period] for period in sorted(rows_by_month)]
    write_csv(HIGH_LEVEL_WIDE_OUTPUT, fieldnames, output_rows)
    return len(output_rows)


def capacity_group_map_rows(monthly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: dict[tuple[str, str, str, str, str], set[str]] = {}
    for row in monthly_rows:
        key = (
            str(row["capacity_type"]),
            str(row["capacity_detail"]),
            str(row["capacity_group_id"]),
            str(row["capacity_group"]),
            str(row["aggregate_eligible"]),
        )
        details.setdefault(key, set()).add(str(row["series_id"]))
    rows = [
        {
            "capacity_type": key[0],
            "capacity_detail": key[1],
            "capacity_group_id": key[2],
            "capacity_group": key[3],
            "aggregate_eligible": key[4],
            "source_series_count": len(series_ids),
        }
        for key, series_ids in details.items()
    ]
    rows.sort(key=lambda row: (row["capacity_group"], row["capacity_detail"], row["aggregate_eligible"]))
    return rows


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    content = fetch_bulk_zip()
    RAW_ZIP.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    items = selected_capacity_items(RAW_ZIP)
    annual_rows, values_by_series = annual_rows_for_items(items)
    eia_monthly_rows = monthly_rows_for_items(items, values_by_series)
    manual_points = manual_base_rows(generated_at)
    manual_rows = manual_monthly_rows(manual_points)
    monthly_rows = merge_monthly_rows(eia_monthly_rows, manual_rows)
    high_level = high_level_rows(monthly_rows)
    group_map = capacity_group_map_rows(monthly_rows)
    write_csv(ANNUAL_OUTPUT, ANNUAL_COLUMNS, annual_rows)
    write_csv(LONG_OUTPUT, LONG_COLUMNS, monthly_rows)
    write_csv(HIGH_LEVEL_OUTPUT, HIGH_LEVEL_COLUMNS, high_level)
    write_csv(GROUP_MAP_OUTPUT, GROUP_MAP_COLUMNS, group_map)
    wide_rows = write_wide(monthly_rows)
    high_level_wide_rows = write_high_level_wide(high_level)
    write_json(
        MANIFEST,
        {
            "pipeline_name": "eia_downstream_charge_capacity",
            "generated_at": generated_at,
            "source_url": BULK_URL,
            "raw_zip": {
                "path": str(RAW_ZIP),
                "bytes": RAW_ZIP.stat().st_size,
                "sha256": digest,
            },
            "start_month": START_MONTH,
            "end_month": END_MONTH,
            "series_count": len(items),
            "annual_rows": len(annual_rows),
            "eia_monthly_rows": len(eia_monthly_rows),
            "manual_point_rows": len(manual_points),
            "manual_monthly_rows": len(manual_rows),
            "monthly_rows": len(monthly_rows),
            "high_level_monthly_rows": len(high_level),
            "capacity_group_rows": len(group_map),
            "wide_rows": wide_rows,
            "high_level_wide_rows": high_level_wide_rows,
            "manual_input": {
                "path": str(MANUAL_INPUT),
                "template": str(MANUAL_TEMPLATE),
                "mode": "applied" if manual_points else "empty",
            },
            "outputs": {
                "annual_raw": str(ANNUAL_OUTPUT),
                "monthly_long": str(LONG_OUTPUT),
                "monthly_wide": str(WIDE_OUTPUT),
                "high_level_monthly": str(HIGH_LEVEL_OUTPUT),
                "high_level_monthly_wide": str(HIGH_LEVEL_WIDE_OUTPUT),
                "capacity_group_map": str(GROUP_MAP_OUTPUT),
            },
            "forward_fill": "Annual EIA downstream charge capacity values are assigned to every month in their source year and carried forward until a newer annual value exists.",
            "manual_forward_fill": "Rows in eia_capacity/manual_capacity.csv are forward-filled monthly from period_month or source_year and override EIA rows with the same period_month and series_id.",
        },
    )
    print(
        f"eia capacity series={len(items)} annual_rows={len(annual_rows)} "
        f"monthly_rows={len(monthly_rows)} high_level_rows={len(high_level)} "
        f"manual_points={len(manual_points)} latest={END_MONTH} output={LONG_OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
