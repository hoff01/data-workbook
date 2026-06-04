from __future__ import annotations

import csv
import io
import json
import re
import tarfile
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import polars as pl
import xlrd


EIA_WPSR_CSV_TEST_URL = "https://irtest.eia.gov/wpsr/wpsr.csv"
EIA_WPSR_CSV_PROD_URL = "https://ir.eia.gov/wpsr/wpsr.csv"
EIA_WPSR_CSV_PROD_START = date(2026, 6, 10)
CACHE_DIR = "cache"
HISTORY_RAW_CACHE = "eia_history_raw.csv.tar.xz"
HISTORY_SERIES_CACHE = "eia_history_series.csv"
HISTORY_WORKBOOK_CACHE_DIR = "eia_history_workbooks"
WPSR_LATEST_SIGNATURE_CACHE = "wpsr_latest_signature.txt"
MIN_DATA_WEEK = date(2016, 1, 1)
MIN_DATA_WEEK_ISO = MIN_DATA_WEEK.isoformat()

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

RAW_FIELDS = [
    "week_ending",
    "release_date",
    "source_table",
    "source_sheet",
    "section",
    "metric",
    "product",
    "region",
    "subregion",
    "unit",
    "period_type",
    "value",
    "source_column",
    "source_row_index",
]

SERIES_FIELDS = [
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


def _norm_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _date_from_cell(book: xlrd.Book, value) -> date | None:
    if value in ("", None):
        return None
    if isinstance(value, (int, float)):
        return xlrd.xldate.xldate_as_datetime(value, book.datemode).date()
    text = _norm_spaces(str(value))
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            from datetime import datetime

            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _date_from_text(value: str) -> date:
    text = _norm_spaces(value)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"could not parse date: {value!r}")


def _parse_number(value) -> float | None:
    if value in ("", None, "--", "NA", "N/A"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "NA", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _filter_min_data_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("week_ending", "") >= MIN_DATA_WEEK_ISO]


def _parse_series_name(header: str) -> tuple[str, str, str]:
    clean = _norm_spaces(header)
    unit = ""
    match = re.search(r"\(([^()]*)\)\s*$", clean)
    if match:
        unit = _norm_spaces(match.group(1))
        clean = _norm_spaces(clean[:match.start()])

    if clean.lower().startswith("weekly "):
        return "weekly", f"weekly {clean[7:]}", unit
    if clean.lower().startswith("4-week avg "):
        return "4-week", f"4-week {clean[11:]}", unit
    if clean.lower().startswith("4-week "):
        return "4-week", f"4-week {clean[7:]}", unit
    return "weekly", clean, unit


def _split_region(series_name: str, period_type: str) -> tuple[str, str, str, str]:
    prefix = f"{period_type} "
    body = series_name[len(prefix):] if series_name.startswith(prefix) else series_name
    patterns = [
        ("PADD 1 New England (A)", "PADD 1", "New England (A)"),
        ("PADD 1 Central Atlantic (B)", "PADD 1", "Central Atlantic (B)"),
        ("PADD 1 Lower Atlantic (C)", "PADD 1", "Lower Atlantic (C)"),
        ("East Coast (PADD 1)", "East Coast", ""),
        ("Midwest (PADD 2)", "Midwest", ""),
        ("Gulf Coast (PADD 3)", "Gulf Coast", ""),
        ("Rocky Mountain (PADD 4)", "Rocky Mountain", ""),
        ("Rocky Mountain s (PADD 4)", "Rocky Mountain", ""),
        ("West Coast (PADD 5)", "West Coast", ""),
        ("U.S.", "U.S.", ""),
        ("Total U. S.", "Total", ""),
        ("Total", "Total", ""),
        ("Alaska", "Alaska", ""),
        ("Lower 48 States", "Lower 48", ""),
    ]
    for marker, region, subregion in patterns:
        if body.startswith(marker + " "):
            metric = _norm_spaces(body[len(marker):])
            product = f"{subregion} {metric}".strip() if subregion else metric
            return region, subregion, product, product
    return "", "", body, body


