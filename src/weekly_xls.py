from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("ARROW_USER_SIMD_LEVEL", "NONE")

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import xlrd


OUT_DIR = Path("eia_weekly")
CACHE_DIR = OUT_DIR / "cache"
HISTORY_WORKBOOK_CACHE_DIR = CACHE_DIR / "eia_history_workbooks"
SHARED_HISTORY_WORKBOOK_CACHE_DIR = Path("eia_summary_dashboard/cache/eia_history_workbooks")
WPSR_LATEST_SIGNATURE_CACHE = CACHE_DIR / "wpsr_latest_signature.txt"
MIN_DATA_WEEK = date(2016, 1, 1)
MIN_DATA_WEEK_ISO = MIN_DATA_WEEK.isoformat()
USER_AGENT = "python-pulls-eia-pipeline/0.2 (build-time data pipeline; local forecast artifacts)"
EIA_WPSR_CSV_TEST_URL = "https://irtest.eia.gov/wpsr/wpsr.csv"
EIA_WPSR_CSV_PROD_URL = "https://ir.eia.gov/wpsr/wpsr.csv"
EIA_WPSR_CSV_PROD_START = date(2026, 6, 10)

HISTORICAL_WORKBOOKS = [
    ("NUS", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_NUS_W.xls"),
    ("R10", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R10_W.xls"),
    ("R1X", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R1X_W.xls"),
    ("R1Y", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R1Y_W.xls"),
    ("R1Z", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R1Z_W.xls"),
    ("R20", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R20_W.xls"),
    ("YCUOK", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_YCUOK_W.xls"),
    ("R30", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R30_W.xls"),
    ("R40", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R40_W.xls"),
    ("R50", "https://www.eia.gov/dnav/pet/xls/PET_SUM_SNDW_DCUS_R50_W.xls"),
]

FIELDS = [
    ("week_ending", pa.string()),
    ("release_date", pa.string()),
    ("source_table", pa.string()),
    ("source_sheet", pa.string()),
    ("section", pa.string()),
    ("metric", pa.string()),
    ("product", pa.string()),
    ("region", pa.string()),
    ("subregion", pa.string()),
    ("unit", pa.string()),
    ("period_type", pa.string()),
    ("value", pa.float64()),
    ("source_column", pa.string()),
    ("source_row_index", pa.uint32()),
]

SCHEMA = pa.schema([pa.field(name, dtype) for name, dtype in FIELDS])
FIELD_NAMES = [name for name, _ in FIELDS]


@dataclass(frozen=True)
class SeriesMeta:
    source_table: str
    source_sheet: str
    source_column: str
    series_name: str
    region: str
    subregion: str
    product: str
    metric: str
    unit: str
    period_type: str


def norm_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def fetch(url: str) -> tuple[bytes, str, dict[str, str], int]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        return body, response.geturl(), dict(response.headers.items()), response.status


def fetch_text(url: str) -> tuple[str, str, dict[str, str], int]:
    body, final_url, headers, status = fetch(url)
    return body.decode("utf-8-sig"), final_url, headers, status


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def date_from_cell(book: xlrd.Book, value: Any) -> date | None:
    if value in ("", None):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return xlrd.xldate.xldate_as_datetime(value, book.datemode).date()
        except Exception:
            return None
    text = norm_spaces(str(value))
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def date_from_text(value: str) -> date:
    text = norm_spaces(value)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"could not parse date: {value!r}")


def parse_number(value: Any) -> float | None:
    if value in ("", None, "--", "NA", "N/A"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "NA", "N/A", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clean_output_dir(path: Path) -> None:
    path.mkdir(exist_ok=True)
    for child in path.iterdir():
        if child.name == "cache":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def parse_series_name(header: str) -> tuple[str, str, str]:
    clean = norm_spaces(header)
    unit = ""
    match = re.search(r"\(([^()]*)\)\s*$", clean)
    if match:
        unit = norm_spaces(match.group(1))
        clean = norm_spaces(clean[: match.start()])

    if clean.lower().startswith("weekly "):
        return "weekly", f"weekly {clean[7:]}", unit
    if clean.lower().startswith("4-week avg "):
        return "4-week", f"4-week {clean[11:]}", unit
    if clean.lower().startswith("4-week "):
        return "4-week", f"4-week {clean[7:]}", unit
    return "weekly", clean, unit


def split_region(series_name: str, period_type: str) -> tuple[str, str, str, str]:
    prefix = f"{period_type} "
    body = series_name[len(prefix) :] if series_name.lower().startswith(prefix) else series_name
    patterns = [
        ("PADD 1 New England (A)", "PADD 1", "New England (A)"),
        ("PADD 1 Central Atlantic (B)", "PADD 1", "Central Atlantic (B)"),
        ("PADD 1 Lower Atlantic (C)", "PADD 1", "Lower Atlantic (C)"),
        ("New England (PADD 1A)", "PADD 1 New England (A)", ""),
        ("Central Atlantic (PADD 1B)", "PADD 1 Central Atlantic (B)", ""),
        ("Lower Atlantic (PADD 1C)", "PADD 1 Lower Atlantic (C)", ""),
        ("East Coast (PADD 1)", "East Coast (PADD 1)", ""),
        ("Midwest (PADD 2)", "Midwest (PADD 2)", ""),
        ("Midwest (PADD2)", "Midwest (PADD 2)", ""),
        ("Gulf Coast (PADD 3)", "Gulf Coast (PADD 3)", ""),
        ("Rocky Mountain (PADD 4)", "Rocky Mountain (PADD 4)", ""),
        ("Rocky Mountain s (PADD 4)", "Rocky Mountain (PADD 4)", ""),
        ("Rocky Mountains (PADD 4)", "Rocky Mountain (PADD 4)", ""),
        ("West Coast (PADD 5)", "West Coast (PADD 5)", ""),
        ("East Coast", "East Coast (PADD 1)", ""),
        ("Midwest", "Midwest (PADD 2)", ""),
        ("Gulf Coast", "Gulf Coast (PADD 3)", ""),
        ("Rocky Mountains", "Rocky Mountain (PADD 4)", ""),
        ("Rocky Mountain", "Rocky Mountain (PADD 4)", ""),
        ("West Coast", "West Coast (PADD 5)", ""),
        ("U. S.", "U.S.", ""),
        ("U.S.", "U.S.", ""),
        ("Total U. S.", "U.S.", ""),
        ("Total", "Total", ""),
        ("Alaska", "Alaska", ""),
        ("Lower 48 States", "Lower 48", ""),
    ]
    for marker, region, subregion in patterns:
        if body.startswith(marker + " "):
            metric = norm_spaces(body[len(marker) :])
            product = f"{subregion} {metric}".strip() if subregion else metric
            return region, subregion, product, product
    return "", "", body, body


def table_from_rows(rows: list[dict[str, Any]]) -> pa.Table:
    columns = {name: [row.get(name) for row in rows] for name in FIELD_NAMES}
    arrays = [pa.array(columns[name], type=dtype) for name, dtype in FIELDS]
    return pa.Table.from_arrays(arrays, schema=SCHEMA)


def parse_workbook_polars(table_id: str, workbook_path: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], SeriesMeta], list[dict[str, Any]]]:
    sheets = pl.read_excel(workbook_path, sheet_id=0, engine="calamine", has_header=False)
    raw_rows: list[dict[str, Any]] = []
    series: dict[tuple[str, str], SeriesMeta] = {}
    inventory: list[dict[str, Any]] = []

    for sheet_index, (sheet_name, df) in enumerate(sheets.items()):
        included = sheet_name.lower().startswith("data") and df.height >= 4 and df.width >= 2
        inventory.append(
            {
                "name": sheet_name,
                "index": sheet_index,
                "row_count": df.height,
                "column_count": df.width,
                "included": included,
                "reason": "data sheet" if included else "not a data sheet",
            }
        )
        if not included:
            continue

        column_names = df.columns
        source_keys = df.row(1)
        headers = df.row(2)
        section = norm_spaces(str(df[0, 1])).split(":", 1)[-1].strip()

        rename: dict[str, str] = {column_names[0]: "week_raw"}
        value_columns: list[str] = []
        meta_by_field: dict[str, SeriesMeta] = {}
        for col_idx in range(1, df.width):
            source_column = norm_spaces(str(source_keys[col_idx])) if col_idx < len(source_keys) and source_keys[col_idx] is not None else ""
            header = norm_spaces(str(headers[col_idx])) if col_idx < len(headers) and headers[col_idx] is not None else ""
            if not source_column or not header:
                continue
            period_type, series_name, unit = parse_series_name(header)
            region, subregion, product, metric = split_region(series_name, period_type)
            meta = SeriesMeta(
                source_table=table_id,
                source_sheet=sheet_name,
                source_column=source_column,
                series_name=series_name,
                region=region,
                subregion=subregion,
                product=product,
                metric=metric,
                unit=unit,
                period_type=period_type,
            )
            field = f"value_{col_idx}"
            rename[column_names[col_idx]] = field
            value_columns.append(field)
            meta_by_field[field] = meta
            series.setdefault((source_column, series_name), meta)

        if not value_columns:
            continue

        long_df = (
            df.slice(3)
            .select([pl.col(name) for name in rename])
            .rename(rename)
            .unpivot(index="week_raw", on=value_columns, variable_name="field", value_name="value_raw")
            .with_columns(
                week_ending=pl.col("week_raw")
                .cast(pl.Utf8)
                .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
                .dt.date()
                .cast(pl.Utf8),
                value=pl.col("value_raw").cast(pl.Utf8).str.replace_all(",", "").cast(pl.Float64, strict=False),
            )
            .filter(pl.col("week_ending").is_not_null() & pl.col("value").is_not_null())
            .filter(pl.col("week_ending") >= MIN_DATA_WEEK_ISO)
        )

        for row_idx, row in enumerate(long_df.iter_rows(named=True), start=3):
            meta = meta_by_field[row["field"]]
            raw_rows.append(
                {
                    "week_ending": row["week_ending"],
                    "release_date": "",
                    "source_table": meta.source_table,
                    "source_sheet": meta.source_sheet,
                    "section": section,
                    "metric": meta.metric,
                    "product": meta.product,
                    "region": meta.region,
                    "subregion": meta.subregion,
                    "unit": meta.unit,
                    "period_type": meta.period_type,
                    "value": float(row["value"]),
                    "source_column": meta.source_column,
                    "source_row_index": row_idx,
                }
            )

    return raw_rows, series, inventory


def parse_workbook_xlrd(table_id: str, workbook_path: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], SeriesMeta], list[dict[str, Any]]]:
    raw_rows: list[dict[str, Any]] = []
    series: dict[tuple[str, str], SeriesMeta] = {}
    inventory: list[dict[str, Any]] = []
    book = xlrd.open_workbook(str(workbook_path), on_demand=True)
    try:
        for sheet_index, sheet_name in enumerate(book.sheet_names()):
            sheet = book.sheet_by_index(sheet_index)
            included = sheet.name.lower().startswith("data") and sheet.nrows >= 4 and sheet.ncols >= 2
            inventory.append(
                {
                    "name": sheet.name,
                    "index": sheet_index,
                    "row_count": sheet.nrows,
                    "column_count": sheet.ncols,
                    "included": included,
                    "reason": "data sheet" if included else "not a data sheet",
                }
            )
            if not included:
                continue

            source_keys = sheet.row_values(1)
            headers = sheet.row_values(2)
            section = norm_spaces(str(sheet.cell_value(0, 1))).split(":", 1)[-1].strip()
            sheet_series: dict[int, SeriesMeta] = {}
            for col in range(1, sheet.ncols):
                source_column = norm_spaces(str(source_keys[col])) if col < len(source_keys) else ""
                header = norm_spaces(str(headers[col])) if col < len(headers) else ""
                if not source_column or not header:
                    continue
                period_type, series_name, unit = parse_series_name(header)
                region, subregion, product, metric = split_region(series_name, period_type)
                meta = SeriesMeta(
                    source_table=table_id,
                    source_sheet=sheet.name,
                    source_column=source_column,
                    series_name=series_name,
                    region=region,
                    subregion=subregion,
                    product=product,
                    metric=metric,
                    unit=unit,
                    period_type=period_type,
                )
                sheet_series[col] = meta
                series.setdefault((source_column, series_name), meta)

            for row_idx in range(3, sheet.nrows):
                week = date_from_cell(book, sheet.cell_value(row_idx, 0))
                if week is None or week < MIN_DATA_WEEK:
                    continue
                for col, meta in sheet_series.items():
                    value = parse_number(sheet.cell_value(row_idx, col))
                    if value is None:
                        continue
                    raw_rows.append(
                        {
                            "week_ending": week.isoformat(),
                            "release_date": "",
                            "source_table": meta.source_table,
                            "source_sheet": meta.source_sheet,
                            "section": section,
                            "metric": meta.metric,
                            "product": meta.product,
                            "region": meta.region,
                            "subregion": meta.subregion,
                            "unit": meta.unit,
                            "period_type": meta.period_type,
                            "value": value,
                            "source_column": meta.source_column,
                            "source_row_index": row_idx,
                        }
                    )
    finally:
        book.release_resources()
    return raw_rows, series, inventory


def parse_workbook(table_id: str, workbook_path: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], SeriesMeta], list[dict[str, Any]]]:
    try:
        return parse_workbook_polars(table_id, workbook_path)
    except Exception:
        return parse_workbook_xlrd(table_id, workbook_path)


def cached_workbook_path(table_id: str) -> Path:
    return HISTORY_WORKBOOK_CACHE_DIR / f"{table_id}.xls"


def ensure_workbook(table_id: str, url: str, force_download: bool) -> tuple[Path, dict[str, Any]]:
    cache_path = cached_workbook_path(table_id)
    if cache_path.exists() and not force_download:
        body = cache_path.read_bytes()
        return cache_path, {"cache_status": "local", "bytes": len(body), "sha256": sha256(body)}

    shared_path = SHARED_HISTORY_WORKBOOK_CACHE_DIR / f"{table_id}.xls"
    if shared_path.exists() and not force_download:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared_path, cache_path)
        body = cache_path.read_bytes()
        return cache_path, {"cache_status": "copied_from_dashboard_cache", "bytes": len(body), "sha256": sha256(body)}

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    body, final_url, headers, status = fetch(url)
    if len(body) < 1000:
        raise ValueError(f"downloaded workbook from {url} is unexpectedly small")
    cache_path.write_bytes(body)
    return cache_path, {
        "cache_status": "downloaded",
        "final_url_host": urllib.parse.urlparse(final_url).netloc,
        "status": status,
        "etag": headers.get("ETag"),
        "last_modified": headers.get("Last-Modified"),
        "bytes": len(body),
        "sha256": sha256(body),
    }


def wpsr_csv_url(today: date | None = None) -> str:
    today = today or date.today()
    return EIA_WPSR_CSV_PROD_URL if today >= EIA_WPSR_CSV_PROD_START else EIA_WPSR_CSV_TEST_URL


def latest_signature(source_url: str, release_date: str, current_week: str, week_ago: str, series_count: int) -> str:
    return json.dumps(
        {
            "source_url": source_url,
            "release_date": release_date,
            "current_week": current_week,
            "week_ago": week_ago,
            "series_count": series_count,
        },
        sort_keys=True,
    )


def series_name_from_wpsr(row: dict[str, Any]) -> tuple[str, str, str]:
    unit = norm_spaces(str(row.get("units", "")))
    desc = norm_spaces(str(row.get("sourcekey_desc", "")))
    if desc:
        desc = re.sub(r"\s*\([^()]*(?:Barrels|Percent|Gallons)[^()]*\)\s*$", "", desc)
        if desc.lower().startswith("weekly "):
            return "weekly", f"weekly {desc[7:]}", unit
        return "weekly", f"weekly {desc}", unit
    name = norm_spaces(" ".join(str(row.get(k, "")) for k in ("stub_1", "stub_2") if row.get(k)))
    return "weekly", f"weekly {name}", unit


def read_wpsr_csv_rows(text: str) -> tuple[list[dict[str, Any]], list[str], str]:
    lines = text.splitlines()
    header_index = next((idx for idx, line in enumerate(lines) if line.startswith("stub_1,")), None)
    if header_index is None:
        raise ValueError("WPSR CSV did not contain the expected stub_1 header")
    csv_body = "\n".join(lines[header_index:])
    df = pl.read_csv(io.BytesIO(csv_body.encode("utf-8")), infer_schema=False)
    return df.to_dicts(), df.columns, "\n".join(lines[:header_index])


def release_date_from_wpsr_preamble(preamble: str) -> date:
    match = re.search(r"Released:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", preamble)
    if not match:
        raise ValueError("WPSR CSV preamble did not contain a release date")
    return date_from_text(match.group(1))


def parse_wpsr_csv(text: str, source_url: str) -> tuple[list[dict[str, Any]], dict[tuple[str, str], SeriesMeta], str, str, dict[str, Any]]:
    csv_rows, columns, preamble = read_wpsr_csv_rows(text)
    if len(columns) < 4:
        raise ValueError("WPSR CSV is missing current/week-ago columns")
    current_column = columns[2]
    week_ago_column = columns[3]
    current_week = date_from_text(current_column)
    week_ago = date_from_text(week_ago_column)
    release_date = release_date_from_wpsr_preamble(preamble).isoformat()
    week_columns = [(current_column, current_week), (week_ago_column, week_ago)]

    raw_rows: list[dict[str, Any]] = []
    series: dict[tuple[str, str], SeriesMeta] = {}
    for item in csv_rows:
        source_column = norm_spaces(str(item.get("sourcekey", "")))
        if not source_column:
            continue
        period_type, series_name, unit = series_name_from_wpsr(item)
        region, subregion, product, metric = split_region(series_name, period_type)
        section = norm_spaces(str(item.get("stub_1", "")))
        meta = SeriesMeta(
            source_table="WPSR_CSV",
            source_sheet=source_url,
            source_column=source_column,
            series_name=series_name,
            region=region,
            subregion=subregion,
            product=product or norm_spaces(str(item.get("stub_2", ""))),
            metric=metric or norm_spaces(str(item.get("stub_2", ""))),
            unit=unit,
            period_type=period_type,
        )
        series.setdefault((source_column, series_name), meta)
        for column_name, week in week_columns:
            value = parse_number(item.get(column_name))
            if value is None:
                continue
            raw_rows.append(
                {
                    "week_ending": week.isoformat(),
                    "release_date": release_date,
                    "source_table": meta.source_table,
                    "source_sheet": meta.source_sheet,
                    "section": section,
                    "metric": meta.metric,
                    "product": meta.product,
                    "region": meta.region,
                    "subregion": meta.subregion,
                    "unit": meta.unit,
                    "period_type": meta.period_type,
                    "value": value,
                    "source_column": meta.source_column,
                    "source_row_index": None,
                }
            )

    signature = latest_signature(source_url, release_date, current_week.isoformat(), week_ago.isoformat(), len(csv_rows))
    inventory = {
        "source_url": source_url,
        "release_date": release_date,
        "current_week": current_week.isoformat(),
        "week_ago": week_ago.isoformat(),
        "series_count": len(csv_rows),
        "row_count": len(raw_rows),
    }
    return raw_rows, series, release_date, signature, inventory


def download_latest_wpsr_rows() -> tuple[list[dict[str, Any]], dict[tuple[str, str], SeriesMeta], str, str, dict[str, Any]]:
    csv_url = wpsr_csv_url()
    text, final_url, headers, status = fetch_text(csv_url)
    rows, series, release_date, signature, inventory = parse_wpsr_csv(text, csv_url)
    inventory.update(
        {
            "final_url_host": urllib.parse.urlparse(final_url).netloc,
            "status": status,
            "etag": headers.get("ETag"),
            "last_modified": headers.get("Last-Modified"),
        }
    )
    return rows, series, release_date, signature, inventory


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("week_ending", "") < MIN_DATA_WEEK_ISO:
            continue
        key = (row["week_ending"], row["source_column"], row["period_type"])
        by_key[key] = row
    return sorted(by_key.values(), key=lambda row: (row["week_ending"], row["source_column"], row["period_type"]))


def fetch_parse_history(table_id: str, url: str, force_download: bool) -> tuple[list[dict[str, Any]], dict[tuple[str, str], SeriesMeta], dict[str, Any]]:
    workbook_path, source_info = ensure_workbook(table_id, url, force_download)
    rows, series, sheet_inventory = parse_workbook(table_id, workbook_path)
    source_info.update(
        {
            "table": table_id,
            "xls_url": url,
            "row_count": len(rows),
            "sheet_inventory": sheet_inventory,
            "included_sheet_count": sum(1 for sheet in sheet_inventory if sheet["included"]),
        }
    )
    return rows, series, source_info


def load_history(force_download: bool) -> tuple[list[dict[str, Any]], dict[tuple[str, str], SeriesMeta], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    all_series: dict[tuple[str, str], SeriesMeta] = {}
    source_manifest: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(10, len(HISTORICAL_WORKBOOKS))) as executor:
        futures = {
            executor.submit(fetch_parse_history, table_id, url, force_download): table_id
            for table_id, url in HISTORICAL_WORKBOOKS
        }
        results = {futures[future]: future.result() for future in as_completed(futures)}
    for table_id, _url in HISTORICAL_WORKBOOKS:
        rows, series, source_info = results[table_id]
        all_rows.extend(rows)
        all_series.update(series)
        source_manifest.append(source_info)
    if not all_rows:
        raise ValueError("no rows parsed from EIA historical dnav workbooks")
    return dedupe_rows(all_rows), all_series, source_manifest


def write_raw(path: Path, table: pa.Table, manifest: dict[str, Any]) -> int:
    metadata_bytes = {
        b"eia_manifest": json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8"),
    }
    table = table.replace_schema_metadata(metadata_bytes)
    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=9,
        use_dictionary=True,
        row_group_size=100_000,
        write_statistics=True,
    )
    if pq.read_metadata(path).num_rows != table.num_rows:
        raise RuntimeError(f"Raw Parquet row-count mismatch for {path}")
    return path.stat().st_size


def write_latest_signature(signature: str) -> None:
    WPSR_LATEST_SIGNATURE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    WPSR_LATEST_SIGNATURE_CACHE.write_text(signature, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build EIA weekly raw data from dnav history plus WPSR CSV latest overlay.")
    parser.add_argument("--force-history", action="store_true", help="redownload the historical dnav workbooks instead of using cache")
    args = parser.parse_args()

    clean_output_dir(OUT_DIR)

    with ThreadPoolExecutor(max_workers=2) as executor:
        history_future = executor.submit(load_history, args.force_history)
        latest_future = executor.submit(download_latest_wpsr_rows)
        history_rows, history_series, history_manifest = history_future.result()
        latest_rows, latest_series, latest_release_date, latest_signature_value, latest_manifest = latest_future.result()

    rows = dedupe_rows([*history_rows, *latest_rows])
    latest_weeks = {row["week_ending"] for row in latest_rows}
    latest_week = max(row["week_ending"] for row in rows if row["period_type"] == "weekly")
    for row in rows:
        if not row["release_date"]:
            row["release_date"] = latest_release_date if row["week_ending"] in latest_weeks else latest_week

    all_series = dict(history_series)
    all_series.update(latest_series)
    table = table_from_rows(rows)
    min_week = min((row["week_ending"] for row in rows), default="")
    max_week = max((row["week_ending"] for row in rows), default="")
    manifest = {
        "pipeline_name": "eia_weekly",
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(HISTORICAL_WORKBOOKS) + 1,
        "historical_source_count": len(HISTORICAL_WORKBOOKS),
        "latest_source_count": 1,
        "row_count": table.num_rows,
        "series_count": len(all_series),
        "column_count": len(FIELD_NAMES),
        "min_week_ending": min_week,
        "max_week_ending": max_week,
        "min_data_week": MIN_DATA_WEEK_ISO,
        "primary_source_format": "historical_dnav_xls_plus_wpsr_csv",
        "transition_policy": "Historical dnav workbooks provide the long history; WPSR CSV provides the latest current/week-ago overlay and wins on duplicate week/sourcekey/period_type keys.",
        "wpsr_csv_production_start": EIA_WPSR_CSV_PROD_START.isoformat(),
        "latest_source": latest_manifest,
        "sources": history_manifest,
        "schema": [{"name": name, "type": str(dtype)} for name, dtype in FIELDS],
        "validation": {
            "no_rows_before_2016": all(row["week_ending"] >= MIN_DATA_WEEK_ISO for row in rows),
            "latest_overlay_rows_present": len(latest_rows) > 0,
            "latest_overlay_uses_sourcekey": all(bool(row["source_column"]) for row in latest_rows),
            "historical_workbook_count": len(history_manifest),
        },
        "artifact_files": {
            "raw": {"path": str(OUT_DIR / "raw"), "format": "parquet_zstd"},
            "diesel.csv": {"path": str(OUT_DIR / "diesel.csv"), "format": "csv"},
            "jet.csv": {"path": str(OUT_DIR / "jet.csv"), "format": "csv"},
            "gasoline.csv": {"path": str(OUT_DIR / "gasoline.csv"), "format": "csv"},
            "series.csv": {"path": str(OUT_DIR / "series.csv"), "format": "csv"},
        },
    }

    raw_bytes = write_raw(OUT_DIR / "raw", table, manifest)
    write_latest_signature(latest_signature_value)
    print(
        f"weekly rows={table.num_rows} raw={raw_bytes} latest_week={latest_week} "
        f"wpsr_url={latest_manifest['source_url']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
