from __future__ import annotations

from calendar import monthrange
from contextlib import contextmanager
import csv
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from zipfile import ZipFile

os.environ.setdefault("ARROW_USER_SIMD_LEVEL", "NONE")

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


WEEKLY_DIESEL_OUTPUT = "diesel.csv"
WEEKLY_JET_OUTPUT = "jet.csv"
WEEKLY_GASOLINE_OUTPUT = "gasoline.csv"
MONTHLY_GASOLINE_OUTPUT = "gasoline.csv"
WEEKLY_RAW_EXCEL_OUTPUT = "raw.csv.tar.xz"
MONTHLY_DIESEL_OUTPUT = "diesel.csv"
MONTHLY_JET_OUTPUT = "jet.csv"
MONTHLY_BULK_SOURCE = Path("PET.zip")
MONTHLY_START = "201601"
MONTHLY_REGION_PREFIXES = [
    "East Coast (PADD 1)",
    "East Coast (PAD I)",
    "New England (PADD 1A)",
    "Central Atlantic (PADD 1B)",
    "Lower Atlantic (PADD 1C)",
    "Midwest (PADD 2)",
    "Gulf Coast (PADD 3)",
    "Rocky Mountain (PADD 4)",
    "Rocky Mountains (PADD 4)",
    "West Coast (PADD 5)",
    "U.S.",
]
MONTHLY_COMMON_PHRASES = [
    "Refinery Net Input of Crude Oil, Monthly",
    "Gross Inputs to",
    "Operable Crude Oil Distillation Capacity",
    "Operating Crude Oil Distillation Capacity",
    "Idle Crude Oil Distillation Capacity",
    "Percent Utilization of Refinery Operable Capacity",
    "Downstream Processing of Fresh Feed Input by",
]
MONTHLY_ANNUAL_CAPACITY_PHRASES = [
    "Refinery Catalytic Cracking, Fresh Feed Downstream Charge Capacity as of January 1",
    "Refinery Catalytic Hydrocracking Downstream Charge Capacity as of January 1",
    "Refinery Catalytic Reforming Downstream Charge Capacity as of January 1",
    "Refinery Thermal Cracking, Coking Downstream Charge Capacity as of January 1",
]
MONTHLY_EXPORT_PADD_CATEGORIES = {
    "East Coast (PADD 1)": ["Europe", "Other"],
    "Gulf Coast (PADD 3)": ["Africa", "Europe", "Latin America", "Other"],
    "West Coast (PADD 5)": ["Latin America", "Other"],
}
MONTHLY_GASOLINE_EXPORT_PADD_CATEGORIES = {
    "Gulf Coast (PADD 3)": ["Africa", "Latin America", "Other"],
}
MONTHLY_IMPORT_PADD_CATEGORIES = {
    "Distillate Fuel Oil": {
        "East Coast (PADD 1)": ["Canada", "Latin America", "Other"],
        "Midwest (PADD 2)": [],
        "Gulf Coast (PADD 3)": [],
        "Rocky Mountain (PADD 4)": [],
        "West Coast (PADD 5)": ["Asia including India", "Other"],
    },
    "Kerosene-Type Jet Fuel": {
        "East Coast (PADD 1)": ["Canada", "Africa", "Other"],
        "Midwest (PADD 2)": [],
        "Gulf Coast (PADD 3)": [],
        "Rocky Mountain (PADD 4)": [],
        "West Coast (PADD 5)": ["Asia including India", "Other"],
    },
    "Finished Motor Gasoline": {
        "East Coast (PADD 1)": ["Europe", "Africa", "Middle East", "Canada/Other"],
        "West Coast (PADD 5)": ["Asia including India", "Other"],
    },
    "Gasoline Blending Components": {
        "East Coast (PADD 1)": ["Europe", "Africa", "Middle East", "Canada/Other"],
        "West Coast (PADD 5)": ["Asia including India", "Other"],
    },
    "Fuel Ethanol": {
        "East Coast (PADD 1)": ["Europe", "Africa", "Middle East", "Canada/Other"],
        "West Coast (PADD 5)": ["Asia including India", "Other"],
    },
}
AFRICA_EXPORT_COUNTRIES = {
    "Algeria",
    "Angola",
    "Benin",
    "Cameroon",
    "Djibouti",
    "Egypt",
    "Equatorial Guinea",
    "Gabon",
    "Gambia",
    "Ghana",
    "Guinea",
    "Ivory Coast (Cote d'Ivore)",
    "Kenya",
    "Liberia",
    "Libya",
    "Mali",
    "Mauritania",
    "Morocco",
    "Mozambique",
    "Namibia",
    "Nigeria",
    "Sao Tome and Principe",
    "Senegal",
    "Seychelles",
    "Sierra Leone",
    "South Africa",
    "Togo",
    "Tunisia",
    "Uganda",
}
EUROPE_EXPORT_COUNTRIES = {
    "Austria",
    "Belgium",
    "Bulgaria",
    "Croatia",
    "Cyprus",
    "Czechia",
    "Denmark",
    "Estonia",
    "Finland",
    "France",
    "Georgia",
    "Germany",
    "Gibraltar",
    "Greece",
    "Hungary",
    "Iceland",
    "Ireland",
    "Italy",
    "Latvia",
    "Lithuania",
    "Luxembourg",
    "Macedonia",
    "Malta",
    "Monaco",
    "Montenegro",
    "Netherlands",
    "Norway",
    "Poland",
    "Portugal",
    "Romania",
    "Russia",
    "Slovakia",
    "Slovenia",
    "Spain",
    "Sweden",
    "Switzerland",
    "Turkey",
    "Turkiye",
    "Ukraine",
    "United Kingdom",
}
LATIN_AMERICA_EXPORT_COUNTRIES = {
    "Anguilla",
    "Antigua and Barbuda",
    "Argentina",
    "Aruba",
    "Bahama Islands",
    "Barbados",
    "Belize",
    "Bermuda",
    "Bolivia",
    "Brazil",
    "British Virgin Islands",
    "Cayman Islands",
    "Chile",
    "Colombia",
    "Costa Rica",
    "Cuba",
    "Curacao",
    "Dominica",
    "Dominican Republic",
    "Ecuador",
    "El Salvador",
    "Falkland Islands",
    "Grenada",
    "Guadeloupe",
    "Guatemala",
    "Guyana",
    "Haiti",
    "Honduras",
    "Jamaica",
    "Martinique",
    "Mexico",
    "Montserrat",
    "Netherlands Antilles",
    "Nicaragua",
    "Panama",
    "Paraguay",
    "Peru",
    "Puerto Rico",
    "Saint Kitts and Nevis",
    "Saint Lucia",
    "Saint Vincent and the Grenadines",
    "Sint Maarten",
    "Suriname",
    "Trinidad and Tobago",
    "Turks and Caicos Islands",
    "Uruguay",
    "Venezuela",
    "Virgin Islands",
}
ASIA_EXPORT_COUNTRIES = {
    "Afghanistan",
    "Armenia",
    "Azerbaijan",
    "Bahrain",
    "Bangladesh",
    "Brunei",
    "Burma",
    "Cambodia",
    "China",
    "Hong Kong",
    "India",
    "Indonesia",
    "Iraq",
    "Israel",
    "Japan",
    "Jordan",
    "Kazakhstan",
    "Korea",
    "Kuwait",
    "Kyrgyzstan",
    "Lebanon",
    "Macau S.A.R.",
    "Malaysia",
    "Maldives",
    "Mongolia",
    "Oman",
    "Pakistan",
    "Persian Gulf Countries",
    "Philippines",
    "Qatar",
    "Russia",
    "Saudi Arabia",
    "Singapore",
    "Sri Lanka",
    "Syria",
    "Taiwan",
    "Thailand",
    "Turkiye",
    "Turkey",
    "Turkmenistan",
    "United Arab Emirates",
    "Uzbekistan",
    "Vietnam",
}
MIDDLE_EAST_EXPORT_COUNTRIES = {
    "Bahrain",
    "Iran",
    "Iraq",
    "Israel",
    "Jordan",
    "Kuwait",
    "Lebanon",
    "Oman",
    "Persian Gulf Countries",
    "Qatar",
    "Saudi Arabia",
    "Syria",
    "United Arab Emirates",
    "Yemen",
}
MONTHLY_PRODUCT_PHRASES = [
    "Ending Stocks of {product}",
    "Net Receipts by Pipeline, Tanker, and Barge from Other PADDs of {product}",
    "Product Supplied of {product}",
    "Receipts by Pipeline from",
    "Receipts by Pipeline, Tanker, and Barge from",
    "Receipts by Tanker and Barge from",
    "Refinery and Blender Net Production of {product}",
    "Shipments by Pipeline, Tanker, and Barge to Other PADDs of {product}",
]
MONTHLY_INTERPADD_PHRASES = [
    "Net Receipts by Pipeline, Tanker, and Barge from Other PADDs",
    "Receipts by Pipeline from",
    "Receipts by Pipeline, Tanker, and Barge from",
    "Receipts by Tanker and Barge from",
    "Shipments by Pipeline, Tanker, and Barge to Other PADDs",
]
MONTHLY_DISTILLATE_EXCLUDE_PHRASES = [
    "0 to 15 ppm",
    "Greater Than",
    "Greater than",
    "Low Sulfur",
    "High Sulfur",
]
WEEKLY_DIESEL_SOURCE_COLUMNS = [
    "WCRRIP12",
    "WCRRIP22",
    "WCRRIP32",
    "WCRRIP42",
    "WCRRIP52",
    "WCRRIUS2",
    "WDIRPP12",
    "WDIRPP22",
    "WDIRPP32",
    "WDIRPP42",
    "WDIRPP52",
    "WDIRPUS2",
    "WGIRIP12",
    "WGIRIP22",
    "WGIRIP32",
    "WGIRIP42",
    "WGIRIP52",
    "WGIRIUS2",
    "WOCLEUS2",
    "W_NA_YRL_R10_MBBLD",
    "W_NA_YRL_R20_MBBLD",
    "W_NA_YRL_R30_MBBLD",
    "W_NA_YRL_R40_MBBLD",
    "W_NA_YRL_R50_MBBLD",
    "W_NA_YUP_R10_PER",
    "W_NA_YUP_R20_PER",
    "W_NA_YUP_R30_PER",
    "W_NA_YUP_R40_PER",
    "W_NA_YUP_R50_PER",
    "W_EPD0_YPB_NUS_MBBLD",
    "W_EPD0_YPY_NUS_MBBLD",
    "WDIST1A1",
    "WDIST1B1",
    "WDIST1C1",
    "WDISTP11",
    "WDISTP21",
    "WDISTP31",
    "WDISTP41",
    "WDISTP51",
    "WDISTUS1",
    "WDIIMUS2",
    "WDIUPUS2",
    "WDIIM_R10-Z00_2",
    "WDIIM_R20-Z00_2",
    "WDIIM_R30-Z00_2",
    "WDIIM_R40-Z00_2",
    "WDIIM_R50-Z00_2",
    "WDIEXUS2",
]
WEEKLY_GASOLINE_CONTEXT_SOURCE_COLUMNS = [
    "WCRRIP12",
    "WCRRIP22",
    "WCRRIP32",
    "WCRRIP42",
    "WCRRIP52",
    "WCRRIUS2",
    "WGIRIP12",
    "WGIRIP22",
    "WGIRIP32",
    "WGIRIP42",
    "WGIRIP52",
    "WGIRIUS2",
    "WOCLEUS2",
    "W_NA_YRL_R10_MBBLD",
    "W_NA_YRL_R20_MBBLD",
    "W_NA_YRL_R30_MBBLD",
    "W_NA_YRL_R40_MBBLD",
    "W_NA_YRL_R50_MBBLD",
    "W_NA_YUP_R10_PER",
    "W_NA_YUP_R20_PER",
    "W_NA_YUP_R30_PER",
    "W_NA_YUP_R40_PER",
    "W_NA_YUP_R50_PER",
]
GASOLINE_PRODUCTS = [
    "Finished Motor Gasoline",
    "Gasoline Blending Components",
    "Fuel Ethanol",
]
GASOLINE_MATCH_PHRASES = [
    "Finished Motor Gasoline",
    "Gasoline Blending Components",
    "Motor Gasoline Blending Components",
    "Fuel Ethanol",
]
GASOLINE_CODE_MARKERS = [
    "EPM0F",
    "EPOBG",
    "EPOOXE",
]
PADD_ORDER = [
    "PADD 1",
    "PADD 1A",
    "PADD 1B",
    "PADD 1C",
    "PADD 2",
    "PADD 3",
    "PADD 4",
    "PADD 5",
    "US",
]