def _download(url: str, output_path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "eia-summary-dashboard/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if len(data) < 1000:
        raise ValueError(f"downloaded file from {url} is unexpectedly small")
    output_path.write_bytes(data)


def _download_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "eia-summary-dashboard/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8-sig")


def _wpsr_csv_url(today: date | None = None) -> str:
    today = today or date.today()
    return EIA_WPSR_CSV_PROD_URL if today >= EIA_WPSR_CSV_PROD_START else EIA_WPSR_CSV_TEST_URL


def _latest_signature(source_url: str, release_date: str, current_week: str, week_ago: str, series_count: int) -> str:
    data = {
        "source_url": source_url,
        "release_date": release_date,
        "current_week": current_week,
        "week_ago": week_ago,
        "series_count": series_count,
    }
    return json.dumps(data, sort_keys=True)


def _parse_workbook_xlrd(table_id: str, workbook_path: Path) -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta]]:
    book = xlrd.open_workbook(str(workbook_path))
    raw_rows: list[dict[str, str]] = []
    series: dict[tuple[str, str], SeriesMeta] = {}

    for sheet in book.sheets():
        if sheet.name.lower() == "contents" or not sheet.name.lower().startswith("data"):
            continue
        if sheet.nrows < 4 or sheet.ncols < 2:
            continue
        source_keys = sheet.row_values(1)
        headers = sheet.row_values(2)
        sheet_series: dict[int, SeriesMeta] = {}
        section = _norm_spaces(str(sheet.cell_value(0, 1))).split(":", 1)[-1].strip()

        for col in range(1, sheet.ncols):
            source_column = _norm_spaces(str(source_keys[col])) if col < len(source_keys) else ""
            header = _norm_spaces(str(headers[col])) if col < len(headers) else ""
            if not source_column or not header:
                continue
            period_type, series_name, unit = _parse_series_name(header)
            region, subregion, product, metric = _split_region(series_name, period_type)
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
            week = _date_from_cell(book, sheet.cell_value(row_idx, 0))
            if week is None:
                continue
            if week < MIN_DATA_WEEK:
                continue
            for col, meta in sheet_series.items():
                value = sheet.cell_value(row_idx, col)
                if value in ("", None):
                    continue
                if not isinstance(value, (int, float)):
                    continue
                raw_rows.append({
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
                    "value": str(float(value)),
                    "source_column": meta.source_column,
                    "source_row_index": str(row_idx),
                })

    return raw_rows, series


def _parse_workbook_polars(table_id: str, workbook_path: Path) -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta]]:
    sheets = pl.read_excel(workbook_path, sheet_id=0, engine="calamine", has_header=False)
    raw_rows: list[dict[str, str]] = []
    series: dict[tuple[str, str], SeriesMeta] = {}

    for sheet_name, df in sheets.items():
        if sheet_name.lower() == "contents" or not sheet_name.lower().startswith("data"):
            continue
        if df.height < 4 or df.width < 2:
            continue

        column_names = df.columns
        source_keys = df.row(1)
        headers = df.row(2)
        sheet_series: dict[str, SeriesMeta] = {}
        section = _norm_spaces(str(df[0, 1])).split(":", 1)[-1].strip()

        rename: dict[str, str] = {column_names[0]: "week_raw"}
        value_columns: list[str] = []
        meta_by_field: dict[str, SeriesMeta] = {}
        for col_idx in range(1, df.width):
            source_column = _norm_spaces(str(source_keys[col_idx])) if col_idx < len(source_keys) and source_keys[col_idx] is not None else ""
            header = _norm_spaces(str(headers[col_idx])) if col_idx < len(headers) and headers[col_idx] is not None else ""
            if not source_column or not header:
                continue
            period_type, series_name, unit = _parse_series_name(header)
            region, subregion, product, metric = _split_region(series_name, period_type)
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
            sheet_series[field] = meta
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
            raw_rows.append({
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
                "value": str(float(row["value"])),
                "source_column": meta.source_column,
                "source_row_index": str(row_idx),
            })

    return raw_rows, series


def _parse_workbook(table_id: str, workbook_path: Path) -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta]]:
    try:
        return _parse_workbook_polars(table_id, workbook_path)
    except Exception:
        return _parse_workbook_xlrd(table_id, workbook_path)


