from __future__ import annotations

from contextlib import contextmanager
import csv
from decimal import Decimal
import gzip
import io
import json
import os
import tarfile
from pathlib import Path

os.environ.setdefault("ARROW_USER_SIMD_LEVEL", "NONE")

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


EXPECTED_FILES = {
    "eia_weekly": {"diesel.csv", "jet.csv", "gasoline.csv"},
    "eia_monthly": {"bulk_series.csv", "diesel.csv", "jet.csv", "gasoline.csv"},
}
CLEAN_MAGIC = b"EIA_CLEAN_V1\0"
PUBLIC_EIA_API_KEY = b"4ZooAQ2fowZXw2nzj8dhtscw8orLWsdpcEk0sbzM"
SIZE_LIMITS = {
    "eia_weekly": {"diesel.csv": 5_000_000, "jet.csv": 5_000_000, "gasoline.csv": 10_000_000},
    "eia_monthly": {
        "bulk_series.csv": 10_000_000,
        "diesel.csv": 5_000_000,
        "jet.csv": 5_000_000,
        "gasoline.csv": 50_000_000,
    },
}
WEEKLY_DIESEL_OUTPUT = "diesel.csv"
WEEKLY_JET_OUTPUT = "jet.csv"
WEEKLY_GASOLINE_OUTPUT = "gasoline.csv"
MONTHLY_GASOLINE_OUTPUT = "gasoline.csv"
WEEKLY_RAW_EXCEL_OUTPUT = "raw.csv.tar.xz"
MONTHLY_DIESEL_OUTPUT = "diesel.csv"
MONTHLY_JET_OUTPUT = "jet.csv"
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
PADD_ORDER = ["PADD 1", "PADD 2", "PADD 3", "PADD 4", "PADD 5", "US"]
MONTHLY_REFINERY_REGION_LABELS = [
    "East Coast (PADD 1)",
    "Midwest (PADD 2)",
    "Gulf Coast (PADD 3)",
    "Rocky Mountain (PADD 4)",
    "West Coast (PADD 5)",
    "U.S.",
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


def validate_clean(path: Path) -> dict:
    body = path.read_bytes()
    if not body.startswith(CLEAN_MAGIC):
        raise RuntimeError(f"{path} does not start with expected clean binary magic")
    payload = json.loads(gzip.decompress(body[len(CLEAN_MAGIC) :]).decode("utf-8"))
    if payload.get("format") != "eia_clean_placeholder":
        raise RuntimeError(f"{path} has unexpected clean format {payload.get('format')!r}")
    if payload.get("row_count") != 0:
        raise RuntimeError(f"{path} should be a zero-row placeholder until clean series are defined")
    return payload


def validate_raw(path: Path) -> pq.FileMetaData:
    metadata = pq.read_metadata(path)
    if metadata.num_rows <= 0:
        raise RuntimeError(f"{path} has no rows")
    if metadata.num_columns <= 0:
        raise RuntimeError(f"{path} has no columns")
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        for column_index in range(row_group.num_columns):
            compression = row_group.column(column_index).compression
            if compression != "ZSTD":
                raise RuntimeError(f"{path} column {column_index} row group {row_group_index} is {compression}, expected ZSTD")
    return metadata


def metadata_json(metadata: pq.FileMetaData, key: str) -> dict:
    raw_metadata = metadata.metadata or {}
    value = raw_metadata.get(key.encode("utf-8"))
    if value is None:
        raise RuntimeError(f"raw Parquet missing embedded {key}")
    return json.loads(value.decode("utf-8"))


def csv_line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as file:
        return next(csv.reader(file))


def padd_group(series_name: str) -> str:
    if "East Coast (PADD 1)" in series_name or series_name.startswith("weekly PADD 1 "):
        return "PADD 1"
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


def read_weekly_series_rows(path: Path) -> list[dict[str, str]]:
    with (path / "series.csv").open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def weekly_rows_by_source_column(series_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in series_rows:
        if row["period_type"] == "weekly":
            rows.setdefault(row["source_column"], row)
    return rows


def weekly_rows_by_series_name(series_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in series_rows:
        if row["period_type"] == "weekly":
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
    rows_by_column = weekly_rows_by_source_column(series_rows)
    missing = [source_column for source_column in WEEKLY_DIESEL_SOURCE_COLUMNS if source_column not in rows_by_column]
    if missing:
        raise RuntimeError(f"Missing weekly diesel source columns: {missing}")
    return sort_weekly_mappings([rows_by_column[source_column] for source_column in WEEKLY_DIESEL_SOURCE_COLUMNS])


def jet_mappings(series_rows: list[dict[str, str]], diesel_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows_by_name = weekly_rows_by_series_name(series_rows)
    mappings: list[dict[str, str]] = []
    seen_source_columns: set[str] = set()
    for row in diesel_rows:
        match = rows_by_name.get(row["series_name"].replace("Distillate Fuel Oil", "Kerosene-Type Jet Fuel"))
        if match and match["source_column"] not in seen_source_columns:
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
    return sort_weekly_mappings(mappings)


def validate_no_key_leak(path: Path) -> None:
    for child in path.iterdir():
        if child.is_file() and PUBLIC_EIA_API_KEY in child.read_bytes():
            raise RuntimeError(f"public EIA key should not appear in output artifact {child}")


def validate_size_limits(name: str, path: Path) -> None:
    for filename, limit in SIZE_LIMITS[name].items():
        size = (path / filename).stat().st_size
        if size > limit:
            raise RuntimeError(f"{path / filename} is {size} bytes, above limit {limit}")


def validate_weekly_clean_csv(path: Path, filename: str, mappings: list[dict[str, str]]) -> None:
    clean_path = path / filename
    source_columns = [row["source_column"] for row in mappings]
    series_names = [row["series_name"] for row in mappings]
    header = csv_header(clean_path)
    if header != ["week_ending", *series_names]:
        raise RuntimeError(f"{clean_path} has unexpected grouped series_name header")
    if any(source_column in header for source_column in source_columns):
        raise RuntimeError(f"{clean_path} should expose series_name headers, not source_column IDs")

    table = pq.read_table(path / "raw", columns=["week_ending", "source_column", "period_type"])
    selected = pc.and_(
        pc.is_in(table["source_column"], value_set=pa.array(source_columns, type=pa.string())),
        pc.equal(table["period_type"], "weekly"),
    )
    expected_rows = len(set(table.filter(selected)["week_ending"].to_pylist()))
    actual_rows = csv_line_count(clean_path) - 1
    if actual_rows != expected_rows:
        raise RuntimeError(f"{clean_path} row count {actual_rows} != expected {expected_rows}")


def validate_monthly_clean_csv(path: Path, filename: str, product_name: str) -> None:
    clean_path = path / filename
    with clean_path.open(newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader)
        rows = list(reader)
    if not header or header[0] != "Date":
        raise RuntimeError(f"{clean_path} must start with a Date column")
    if len(header) != len(set(header)):
        raise RuntimeError(f"{clean_path} contains duplicate column headers")
    if len(header) < 50:
        raise RuntimeError(f"{clean_path} has too few selected monthly series columns")
    if not rows:
        raise RuntimeError(f"{clean_path} has no monthly rows")
    months = [row[0] for row in rows]
    if months != sorted(months):
        raise RuntimeError(f"{clean_path} months are not sorted ascending")
    if months[0] < "2016-01-01":
        raise RuntimeError(f"{clean_path} starts before 2016-01-01")
    if any(not month.endswith("-15") for month in months):
        raise RuntimeError(f"{clean_path} dates must be on the 15th of each month")
    for row in rows:
        if len(row) != len(header):
            raise RuntimeError(f"{clean_path} contains a short row")
        if any(value == "" for value in row[1:]):
            raise RuntimeError(f"{clean_path} contains blank data cells")
    calculated_daily_markers = [
        "Exports of",
        "Imports of",
        "Net Receipts by Pipeline, Tanker, and Barge",
        "Receipts by Pipeline from",
        "Receipts by Pipeline, Tanker, and Barge from",
        "Receipts by Tanker and Barge from",
        "Shipments by Pipeline, Tanker, and Barge",
        "Downstream Charge Capacity as of January 1",
    ]
    for column_index, column in enumerate(header[1:], start=1):
        values = [row[column_index] for row in rows]
        if column.endswith("(Percent)") and any("." not in value or len(value.rsplit(".", 1)[-1]) != 2 for value in values):
            raise RuntimeError(f"{clean_path} percent column is not formatted to 2 decimals: {column}")
        if (
            column.endswith("(Thousand Barrels per Day)")
            and any(marker in column for marker in calculated_daily_markers)
            and any("." not in value or len(value.rsplit(".", 1)[-1]) != 3 for value in values)
        ):
            raise RuntimeError(f"{clean_path} calculated daily column is not formatted to 3 decimals: {column}")
    required_markers = [
        f"Product Supplied of {product_name}",
        f"Refinery and Blender Net Production of {product_name}",
        "Refinery Net Input of Crude Oil",
        "Gross Inputs",
        "Operable Crude Oil Distillation Capacity",
        "Refinery Catalytic Cracking, Fresh Feed Downstream Charge Capacity",
        "Refinery Catalytic Hydrocracking Downstream Charge Capacity",
        "Refinery Catalytic Reforming Downstream Charge Capacity",
        "Refinery Thermal Cracking, Coking Downstream Charge Capacity",
        "Delayed and Fluid Coking Units",
        "/",
    ]
    for marker in required_markers:
        if not any(marker in column for column in header[1:]):
            raise RuntimeError(f"{clean_path} missing expected monthly marker {marker!r}")
    validate_monthly_reforming_coverage(clean_path, header)
    export_groups = {
        "East Coast (PADD 1)": ["Europe", "Other"],
        "Gulf Coast (PADD 3)": ["Africa", "Europe", "Latin America", "Other"],
        "West Coast (PADD 5)": ["Latin America", "Other"],
    }
    import_groups = {
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
    }
    header_index = {column: index for index, column in enumerate(header)}
    for flow, groups in [("Exports", export_groups), ("Imports", import_groups[product_name])]:
        preposition = "to" if flow == "Exports" else "from"
        for padd, categories in groups.items():
            total_column = f"{padd} {flow} of {product_name} (Thousand Barrels per Day)"
            if total_column not in header_index:
                raise RuntimeError(f"{clean_path} missing expected {flow.lower()} total {total_column!r}")
            for category in categories:
                category_column = f"{padd} {flow} of {product_name} {preposition} {category} (Thousand Barrels per Day)"
                if category_column not in header_index:
                    raise RuntimeError(f"{clean_path} missing expected {flow.lower()} category {category_column!r}")
            if "Other" not in categories:
                continue
            named_columns = [
                f"{padd} {flow} of {product_name} {preposition} {category} (Thousand Barrels per Day)"
                for category in categories
                if category != "Other"
            ]
            other_column = f"{padd} {flow} of {product_name} {preposition} Other (Thousand Barrels per Day)"
            for row in rows:
                total = Decimal(row[header_index[total_column]])
                named_sum = sum(Decimal(row[header_index[column]]) for column in named_columns)
                other = Decimal(row[header_index[other_column]])
                if total - named_sum != other:
                    raise RuntimeError(f"{clean_path} {flow.lower()} other does not reconcile for {padd} {row[0]}")
    interpadd_markers = [
        "Net Receipts by Pipeline, Tanker, and Barge",
        "Receipts by Pipeline from",
        "Receipts by Pipeline, Tanker, and Barge from",
        "Receipts by Tanker and Barge from",
        "Shipments by Pipeline, Tanker, and Barge",
    ]
    bad_interpadd_columns = [
        column
        for column in header[1:]
        if any(marker in column for marker in interpadd_markers)
        and column.endswith("(Thousand Barrels)")
    ]
    if bad_interpadd_columns:
        raise RuntimeError(f"{clean_path} contains inter-PADD monthly volume columns instead of daily rates")


def validate_monthly_reforming_coverage(clean_path: Path, header: list[str]) -> None:
    header_set = set(header)
    for region in MONTHLY_REFINERY_REGION_LABELS:
        required = [
            f"{region} Downstream Processing of Fresh Feed Input by Catalytic Reforming Units (Thousand Barrels per Day)",
            f"{region} Refinery Catalytic Reforming Downstream Charge Capacity as of January 1 (Thousand Barrels per Day)",
            f"{region} Downstream Processing of Fresh Feed Input by Catalytic Reforming Units / Refinery Catalytic Reforming Downstream Charge Capacity as of January 1 (Percent)",
        ]
        missing = [column for column in required if column not in header_set]
        if missing:
            raise RuntimeError(f"{clean_path} missing reforming input/capacity/utilization columns: {missing}")


def validate_gasoline_monthly_csv(path: Path) -> None:
    clean_path = path / MONTHLY_GASOLINE_OUTPUT
    with clean_path.open(newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader)
        rows = list(reader)
    if not header or header[0] != "Date":
        raise RuntimeError(f"{clean_path} must start with a Date column")
    if len(header) != len(set(header)):
        raise RuntimeError(f"{clean_path} contains duplicate column headers")
    if len(header) < 100:
        raise RuntimeError(f"{clean_path} has too few selected gasoline monthly series columns")
    if not rows:
        raise RuntimeError(f"{clean_path} has no monthly rows")
    months = [row[0] for row in rows]
    if months != sorted(months):
        raise RuntimeError(f"{clean_path} months are not sorted ascending")
    if months[0] < "2016-01-01":
        raise RuntimeError(f"{clean_path} starts before 2016-01-01")
    if any(not month.endswith("-15") for month in months):
        raise RuntimeError(f"{clean_path} dates must be on the 15th of each month")
    for row in rows:
        if len(row) != len(header):
            raise RuntimeError(f"{clean_path} contains a short row")
        if any(value == "" for value in row[1:]):
            raise RuntimeError(f"{clean_path} contains blank data cells")
    required_markers = [
        "Finished Motor Gasoline",
        "Gasoline Blending Components",
        "Fuel Ethanol",
        "Refinery Net Input of Crude Oil",
        "Gross Inputs",
        "Operable Crude Oil Distillation Capacity",
        "Product Supplied of Finished Motor Gasoline",
        "Ending Stocks of Finished Motor Gasoline",
        "Imports of Finished Motor Gasoline",
        "Exports of Finished Motor Gasoline",
        "Ending Stocks of Gasoline Blending Components",
        "Imports of Gasoline Blending Components",
        "Ending Stocks of Fuel Ethanol",
        "Imports of Fuel Ethanol",
        "Exports of Fuel Ethanol",
        "Input",
        "/",
    ]
    for marker in required_markers:
        if not any(marker in column for column in header[1:]):
            raise RuntimeError(f"{clean_path} missing expected gasoline monthly marker {marker!r}")
    validate_monthly_reforming_coverage(clean_path, header)
    if not any("Other (Thousand Barrels per Day)" in column for column in header[1:]):
        raise RuntimeError(f"{clean_path} missing generated import/export Other buckets")
    interpadd_markers = [
        "Net Receipts by Pipeline, Tanker, and Barge",
        "Receipts by Pipeline from",
        "Receipts by Pipeline, Tanker, and Barge from",
        "Receipts by Tanker and Barge from",
        "Shipments by Pipeline, Tanker, and Barge",
    ]
    bad_interpadd_columns = [
        column
        for column in header[1:]
        if any(marker in column for marker in interpadd_markers)
        and column.endswith("(Thousand Barrels)")
    ]
    if bad_interpadd_columns:
        raise RuntimeError(f"{clean_path} contains inter-PADD monthly volume columns instead of daily rates")


def validate_weekly_raw_excel_archive(path: Path, metadata: pq.FileMetaData) -> None:
    archive_path = path / WEEKLY_RAW_EXCEL_OUTPUT
    with tarfile.open(archive_path, "r:xz") as archive:
        members = archive.getmembers()
        if [member.name for member in members] != ["raw.csv"]:
            raise RuntimeError(f"{archive_path} should contain only raw.csv")
        raw_file = archive.extractfile(members[0])
        if raw_file is None:
            raise RuntimeError(f"{archive_path} raw.csv could not be read")
        with raw_file:
            text_file = io.TextIOWrapper(raw_file, encoding="utf-8", newline="")
            reader = csv.reader(text_file)
            header = next(reader)
            if header != pq.read_schema(path / "raw").names:
                raise RuntimeError(f"{archive_path} raw.csv header does not match Parquet raw schema")
            row_count = sum(1 for _ in reader)
    if row_count != metadata.num_rows:
        raise RuntimeError(f"{archive_path} raw.csv row count {row_count} != raw rows {metadata.num_rows}")


def validate_weekly(path: Path, metadata: pq.FileMetaData) -> None:
    manifest = metadata_json(metadata, "eia_manifest")
    if manifest["source_count"] != 9:
        raise RuntimeError("weekly raw must include 9 WPSR workbook sources")
    if sum(source["included_sheet_count"] for source in manifest["sources"]) != 33:
        raise RuntimeError("weekly raw must include all 33 non-first workbook sheets")
    for key in ["first_sheet_skipped_for_all_sources", "all_non_first_sheets_included", "no_rows_before_2016"]:
        if not manifest["validation"].get(key):
            raise RuntimeError(f"weekly raw failed embedded validation {key}")
    table = pq.read_table(path / "raw", columns=["week_ending", "source_table", "source_sheet", "source_column", "region", "subregion", "product", "metric", "unit", "period_type"])
    min_week = pc.min(table["week_ending"]).as_py()
    if min_week < "2016-01-01":
        raise RuntimeError(f"weekly min week {min_week} is before 2016-01-01")
    keys = set(
        zip(
            table["source_table"].to_pylist(),
            table["source_sheet"].to_pylist(),
            table["source_column"].to_pylist(),
            table["region"].to_pylist(),
            table["subregion"].to_pylist(),
            table["product"].to_pylist(),
            table["metric"].to_pylist(),
            table["unit"].to_pylist(),
            table["period_type"].to_pylist(),
        )
    )
    expected_lines = len(keys) + 1
    actual_lines = csv_line_count(path / "series.csv")
    if actual_lines != expected_lines:
        raise RuntimeError(f"weekly series.csv line count {actual_lines} != expected {expected_lines}")

    validate_weekly_raw_excel_archive(path, metadata)
    series_rows = read_weekly_series_rows(path)
    diesel_rows = diesel_mappings(series_rows)
    jet_rows = jet_mappings(series_rows, diesel_rows)
    if not jet_rows:
        raise RuntimeError("weekly jet clean export has no valid matched series")
    validate_weekly_clean_csv(path, WEEKLY_DIESEL_OUTPUT, diesel_rows)
    validate_weekly_clean_csv(path, WEEKLY_JET_OUTPUT, jet_rows)
    gasoline_rows = gasoline_mappings(series_rows)
    if not any("EPM0F" in row["source_column"] for row in gasoline_rows):
        raise RuntimeError("weekly gasoline clean export missing EPM0F source columns")
    if not any("EPOBG" in row["source_column"] for row in gasoline_rows) and not any(
        "Gasoline Blending Components" in row["series_name"] for row in gasoline_rows
    ):
        raise RuntimeError("weekly gasoline clean export missing EPOBG/gasoline blending component source columns")
    if not any("EPOOXE" in row["source_column"] for row in gasoline_rows) and not any(
        "Fuel Ethanol" in row["series_name"] for row in gasoline_rows
    ):
        raise RuntimeError("weekly gasoline clean export missing fuel ethanol source columns")
    validate_weekly_clean_csv(path, WEEKLY_GASOLINE_OUTPUT, gasoline_rows)


def validate_monthly(path: Path, metadata: pq.FileMetaData) -> None:
    manifest = metadata_json(metadata, "eia_manifest")
    expected_slugs = ["move_pipe", "pnp_dwns", "pnp_refp", "pnp_unc", "stoc_ts", "move_tb", "move_ptb", "cons_psup"]
    if manifest["source_count"] != len(expected_slugs):
        raise RuntimeError("monthly raw must include all 8 endpoint sources")
    if [endpoint["slug"] for endpoint in manifest["endpoints"]] != expected_slugs:
        raise RuntimeError("monthly endpoint slug order or membership changed")
    if manifest["start_period"] != "2016-01":
        raise RuntimeError("monthly raw must start at 2016-01")
    table = pq.read_table(path / "raw", columns=["period_month", "source_endpoint", "series", "duoarea_code", "origin_code", "destination_code", "product_code", "unit"])
    min_period = pc.min(table["period_month"]).as_py()
    if min_period < "2016-01-01":
        raise RuntimeError(f"monthly min period {min_period} is before 2016-01-01")
    keys = set(
        zip(
            table["source_endpoint"].to_pylist(),
            table["series"].to_pylist(),
            table["duoarea_code"].to_pylist(),
            table["origin_code"].to_pylist(),
            table["destination_code"].to_pylist(),
            table["product_code"].to_pylist(),
            table["unit"].to_pylist(),
        )
    )
    expected_lines = len(keys) + 1
    actual_lines = csv_line_count(path / "series.csv")
    if actual_lines != expected_lines:
        raise RuntimeError(f"monthly series.csv line count {actual_lines} != expected {expected_lines}")
    validate_monthly_clean_csv(path, MONTHLY_DIESEL_OUTPUT, "Distillate Fuel Oil")
    validate_monthly_clean_csv(path, MONTHLY_JET_OUTPUT, "Kerosene-Type Jet Fuel")
    validate_gasoline_monthly_csv(path)


def validate_dir(name: str) -> None:
    path = Path(name)
    actual = {child.name for child in path.iterdir() if child.name not in {".DS_Store", "cache"}}
    expected_files = EXPECTED_FILES[name]
    if actual != expected_files:
        extra = sorted(actual - expected_files)
        missing = sorted(expected_files - actual)
        raise RuntimeError(f"{name} has unexpected output files; extra={extra} missing={missing}")

    raw_metadata = validate_raw(path / "raw")
    clean_payload = validate_clean(path / "clean") if name == "eia_monthly" else None
    if name == "eia_monthly":
        header = (path / "raw.csv").read_text(encoding="utf-8").strip()
        expected_header = ",".join(pq.read_schema(path / "raw").names)
        if header != expected_header:
            raise RuntimeError(f"{name}/raw.csv must contain only the raw column header")
        if csv_line_count(path / "raw.csv") != 1:
            raise RuntimeError(f"{name}/raw.csv must be header-only")
    series_header = (path / "series.csv").read_text(encoding="utf-8").splitlines()[0]
    if name == "eia_weekly" and "source_column,series_name,region" not in series_header:
        raise RuntimeError("eia_weekly/series.csv missing series inspection columns")
    if name == "eia_monthly" and "series,series_name,region" not in series_header:
        raise RuntimeError("eia_monthly/series.csv missing series inspection columns")
    validate_no_key_leak(path)
    validate_size_limits(name, path)
    if name == "eia_weekly":
        validate_weekly(path, raw_metadata)
    else:
        validate_monthly(path, raw_metadata)
    clean_rows = clean_payload["row_count"] if clean_payload else 0
    clean_bytes = (path / "clean").stat().st_size if clean_payload else 0
    print(
        f"{name}: raw_rows={raw_metadata.num_rows} raw_columns={raw_metadata.num_columns} "
        f"clean_rows={clean_rows} clean_bytes={clean_bytes}"
    )


def validate_final_csv(path: Path) -> tuple[int, int, str, str]:
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    if len(rows) < 2:
        raise RuntimeError(f"{path} must contain a header and at least one data row")
    header = rows[0]
    if len(header) != len(set(header)):
        raise RuntimeError(f"{path} contains duplicate column names")
    dates = [row[0] for row in rows[1:]]
    if dates != sorted(dates, reverse=True):
        raise RuntimeError(f"{path} is not sorted descending by {header[0]}")
    return len(rows) - 1, len(header), dates[0], dates[-1]


def validate_no_monthly_barrel_duplicates(path: Path) -> None:
    header = csv_header(path)
    columns = set(header)
    duplicates = [
        column
        for column in header
        if "(Thousand Barrels)" in column
        and column.replace("(Thousand Barrels)", "(Thousand Barrels per Day)") in columns
    ]
    if duplicates:
        raise RuntimeError(f"{path} still contains Thousand Barrels duplicates: {duplicates[:5]}")


def validate_final_gasoline(path: Path, weekly: bool) -> None:
    header = csv_header(path)
    bad_terms = [
        "Aviation Gasoline Blending Components",
        "Biofuels (incl. Fuel Ethanol)",
        "Conventional CBOB Gasoline Blending Components",
        "Conventional GTAB Gasoline Blending Components",
        "Conventional Gasoline Blending Components",
        "Conventional Other Gasoline Blending Components",
        "Motor Gasoline Blending Components",
        "Reformulated Gasoline Blending Components",
        "Reformulated GTAB Gasoline Blending Components",
        "Reformulated RBOB with Alcohol Gasoline Blending Components",
        "Reformulated RBOB with Ether Gasoline Blending Components",
    ]
    offenders = [column for column in header if any(term.lower() in column.lower() for term in bad_terms)]
    if offenders:
        raise RuntimeError(f"{path} contains unwanted gasoline subtype columns: {offenders[:5]}")
    if weekly:
        required = [
            f"weekly {padd} Imports of {product}"
            for padd in [
                "East Coast (PADD 1)",
                "Midwest (PADD 2)",
                "Gulf Coast (PADD 3)",
                "Rocky Mountain (PADD 4)",
                "West Coast (PADD 5)",
            ]
            for product in ["Finished Motor Gasoline", "Fuel Ethanol", "Gasoline Blending Components"]
        ]
    else:
        required = []
        for product in ["Finished Motor Gasoline", "Fuel Ethanol", "Gasoline Blending Components"]:
            required.extend(
                [
                    f"East Coast (PADD 1) Imports of {product} (Thousand Barrels per Day)",
                    f"East Coast (PADD 1) Imports of {product} from Europe (Thousand Barrels per Day)",
                    f"East Coast (PADD 1) Imports of {product} from Africa (Thousand Barrels per Day)",
                    f"East Coast (PADD 1) Imports of {product} from Middle East (Thousand Barrels per Day)",
                    f"East Coast (PADD 1) Imports of {product} from Canada/Other (Thousand Barrels per Day)",
                    f"Gulf Coast (PADD 3) Exports of {product} (Thousand Barrels per Day)",
                    f"Gulf Coast (PADD 3) Exports of {product} to Africa (Thousand Barrels per Day)",
                    f"Gulf Coast (PADD 3) Exports of {product} to Latin America (Thousand Barrels per Day)",
                    f"Gulf Coast (PADD 3) Exports of {product} to Other (Thousand Barrels per Day)",
                    f"West Coast (PADD 5) Imports of {product} (Thousand Barrels per Day)",
                    f"West Coast (PADD 5) Imports of {product} from Asia including India (Thousand Barrels per Day)",
                    f"West Coast (PADD 5) Imports of {product} from Other (Thousand Barrels per Day)",
                ]
            )
    missing = [column for column in required if column not in header]
    if missing:
        raise RuntimeError(f"{path} missing required gasoline balance columns: {missing[:5]}")


def validate_bulk_series_reference(path: Path) -> None:
    bulk_path = path / "bulk_series.csv"
    expected_header = [
        "bulk_source",
        "series_id",
        "name",
        "region",
        "frequency",
        "units",
        "start",
        "end",
        "last_updated",
        "v2_seriesid_route",
    ]
    if csv_header(bulk_path) != expected_header:
        raise RuntimeError("eia_monthly/bulk_series.csv missing expected filtered bulk-series columns")
    with bulk_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise RuntimeError("eia_monthly/bulk_series.csv is empty")
    sources = {row["bulk_source"] for row in rows}
    if sources != {"PET"}:
        raise RuntimeError(f"eia_monthly/bulk_series.csv must only contain needed PET rows; found sources={sorted(sources)}")
    gasoline_terms = ("gasoline", "fuel ethanol", "blending component")
    for row in rows:
        if not row["series_id"] or not row["name"] or not row["region"]:
            raise RuntimeError("eia_monthly/bulk_series.csv contains a row without series_id, name, or region")
        if row["frequency"] not in {"A", "M"}:
            raise RuntimeError(f"eia_monthly/bulk_series.csv contains unsupported frequency {row['frequency']!r}")
        if row["v2_seriesid_route"] != f"/v2/seriesid/{row['series_id']}":
            raise RuntimeError(f"bad v2 route for {row['series_id']}")
        if any(term in row["name"].lower() for term in gasoline_terms):
            raise RuntimeError(f"eia_monthly/bulk_series.csv contains gasoline-related row {row['series_id']}")


def validate_final_dir(name: str) -> None:
    path = Path(name)
    actual = {child.name for child in path.iterdir() if child.name not in {".DS_Store", "cache"}}
    expected = EXPECTED_FILES[name]
    if actual != expected:
        raise RuntimeError(f"{name} has unexpected final files; extra={sorted(actual - expected)} missing={sorted(expected - actual)}")
    for filename in ["diesel.csv", "jet.csv", "gasoline.csv"]:
        rows, columns, latest, oldest = validate_final_csv(path / filename)
        if name == "eia_monthly":
            validate_no_monthly_barrel_duplicates(path / filename)
        if filename == "gasoline.csv":
            validate_final_gasoline(path / filename, weekly=name == "eia_weekly")
        print(f"{name}/{filename}: rows={rows} columns={columns} latest={latest} oldest={oldest}")
    if name == "eia_monthly":
        validate_bulk_series_reference(path)
        print("eia_monthly/bulk_series.csv: filtered PET reference ok")

def main() -> int:
    validate_final_dir("eia_weekly")
    validate_final_dir("eia_monthly")
    print("validation ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