@contextmanager
def suppress_native_stderr():
    saved_stderr = os.dup(2)
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        os.dup2(saved_stderr, 2)
        os.close(saved_stderr)


def write_header_csv(directory: str) -> None:
    path = Path(directory)
    schema = pq.read_schema(path / "raw")
    with (path / "raw.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(schema.names)


def write_weekly_raw_excel_archive() -> None:
    path = Path("eia_weekly")
    output_path = path / WEEKLY_RAW_EXCEL_OUTPUT
    tmp_archive_path = path / f"{WEEKLY_RAW_EXCEL_OUTPUT}.tmp"
    tmp_csv_path = Path(tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name)
    raw = pq.ParquetFile(path / "raw")
    columns = raw.schema_arrow.names
    try:
        with tmp_csv_path.open("w", newline="", encoding="utf-8") as text_file:
            writer = csv.writer(text_file)
            writer.writerow(columns)
            for batch in raw.iter_batches(batch_size=65_536, columns=columns):
                data = batch.to_pydict()
                writer.writerows(zip(*(data[column] for column in columns)))
        with tarfile.open(tmp_archive_path, "w:xz", preset=9) as archive:
            archive.add(tmp_csv_path, arcname="raw.csv")
        tmp_archive_path.replace(output_path)
    finally:
        tmp_csv_path.unlink(missing_ok=True)
        tmp_archive_path.unlink(missing_ok=True)


def write_weekly_series_csv() -> None:
    path = Path("eia_weekly")
    columns = [
        "source_table",
        "source_sheet",
        "source_column",
        "series_name",
        "region",
        "subregion",
        "product",
        "metric",
        "unit",
        "period_type",
    ]
    table = pq.read_table(path / "raw", columns=[
        "source_table",
        "source_sheet",
        "source_column",
        "metric",
        "product",
        "region",
        "subregion",
        "unit",
        "period_type",
    ])
    seen: set[tuple[str, ...]] = set()
    rows: list[tuple[str, ...]] = []
    data = table.to_pydict()
    for index in range(table.num_rows):
        row = {
            name: "" if data[name][index] is None else str(data[name][index])
            for name in data
        }
        key = (
            row["source_table"],
            row["source_sheet"],
            row["source_column"],
            row["region"],
            row["subregion"],
            row["product"],
            row["metric"],
            row["unit"],
            row["period_type"],
        )
        if key in seen:
            continue
        seen.add(key)
        series_name = " ".join(
            part for part in [row["period_type"], row["region"], row["metric"]] if part
        ).strip()
        rows.append((
            row["source_table"],
            row["source_sheet"],
            row["source_column"],
            series_name,
            row["region"],
            row["subregion"],
            row["product"],
            row["metric"],
            row["unit"],
            row["period_type"],
        ))
    rows.sort()
    with (path / "series.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)


def write_monthly_series_csv() -> None:
    path = Path("eia_monthly")
    columns = [
        "source_endpoint",
        "series",
        "series_name",
        "region",
        "region_code",
        "origin_code",
        "destination_code",
        "product_code",
        "product_name",
        "unit",
    ]
    table = pq.read_table(path / "raw", columns=[
        "source_endpoint",
        "series",
        "series_description",
        "duoarea_name",
        "duoarea_code",
        "origin_code",
        "destination_code",
        "product_code",
        "product_name",
        "unit",
    ])
    seen: set[tuple[str, ...]] = set()
    rows: list[tuple[str, ...]] = []
    data = table.to_pydict()
    for index in range(table.num_rows):
        row = {
            name: "" if data[name][index] is None else str(data[name][index])
            for name in data
        }
        key = (
            row["source_endpoint"],
            row["series"],
            row["duoarea_code"],
            row["origin_code"],
            row["destination_code"],
            row["product_code"],
            row["unit"],
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append((
            row["source_endpoint"],
            row["series"],
            row["series_description"],
            row["duoarea_name"],
            row["duoarea_code"],
            row["origin_code"],
            row["destination_code"],
            row["product_code"],
            row["product_name"],
            row["unit"],
        ))
    rows.sort()
    with (path / "series.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)


def monthly_region_rank(name: str) -> int:
    if "East Coast (PADD 1)" in name or "East Coast (PAD I)" in name:
        return 0
    if "New England (PADD 1A)" in name:
        return 1
    if "Central Atlantic (PADD 1B)" in name:
        return 2
    if "Lower Atlantic (PADD 1C)" in name:
        return 3
    if "Midwest (PADD 2)" in name:
        return 4
    if "Gulf Coast (PADD 3)" in name:
        return 5
    if "Rocky Mountain" in name and "(PADD 4)" in name:
        return 6
    if "West Coast (PADD 5)" in name:
        return 7
    if name.startswith("U.S.") or name.startswith("U. S."):
        return 8
    return 99


def monthly_metric_rank(name: str) -> int:
    metric_order = [
        "Refinery Net Input of Crude Oil",
        "Gross Inputs",
        "Operable Crude Oil Distillation Capacity",
        "Operating Crude Oil Distillation Capacity",
        "Idle Crude Oil Distillation Capacity",
        "Percent Utilization of Refinery Operable Capacity",
        "Refinery Catalytic Cracking, Fresh Feed Downstream Charge Capacity",
        "Downstream Processing of Fresh Feed Input by Catalytic Cracking Units",
        "Refinery Catalytic Hydrocracking Downstream Charge Capacity",
        "Downstream Processing of Fresh Feed Input by Catalytic Hydrocracking Units",
        "Refinery Catalytic Reforming Downstream Charge Capacity",
        "Downstream Processing of Fresh Feed Input by Catalytic Reforming Units",
        "Refinery Thermal Cracking, Coking Downstream Charge Capacity",
        "Downstream Processing of Fresh Feed Input by Delayed and Fluid Coking Units",
        "Product Supplied",
        "Refinery and Blender Net Production",
        "Ending Stocks",
        "Exports of",
        "Imports of",
        "Net Receipts",
        "Receipts by Pipeline from",
        "Receipts by Pipeline, Tanker, and Barge from",
        "Receipts by Tanker and Barge from",
        "Shipments by Pipeline, Tanker, and Barge",
    ]
    for index, marker in enumerate(metric_order):
        if marker in name:
            return index
    return len(metric_order)


def monthly_unit_rank(units: str) -> int:
    return {
        "Thousand Barrels per Day": 0,
        "Thousand Barrels per Calendar Day": 1,
        "Thousand Barrels": 2,
        "Percent": 3,
    }.get(units, 9)


def round_daily(value: float) -> float:
    return round(value, 3)


def round_percent(value: float) -> float:
    return round(value, 2)


def is_percent_column(column_name: str) -> bool:
    return column_name.endswith("(Percent)")


def is_calculated_daily_column(column_name: str) -> bool:
    if not column_name.endswith("(Thousand Barrels per Day)"):
        return False
    return (
        is_monthly_interpadd_series(column_name)
        or "Exports of" in column_name
        or "Imports of" in column_name
        or "Downstream Charge Capacity as of January 1" in column_name
    )


def format_monthly_cell(column_name: str, value: object) -> object:
    if column_name == "Date":
        return value
    numeric = float(value or 0)
    if is_percent_column(column_name):
        return f"{round_percent(numeric):.2f}"
    if is_calculated_daily_column(column_name):
        return f"{round_daily(numeric):.3f}"
    return numeric


def normalized_monthly_name(name: str) -> str:
    return (
        name.replace("East Coast (PAD I)", "East Coast (PADD 1)")
        .replace("East Coast (PADD I)", "East Coast (PADD 1)")
        .replace("Midwest (PADD II)", "Midwest (PADD 2)")
        .replace("Gulf Coast (PADD III)", "Gulf Coast (PADD 3)")
        .replace("Rocky Mountain (PADD IV)", "Rocky Mountain (PADD 4)")
        .replace("West Coast (PADD V)", "West Coast (PADD 5)")
        .replace("Rocky Mountains (PADD 4)", "Rocky Mountain (PADD 4)")
        .replace("Rocky Mountain (PADD 4 Downstream", "Rocky Mountain (PADD 4) Downstream")
    )


def normalized_monthly_units(name: str, units: str) -> str:
    if units == "Barrels per Calendar Day" and is_monthly_annual_capacity_series(name, units):
        return "Thousand Barrels per Day"
    if units == "Thousand Barrels" and is_monthly_interpadd_series(name):
        return "Thousand Barrels per Day"
    return units


def monthly_column_name(item: dict[str, object]) -> str:
    raw_name = str(item["name"])
    name = normalized_monthly_name(raw_name.replace(", Monthly", "").replace(", Annual", "").strip())
    units = normalized_monthly_units(raw_name, str(item["units"]).strip())
    return f"{name} ({units})"


def monthly_period_parts(value: object) -> tuple[int, int] | None:
    period = str(value).strip()
    if len(period) != 6 or not period.isdigit() or period < MONTHLY_START:
        return None
    return int(period[:4]), int(period[4:])


def monthly_period(value: object) -> str | None:
    parts = monthly_period_parts(value)
    if parts is None:
        return None
    year, month = parts
    return f"{year:04d}-{month:02d}-15"


def monthly_period_days(value: object) -> int | None:
    parts = monthly_period_parts(value)
    if parts is None:
        return None
    year, month = parts
    return monthrange(year, month)[1]


def annual_year(value: object) -> int | None:
    year = str(value).strip()
    if len(year) != 4 or not year.isdigit():
        return None
    return int(year)


def is_monthly_region_series(name: str) -> bool:
    normalized = normalized_monthly_name(name)
    if normalized.startswith("U.S. Virgin Islands"):
        return False
    return any(normalized.startswith(normalized_monthly_name(prefix)) for prefix in MONTHLY_REGION_PREFIXES)


def is_monthly_common_series(name: str) -> bool:
    return is_monthly_region_series(name) and ", Monthly" in name and any(phrase in name for phrase in MONTHLY_COMMON_PHRASES)


def is_monthly_annual_capacity_series(name: str, units: str) -> bool:
    return (
        is_monthly_region_series(name)
        and ", Annual" in name
        and units == "Barrels per Calendar Day"
        and any(phrase in name for phrase in MONTHLY_ANNUAL_CAPACITY_PHRASES)
    )


def is_monthly_product_series(name: str, product: str) -> bool:
    if product not in name or not is_monthly_region_series(name) or ", Monthly" not in name:
        return False
    if product == "Distillate Fuel Oil" and any(phrase in name for phrase in MONTHLY_DISTILLATE_EXCLUDE_PHRASES):
        return False
    return any(phrase.format(product=product) in name for phrase in MONTHLY_PRODUCT_PHRASES)


def is_monthly_gasoline_series(item: dict[str, object]) -> bool:
    name = normalized_monthly_name(str(item.get("name", "")))
    series_id = str(item.get("series_id", ""))
    if not is_monthly_region_series(name) or ", Monthly" not in name:
        return False
    if any(is_monthly_product_series(name, product) for product in GASOLINE_PRODUCTS):
        return True
    if any(marker in series_id for marker in GASOLINE_CODE_MARKERS):
        return True
    if any(phrase in name for phrase in GASOLINE_MATCH_PHRASES) and any(
        marker in name
        for marker in [
            "Blender Net Input",
            "Input into Blenders",
            "Input into Refineries",
            "Refinery Net Input",
            "Refinery and Blender Net Input",
            "Stocks",
            "Imports",
            "Exports",
            "Net Receipts",
            "Receipts by Pipeline",
            "Receipts by Tanker",
            "Shipments",
        ]
    ):
        return True
    return False


def is_monthly_interpadd_series(name: str) -> bool:
    return any(phrase in name for phrase in MONTHLY_INTERPADD_PHRASES)


def monthly_selection_priority(item: dict[str, object]) -> int:
    name = normalized_monthly_name(str(item["name"]))
    units = str(item["units"]).strip()
    if units == "Thousand Barrels" and is_monthly_interpadd_series(name):
        return 1
    return 0


def normalized_monthly_value(item: dict[str, object], period: object, value: object) -> float:
    if value is None or value == "":
        numeric = 0.0
    else:
        numeric = float(value)
    name = normalized_monthly_name(str(item["name"]))
    units = str(item["units"]).strip()
    if units == "Thousand Barrels" and is_monthly_interpadd_series(name):
        days = monthly_period_days(period)
        return round_daily(numeric / days) if days else 0.0
    if units == "Barrels per Calendar Day" and is_monthly_annual_capacity_series(str(item["name"]), units):
        return round_daily(numeric / 1000.0)
    return numeric


def monthly_region_label(name: str) -> str:
    normalized = normalized_monthly_name(name)
    for prefix in MONTHLY_REGION_PREFIXES:
        label = normalized_monthly_name(prefix)
        if normalized.startswith(label):
            return label
    return ""


def monthly_capacity_key(column_name: str) -> tuple[str, str] | None:
    name = normalized_monthly_name(column_name)
    region = monthly_region_label(name)
    if not region:
        return None
    if "Operable Crude Oil Distillation Capacity" in name:
        return (region, "crude_distillation")
    if "Refinery Catalytic Cracking, Fresh Feed Downstream Charge Capacity" in name:
        return (region, "catalytic_cracking")
    if "Refinery Catalytic Hydrocracking Downstream Charge Capacity" in name:
        return (region, "hydrocracking")
    if "Refinery Catalytic Reforming Downstream Charge Capacity" in name:
        return (region, "reforming")
    if "Refinery Thermal Cracking, Coking Downstream Charge Capacity" in name:
        return (region, "coking")
    return None


def monthly_numerator_key(column_name: str) -> tuple[str, str] | None:
    name = normalized_monthly_name(column_name)
    region = monthly_region_label(name)
    if not region:
        return None
    if "Refinery Net Input of Crude Oil" in name:
        return (region, "crude_distillation")
    if "Gross Inputs" in name:
        return (region, "crude_distillation")
    if "Downstream Processing of Fresh Feed Input by Catalytic Cracking Units" in name:
        return (region, "catalytic_cracking")
    if "Downstream Processing of Fresh Feed Input by Catalytic Hydrocracking Units" in name:
        return (region, "hydrocracking")
    if "Downstream Processing of Fresh Feed Input by Catalytic Reforming Units" in name:
        return (region, "reforming")
    if "Downstream Processing of Fresh Feed Input by Delayed and Fluid Coking Units" in name:
        return (region, "coking")
    return None


def strip_monthly_units(column_name: str) -> str:
    if column_name.endswith(")") and " (" in column_name:
        return column_name.rsplit(" (", 1)[0]
    return column_name


def monthly_percent_column_name(numerator_column: str, capacity_column: str) -> str:
    numerator = strip_monthly_units(numerator_column)
    capacity = strip_monthly_units(capacity_column)
    region = monthly_region_label(numerator)
    if region and capacity.startswith(region):
        capacity = capacity[len(region) :].strip()
    return f"{numerator} / {capacity} (Percent)"


def monthly_header_sort_key(column_name: str) -> tuple[int, int, str, int, str]:
    if column_name == "Date":
        return (-1, -1, "", -1, "")
    units = column_name.rsplit(" (", 1)[1][:-1] if column_name.endswith(")") and " (" in column_name else ""
    return (
        monthly_metric_rank(column_name),
        monthly_region_rank(column_name),
        column_name,
        monthly_unit_rank(units),
        column_name,
    )


def monthly_export_country(name: str, product: str, padd: str) -> str | None:
    prefix = f"{padd} Exports to "
    suffix = f" of {product}, Monthly"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    return name[len(prefix) : -len(suffix)]


def monthly_country_category(allowed: list[str], country: str) -> str | None:
    if "Canada" in allowed and country == "Canada":
        return "Canada"
    if "Africa" in allowed and country in AFRICA_EXPORT_COUNTRIES:
        return "Africa"
    if "Europe" in allowed and country in EUROPE_EXPORT_COUNTRIES:
        return "Europe"
    if "Middle East" in allowed and country in MIDDLE_EAST_EXPORT_COUNTRIES:
        return "Middle East"
    if "Latin America" in allowed and country in LATIN_AMERICA_EXPORT_COUNTRIES:
        return "Latin America"
    if "Asia including India" in allowed and country in ASIA_EXPORT_COUNTRIES:
        return "Asia including India"
    return None


def monthly_export_padd_categories(product: str) -> dict[str, list[str]]:
    if product in GASOLINE_PRODUCTS:
        return MONTHLY_GASOLINE_EXPORT_PADD_CATEGORIES
    return MONTHLY_EXPORT_PADD_CATEGORIES


def monthly_flow_country(name: str, product: str, padd: str, flow: str) -> str | None:
    prefix = f"{padd} {flow} from " if flow == "Imports" else f"{padd} {flow} to "
    suffix = f" of {product}, Monthly"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    return name[len(prefix) : -len(suffix)]


def monthly_flow_total_name(padd: str, product: str, flow: str) -> str:
    return f"{padd} {flow} of {product} (Thousand Barrels per Day)"


def monthly_flow_category_name(padd: str, product: str, flow: str, category: str) -> str:
    preposition = "from" if flow == "Imports" else "to"
    return f"{padd} {flow} of {product} {preposition} {category} (Thousand Barrels per Day)"


def monthly_flow_daily_value(period: object, value: object) -> float:
    days = monthly_period_days(period)
    return round_daily(float(value or 0) / days) if days else 0.0


def add_monthly_country_flow_buckets(
    rows_by_month: dict[str, dict[str, object]],
    product: str,
    flow: str,
    padd_categories: dict[str, list[str]],
) -> list[str]:
    totals: dict[str, dict[str, float]] = {padd: {} for padd in padd_categories}
    category_values: dict[tuple[str, str], dict[str, float]] = {
        (padd, category): {}
        for padd, categories in padd_categories.items()
        for category in categories
        if category not in {"Other", "Canada/Other"}
    }

    for item in iter_monthly_bulk_items():
        if item.get("f") != "M" or item.get("units") != "Thousand Barrels":
            continue
        name = str(item.get("name", ""))
        if product not in name or any(phrase in name for phrase in MONTHLY_DISTILLATE_EXCLUDE_PHRASES):
            continue
        for padd, categories in padd_categories.items():
            if name == f"{padd} {flow} of {product}, Monthly":
                for period, value in item.get("data", []):
                    month = monthly_period(period)
                    if month is not None:
                        rows_by_month.setdefault(month, {"Date": month})
                        totals[padd][month] = monthly_flow_daily_value(period, value)
                break
            country = monthly_flow_country(name, product, padd, flow)
            if country is None:
                continue
            category = monthly_country_category(categories, country)
            if category is None or category not in categories:
                break
            monthly_values = category_values[(padd, category)]
            for period, value in item.get("data", []):
                month = monthly_period(period)
                if month is None:
                    continue
                rows_by_month.setdefault(month, {"Date": month})
                monthly_values[month] = monthly_values.get(month, 0.0) + monthly_flow_daily_value(period, value)
            break

    columns: list[str] = []
    for padd, categories in padd_categories.items():
        total_column = monthly_flow_total_name(padd, product, flow)
        columns.append(total_column)
        for category in categories:
            columns.append(monthly_flow_category_name(padd, product, flow, category))

        for month, row in rows_by_month.items():
            total = round_daily(totals[padd].get(month, 0.0))
            row[total_column] = total
            named_sum = 0.0
            for category in categories:
                category_column = monthly_flow_category_name(padd, product, flow, category)
                if category in {"Other", "Canada/Other"}:
                    continue
                value = round_daily(category_values.get((padd, category), {}).get(month, 0.0))
                named_sum += value
                row[category_column] = value
            if "Other" in categories:
                row[monthly_flow_category_name(padd, product, flow, "Other")] = round_daily(total - named_sum)
            if "Canada/Other" in categories:
                row[monthly_flow_category_name(padd, product, flow, "Canada/Other")] = round_daily(total - named_sum)

    return columns


def add_monthly_destination_exports(rows_by_month: dict[str, dict[str, object]], product: str) -> list[str]:
    return add_monthly_country_flow_buckets(rows_by_month, product, "Exports", monthly_export_padd_categories(product))


def add_monthly_origin_imports(rows_by_month: dict[str, dict[str, object]], product: str) -> list[str]:
    return add_monthly_country_flow_buckets(rows_by_month, product, "Imports", MONTHLY_IMPORT_PADD_CATEGORIES[product])


def monthly_export_sort_key(item: dict[str, object]) -> tuple[int, int, str, int, str]:
    name = normalized_monthly_name(str(item["name"]))
    units = normalized_monthly_units(name, str(item["units"]))
    return (
        monthly_metric_rank(name),
        monthly_region_rank(name),
        name,
        monthly_unit_rank(units),
        str(item["series_id"]),
    )


def iter_monthly_bulk_items():
    with ZipFile(MONTHLY_BULK_SOURCE) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise RuntimeError(f"{MONTHLY_BULK_SOURCE} must contain exactly one txt file")
        with archive.open(names[0]) as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"{MONTHLY_BULK_SOURCE}:{line_number} is not valid JSON") from exc
                if item.get("f") in {"A", "M"}:
                    yield item


def write_monthly_clean_csv_for_products(filename: str, products: list[str]) -> None:
    path = Path("eia_monthly")
    selected_by_column: dict[str, dict[str, object]] = {}
    for item in iter_monthly_bulk_items():
        name = str(item.get("name", ""))
        units = str(item.get("units", ""))
        if not (
            is_monthly_common_series(name)
            or any(is_monthly_product_series(name, product) for product in products)
            or (products == GASOLINE_PRODUCTS and is_monthly_gasoline_series(item))
            or is_monthly_annual_capacity_series(name, units)
        ):
            continue
        column_name = monthly_column_name(item)
        existing = selected_by_column.get(column_name)
        if existing is None or monthly_selection_priority(item) < monthly_selection_priority(existing):
            selected_by_column[column_name] = item

    selected = sorted(selected_by_column.values(), key=monthly_export_sort_key)
    if not selected:
        raise RuntimeError(f"No monthly series matched {', '.join(products)}")

    column_names = [monthly_column_name(item) for item in selected]
    if len(column_names) != len(set(column_names)):
        raise RuntimeError(f"{filename} would contain duplicate monthly column names")

    rows_by_month: dict[str, dict[str, object]] = {}
    annual_values_by_column: dict[str, dict[int, float]] = {}
    for item, column_name in zip(selected, column_names):
        frequency = str(item.get("f", ""))
        if frequency == "A":
            by_year: dict[int, float] = {}
            for period, value in item.get("data", []):
                year = annual_year(period)
                if year is not None:
                    by_year[year] = normalized_monthly_value(item, period, value)
            annual_values_by_column[column_name] = by_year
            continue
        for period, value in item.get("data", []):
            month = monthly_period(period)
            if month is None:
                continue
            row = rows_by_month.setdefault(month, {"Date": month})
            if column_name in row and row[column_name] != value:
                raise RuntimeError(f"Conflicting monthly value for {month} {column_name}")
            row[column_name] = normalized_monthly_value(item, period, value)

    for column_name, annual_values in annual_values_by_column.items():
        years = sorted(annual_values)
        for month, row in rows_by_month.items():
            year = int(month[:4])
            value = 0.0
            for candidate_year in years:
                if candidate_year > year:
                    break
                value = annual_values[candidate_year]
            row[column_name] = value

    capacity_by_key = {
        key: column_name
        for column_name in column_names
        for key in [monthly_capacity_key(column_name)]
        if key is not None
    }
    percent_columns: list[str] = []
    for column_name in column_names:
        if column_name.endswith("(Thousand Barrels)"):
            continue
        key = monthly_numerator_key(column_name)
        if key is None or key not in capacity_by_key:
            continue
        capacity_column = capacity_by_key[key]
        percent_column = monthly_percent_column_name(column_name, capacity_column)
        percent_columns.append(percent_column)
        for row in rows_by_month.values():
            numerator = float(row.get(column_name, 0) or 0)
            capacity = float(row.get(capacity_column, 0) or 0)
            row[percent_column] = round_percent(numerator / capacity * 100.0) if capacity else 0.0

    destination_export_columns: list[str] = []
    origin_import_columns: list[str] = []
    for product in products:
        destination_export_columns.extend(add_monthly_destination_exports(rows_by_month, product))
        origin_import_columns.extend(add_monthly_origin_imports(rows_by_month, product))
    sorted_columns = sorted(
        [*column_names, *percent_columns, *destination_export_columns, *origin_import_columns],
        key=monthly_header_sort_key,
    )
    columns = ["Date", *dict.fromkeys(sorted_columns)]
    for row in rows_by_month.values():
        for column in columns:
            row.setdefault(column, 0)

    with (path / filename).open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for month in sorted(rows_by_month):
            row = rows_by_month[month]
            writer.writerow({column: format_monthly_cell(column, row[column]) for column in columns})


def write_monthly_clean_csv(filename: str, product: str) -> None:
    write_monthly_clean_csv_for_products(filename, [product])


def write_monthly_clean_exports() -> None:
    write_monthly_clean_csv(MONTHLY_DIESEL_OUTPUT, "Distillate Fuel Oil")
    write_monthly_clean_csv(MONTHLY_JET_OUTPUT, "Kerosene-Type Jet Fuel")
    write_monthly_clean_csv_for_products(MONTHLY_GASOLINE_OUTPUT, GASOLINE_PRODUCTS)


def padd_group(series_name: str) -> str:
    if "East Coast (PADD 1)" in series_name or series_name.startswith("weekly PADD 1 "):
        return "PADD 1"
    if "New England (PADD 1A)" in series_name:
        return "PADD 1A"
    if "Central Atlantic (PADD 1B)" in series_name:
        return "PADD 1B"
    if "Lower Atlantic (PADD 1C)" in series_name:
        return "PADD 1C"
    if "Midwest (PADD 2)" in series_name:
        return "PADD 2"
    if "Gulf Coast (PADD 3)" in series_name:
        return "PADD 3"
    if "Rocky Mountain" in series_name and "(PADD 4)" in series_name:
        return "PADD 4"
    if "West Coast (PADD 5)" in series_name:
        return "PADD 5"
    if "U.S." in series_name or "U. S." in series_name:
        return "US"
    return "US"


def read_weekly_series_rows() -> list[dict[str, str]]:
    path = Path("eia_weekly")
    with (path / "series.csv").open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def weekly_rows_by_source_column(series_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in series_rows:
        if row["period_type"] != "weekly":
            continue
        rows.setdefault(row["source_column"], row)
    return rows


def weekly_rows_by_series_name(series_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in series_rows:
        if row["period_type"] != "weekly":
            continue
        rows.setdefault(row["series_name"], row)
    return rows


def sort_weekly_mappings(mappings: list[dict[str, str]]) -> list[dict[str, str]]:
    group_rank = {group: index for index, group in enumerate(PADD_ORDER)}
    return sorted(
        mappings,
        key=lambda row: (
            group_rank[padd_group(row["series_name"])],
            WEEKLY_DIESEL_SOURCE_COLUMNS.index(row["source_column"])
            if row["source_column"] in WEEKLY_DIESEL_SOURCE_COLUMNS
            else len(WEEKLY_DIESEL_SOURCE_COLUMNS),
            row["series_name"],
        ),
    )


def diesel_mappings(series_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    source_columns = list(dict.fromkeys(WEEKLY_DIESEL_SOURCE_COLUMNS))
    rows_by_column = weekly_rows_by_source_column(series_rows)
    missing = [source_column for source_column in source_columns if source_column not in rows_by_column]
    if missing:
        raise RuntimeError(f"Missing weekly diesel source columns: {missing}")
    return sort_weekly_mappings([rows_by_column[source_column] for source_column in source_columns])


def jet_mappings(series_rows: list[dict[str, str]], diesel_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows_by_name = weekly_rows_by_series_name(series_rows)
    mappings: list[dict[str, str]] = []
    seen_source_columns: set[str] = set()
    for row in diesel_rows:
        jet_name = row["series_name"].replace("Distillate Fuel Oil", "Kerosene-Type Jet Fuel")
        if jet_name == row["series_name"] and "Distillate" in row["series_name"]:
            continue
        match = rows_by_name.get(jet_name)
        if not match or match["source_column"] in seen_source_columns:
            continue
        seen_source_columns.add(match["source_column"])
        mappings.append(match)
    return mappings


def is_weekly_gasoline_row(row: dict[str, str]) -> bool:
    haystack = " ".join(
        [
            row.get("source_column", ""),
            row.get("series_name", ""),
            row.get("product", ""),
            row.get("metric", ""),
        ]
    )
    return any(marker in haystack for marker in GASOLINE_CODE_MARKERS) or any(
        phrase in haystack for phrase in GASOLINE_MATCH_PHRASES
    )


def gasoline_mappings(series_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows_by_column = weekly_rows_by_source_column(series_rows)
    missing_context = [
        source_column
        for source_column in WEEKLY_GASOLINE_CONTEXT_SOURCE_COLUMNS
        if source_column not in rows_by_column
    ]
    if missing_context:
        raise RuntimeError(f"Missing weekly gasoline context source columns: {missing_context}")

    mappings = [rows_by_column[source_column] for source_column in WEEKLY_GASOLINE_CONTEXT_SOURCE_COLUMNS]
    seen_source_columns = {row["source_column"] for row in mappings}
    for row in series_rows:
        if row["period_type"] != "weekly" or not is_weekly_gasoline_row(row):
            continue
        if row["source_column"] in seen_source_columns:
            continue
        seen_source_columns.add(row["source_column"])
        mappings.append(row)
    if not any("EPM0F" in row["source_column"] for row in mappings):
        raise RuntimeError("Weekly gasoline mappings missing EPM0F source columns")
    if not any("EPOBG" in row["source_column"] for row in mappings) and not any(
        "Gasoline Blending Components" in row["series_name"] for row in mappings
    ):
        raise RuntimeError("Weekly gasoline mappings missing EPOBG/gasoline blending component source columns")
    return sort_weekly_mappings(mappings)


def read_weekly_value_data(source_columns: list[str]) -> dict[str, list[object]]:
    path = Path("eia_weekly")
    raw_columns = ["week_ending", "source_column", "period_type", "value"]
    table = pq.read_table(path / "raw", columns=raw_columns)
    mask = pc.and_(
        pc.is_in(table["source_column"], value_set=pa.array(source_columns, type=pa.string())),
        pc.equal(table["period_type"], "weekly"),
    )
    return table.filter(mask).to_pydict()


def write_weekly_clean_csv_from_values(filename: str, mappings: list[dict[str, str]], data: dict[str, list[object]]) -> None:
    path = Path("eia_weekly")
    source_columns = [row["source_column"] for row in mappings]
    series_names = [row["series_name"] for row in mappings]
    if len(source_columns) != len(set(source_columns)):
        raise RuntimeError(f"{filename} would contain duplicate source columns")
    if len(series_names) != len(set(series_names)):
        raise RuntimeError(f"{filename} would contain duplicate series_name columns")

    columns = ["week_ending", *series_names]
    series_by_source_column = {
        row["source_column"]: row["series_name"]
        for row in mappings
    }
    rows_by_week: dict[str, dict[str, str | float | None]] = {}
    for index in range(len(data.get("week_ending", []))):
        week_ending = data["week_ending"][index]
        source_column = data["source_column"][index]
        series_name = series_by_source_column.get(str(source_column))
        if not series_name:
            continue
        value = data["value"][index]
        row = rows_by_week.setdefault(week_ending, {"week_ending": week_ending})
        if series_name in row:
            if row[series_name] != value:
                raise RuntimeError(f"Conflicting weekly value for {week_ending} {source_column}")
            continue
        row[series_name] = value

    with (path / filename).open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for week_ending in sorted(rows_by_week):
            writer.writerow(rows_by_week[week_ending])


def write_weekly_clean_csv(filename: str, mappings: list[dict[str, str]]) -> None:
    write_weekly_clean_csv_from_values(filename, mappings, read_weekly_value_data([row["source_column"] for row in mappings]))


def write_weekly_clean_exports() -> None:
    series_rows = read_weekly_series_rows()
    diesel_rows = diesel_mappings(series_rows)
    jet_rows = jet_mappings(series_rows, diesel_rows)
    gasoline_rows = gasoline_mappings(series_rows)
    value_data = read_weekly_value_data(list(dict.fromkeys(
        row["source_column"]
        for mappings in [diesel_rows, jet_rows, gasoline_rows]
        for row in mappings
    )))
    write_weekly_clean_csv_from_values(WEEKLY_DIESEL_OUTPUT, diesel_rows, value_data)
    write_weekly_clean_csv_from_values(WEEKLY_JET_OUTPUT, jet_rows, value_data)
    write_weekly_clean_csv_from_values(WEEKLY_GASOLINE_OUTPUT, gasoline_rows, value_data)


def export_weekly(*, include_raw_archive: bool = True) -> None:
    with suppress_native_stderr():
        if include_raw_archive:
            write_weekly_raw_excel_archive()
        write_weekly_series_csv()
        write_weekly_clean_exports()
    archive_label = "raw.csv.tar.xz, " if include_raw_archive else ""
    print(f"wrote weekly {archive_label}series.csv inspection file, and weekly clean exports")


def export_monthly() -> None:
    with suppress_native_stderr():
        write_header_csv("eia_monthly")
        write_monthly_series_csv()
        write_monthly_clean_exports()
    print("wrote monthly raw.csv, series.csv inspection file, and monthly clean exports")


def export_all(*, include_weekly_raw_archive: bool = True) -> None:
    with suppress_native_stderr():
        write_header_csv("eia_monthly")
        if include_weekly_raw_archive:
            write_weekly_raw_excel_archive()
        write_weekly_series_csv()
        write_monthly_series_csv()
        write_weekly_clean_exports()
        write_monthly_clean_exports()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    include_weekly_raw_archive = "--skip-weekly-raw-archive" not in args
    args = [arg for arg in args if arg != "--skip-weekly-raw-archive"]
    mode = args[0].lower() if args else "all"
    if mode in {"weekly", "--weekly"}:
        export_weekly(include_raw_archive=include_weekly_raw_archive)
        return 0
    if mode in {"monthly", "--monthly"}:
        export_monthly()
        return 0
    if mode not in {"all", "--all"}:
        raise RuntimeError(f"Unknown export mode {mode!r}; use weekly, monthly, or all")
    export_all(include_weekly_raw_archive=include_weekly_raw_archive)
    archive_label = "weekly raw.csv.tar.xz, " if include_weekly_raw_archive else ""
    print(f"wrote monthly raw.csv, {archive_label}series.csv inspection files, and weekly/monthly clean exports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