def _series_name_from_wpsr(row: dict) -> tuple[str, str, str]:
    unit = _norm_spaces(str(row.get("units", "")))
    desc = _norm_spaces(str(row.get("sourcekey_desc", "")))
    if desc:
        desc = re.sub(r"\s*\([^()]*(?:Barrels|Percent|Gallons)[^()]*\)\s*$", "", desc)
        if desc.lower().startswith("weekly "):
            return "weekly", desc, unit
        return "weekly", f"weekly {desc}", unit
    name = _norm_spaces(" ".join(str(row.get(k, "")) for k in ("stub_1", "stub_2") if row.get(k)))
    return "weekly", f"weekly {name}", unit


def _read_wpsr_csv_rows(text: str) -> tuple[list[dict], list[str], str]:
    lines = text.splitlines()
    header_index = next((idx for idx, line in enumerate(lines) if line.startswith("stub_1,")), None)
    if header_index is None:
        raise ValueError("WPSR CSV did not contain the expected stub_1 header")
    csv_body = "\n".join(lines[header_index:])
    df = pl.read_csv(io.BytesIO(csv_body.encode("utf-8")), infer_schema=False)
    return df.to_dicts(), df.columns, "\n".join(lines[:header_index])


def _release_date_from_wpsr_preamble(preamble: str) -> date:
    match = re.search(r"Released:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", preamble)
    if not match:
        raise ValueError("WPSR CSV preamble did not contain a release date")
    return _date_from_text(match.group(1))


def _parse_wpsr_csv(text: str, source_url: str) -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta], str, str]:
    csv_rows, columns, preamble = _read_wpsr_csv_rows(text)
    if len(columns) < 4:
        raise ValueError("WPSR CSV is missing current/week-ago columns")
    current_column = columns[2]
    week_ago_column = columns[3]
    current_week = _date_from_text(current_column)
    week_ago = _date_from_text(week_ago_column)
    release_date = _release_date_from_wpsr_preamble(preamble).isoformat()
    week_columns = [(current_column, current_week), (week_ago_column, week_ago)]

    raw_rows: list[dict[str, str]] = []
    series: dict[tuple[str, str], SeriesMeta] = {}
    for item in csv_rows:
        if not isinstance(item, dict):
            continue
        source_column = _norm_spaces(str(item.get("sourcekey", "")))
        if not source_column:
            continue
        period_type, series_name, unit = _series_name_from_wpsr(item)
        region, subregion, product, metric = _split_region(series_name, period_type)
        section = _norm_spaces(str(item.get("stub_1", "")))
        meta = SeriesMeta(
            source_table="WPSR_CSV",
            source_sheet=source_url,
            source_column=source_column,
            series_name=series_name,
            region=region,
            subregion=subregion,
            product=product or _norm_spaces(str(item.get("stub_2", ""))),
            metric=metric or _norm_spaces(str(item.get("stub_2", ""))),
            unit=unit,
            period_type=period_type,
        )
        series.setdefault((source_column, series_name), meta)
        for column_name, week in week_columns:
            value = _parse_number(item.get(column_name))
            if value is None:
                continue
            raw_rows.append({
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
                "value": str(value),
                "source_column": meta.source_column,
                "source_row_index": "",
            })

    signature = _latest_signature(source_url, release_date, current_week.isoformat(), week_ago.isoformat(), len(csv_rows))
    return raw_rows, series, release_date, signature


def _dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in _filter_min_data_rows(rows):
        key = (row["week_ending"], row["source_column"], row["period_type"])
        by_key[key] = row
    return sorted(by_key.values(), key=lambda r: (r["week_ending"], r["source_column"], r["period_type"]))


def _read_raw_archive(path: Path) -> list[dict[str, str]]:
    with tarfile.open(path, "r:*") as tf:
        raw = tf.extractfile("raw.csv")
        if raw is None:
            raise ValueError(f"{path} does not contain raw.csv")
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
        return [dict(row) for row in reader]


def _read_series(path: Path) -> dict[tuple[str, str], SeriesMeta]:
    series: dict[tuple[str, str], SeriesMeta] = {}
    if not path.exists():
        return series
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            meta = SeriesMeta(
                source_table=row["source_table"],
                source_sheet=row["source_sheet"],
                source_column=row["source_column"],
                series_name=row["series_name"],
                region=row["region"],
                subregion=row["subregion"],
                product=row["product"],
                metric=row["metric"],
                unit=row["unit"],
                period_type=row["period_type"],
            )
            series[(meta.source_column, meta.series_name)] = meta
    return series


def _write_data_paths(
    raw_archive: Path,
    series_path: Path,
    rows: list[dict[str, str]],
    series: dict[tuple[str, str], SeriesMeta],
) -> tuple[int, int, str]:
    rows = _filter_min_data_rows(rows)
    if not rows:
        raise ValueError("no rows available to write")

    latest_week = max(row["week_ending"] for row in rows if row["period_type"] == "weekly")
    raw_archive.parent.mkdir(parents=True, exist_ok=True)
    series_path.parent.mkdir(parents=True, exist_ok=True)

    raw_csv = io.StringIO()
    writer = csv.DictWriter(raw_csv, fieldnames=RAW_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    raw_bytes = raw_csv.getvalue().encode("utf-8")

    raw_tmp = raw_archive.with_suffix(raw_archive.suffix + ".tmp")
    with tarfile.open(raw_tmp, "w:gz", compresslevel=1) as tf:
        info = tarfile.TarInfo("raw.csv")
        info.size = len(raw_bytes)
        tf.addfile(info, io.BytesIO(raw_bytes))
    raw_tmp.replace(raw_archive)

    series_tmp = series_path.with_suffix(series_path.suffix + ".tmp")
    with series_tmp.open("w", newline="") as f:
        series_writer = csv.DictWriter(f, fieldnames=SERIES_FIELDS)
        series_writer.writeheader()
        for meta in sorted(series.values(), key=lambda m: (m.source_table, m.source_sheet, m.source_column, m.series_name)):
            series_writer.writerow({
                "source_table": meta.source_table,
                "source_sheet": meta.source_sheet,
                "source_column": meta.source_column,
                "series_name": meta.series_name,
                "region": meta.region,
                "subregion": meta.subregion,
                "product": meta.product,
                "metric": meta.metric,
                "unit": meta.unit,
                "period_type": meta.period_type,
            })
    series_tmp.replace(series_path)

    meta = {
        "rows": len(rows),
        "series": len(series),
        "latest_week": latest_week,
    }
    raw_archive.with_name(raw_archive.name + ".meta.json").write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")

    return len(rows), len(series), latest_week


def _write_data_files(root: Path, rows: list[dict[str, str]], series: dict[tuple[str, str], SeriesMeta]) -> tuple[int, int, str]:
    return _write_data_paths(root / "raw.csv.tar.xz", root / "series.csv", rows, series)


def _history_cache_paths(root: Path) -> tuple[Path, Path]:
    cache_dir = root / CACHE_DIR
    return cache_dir / HISTORY_RAW_CACHE, cache_dir / HISTORY_SERIES_CACHE


def _history_workbook_cache_dir(root: Path) -> Path:
    return root / CACHE_DIR / HISTORY_WORKBOOK_CACHE_DIR


def _download_latest_wpsr_text() -> tuple[str, str]:
    csv_url = _wpsr_csv_url()
    return _download_text(csv_url), csv_url


def _download_latest_wpsr_rows() -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta], str, str]:
    text, csv_url = _download_latest_wpsr_text()
    return _parse_wpsr_csv(text, csv_url)


def _read_data_meta(raw_archive: Path) -> tuple[int, int, str] | None:
    meta_path = raw_archive.with_name(raw_archive.name + ".meta.json")
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return int(meta["rows"]), int(meta["series"]), str(meta["latest_week"])


def _latest_signature_path(root: Path) -> Path:
    return root / CACHE_DIR / WPSR_LATEST_SIGNATURE_CACHE


def _write_latest_signature(root: Path, signature: str) -> None:
    signature_path = _latest_signature_path(root)
    signature_path.parent.mkdir(parents=True, exist_ok=True)
    signature_path.write_text(signature, encoding="utf-8")


def refresh_wpsr_latest_data(root: Path) -> tuple[int, int, str]:
    raw_archive = root / "raw.csv.tar.xz"
    if not raw_archive.exists():
        raise FileNotFoundError(f"{raw_archive} does not exist; run --refresh-eia-weekly once to bootstrap history")

    latest_rows, latest_series, _latest_release_date, signature = _download_latest_wpsr_rows()
    signature_path = _latest_signature_path(root)
    if signature_path.exists() and signature_path.read_text(encoding="utf-8") == signature:
        meta = _read_data_meta(raw_archive)
        if meta is not None:
            return meta

    all_rows = _read_raw_archive(raw_archive)
    all_series = _read_series(root / "series.csv")
    all_rows = _dedupe_rows([*all_rows, *latest_rows])
    all_series.update(latest_series)
    result = _write_data_files(root, all_rows, all_series)
    _write_latest_signature(root, signature)
    return result


def _download_historical_data(root: Path | None = None, force_download: bool = False) -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta]]:
    all_rows: list[dict[str, str]] = []
    all_series: dict[tuple[str, str], SeriesMeta] = {}

    with tempfile.TemporaryDirectory(prefix="eia_wpsr_") as temp_dir:
        temp_path = Path(temp_dir)
        def download_and_parse(table_id: str, url: str) -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta]]:
            cache_path = _history_workbook_cache_dir(root) / f"{table_id}.xls" if root is not None else None
            if cache_path is not None and cache_path.exists() and not force_download:
                return _parse_workbook(table_id, cache_path)

            workbook_path = temp_path / f"{table_id}.xls"
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                _download(url, workbook_path)
                workbook_path.replace(cache_path)
                return _parse_workbook(table_id, cache_path)

            _download(url, workbook_path)
            return _parse_workbook(table_id, workbook_path)

        with ThreadPoolExecutor(max_workers=min(10, len(HISTORICAL_WORKBOOKS))) as executor:
            futures = [
                executor.submit(download_and_parse, table_id, url)
                for table_id, url in HISTORICAL_WORKBOOKS
            ]
            for future in as_completed(futures):
                rows, series = future.result()
                all_rows.extend(rows)
                all_series.update(series)

    if not all_rows:
        raise ValueError("no rows parsed from EIA historical workbooks")

    all_rows = _dedupe_rows(all_rows)
    latest_week = max(row["week_ending"] for row in all_rows if row["period_type"] == "weekly")
    for row in all_rows:
        if not row["release_date"]:
            row["release_date"] = latest_week
    return all_rows, all_series


def _load_or_create_historical_cache(root: Path, force: bool) -> tuple[list[dict[str, str]], dict[tuple[str, str], SeriesMeta]]:
    cache_raw, cache_series = _history_cache_paths(root)
    if cache_raw.exists() and cache_series.exists() and not force:
        rows = _filter_min_data_rows(_read_raw_archive(cache_raw))
        series = _read_series(cache_series)
        return rows, series

    rows, series = _download_historical_data(root, force_download=force)
    _write_data_paths(cache_raw, cache_series, rows, series)
    return rows, series


def refresh_weekly_data(root: Path, force_history: bool = False) -> tuple[int, int, str]:
    if not force_history and (root / "raw.csv.tar.xz").exists():
        try:
            return refresh_wpsr_latest_data(root)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=2) as executor:
        history_future = executor.submit(_load_or_create_historical_cache, root, force_history)
        latest_future = executor.submit(_download_latest_wpsr_rows)
        all_rows, all_series = history_future.result()
        latest_rows, latest_series, latest_release_date, latest_signature = latest_future.result()

    all_rows = _dedupe_rows([*all_rows, *latest_rows])
    all_series.update(latest_series)

    latest_weeks = {row["week_ending"] for row in latest_rows}
    latest_week = max(row["week_ending"] for row in all_rows if row["period_type"] == "weekly")
    for row in all_rows:
        if not row["release_date"]:
            row["release_date"] = latest_release_date if row["week_ending"] in latest_weeks else latest_week

    result = _write_data_files(root, all_rows, all_series)
    _write_latest_signature(root, latest_signature)
    return result
