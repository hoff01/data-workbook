from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OUT_DIR = Path("Jodi_Data")
RAW_DIR = OUT_DIR / "raw"
SECONDARY_YEAR_URL = "https://www.jodidata.org/_resources/files/downloads/oil-data/annual-csv/secondary/secondaryyear{year}.csv"
HISTORICAL_YEAR_URL = "https://www.jodidata.org/_resources/files/downloads/oil-data/annual-csv/secondary/{year}.csv"
START_YEAR = int(os.environ.get("JODI_START_YEAR", "2017"))
FUTURE_YEAR_PROBE_COUNT = int(os.environ.get("JODI_FUTURE_YEAR_PROBE_COUNT", "1"))
CURRENT_YEAR = datetime.now(timezone.utc).year
END_YEAR = int(os.environ.get("JODI_END_YEAR", str(CURRENT_YEAR + FUTURE_YEAR_PROBE_COUNT)))
CONCURRENCY = max(1, int(os.environ.get("JODI_CONCURRENCY", "4")))
USER_AGENT = "python-pulls-jodi-pipeline/0.1 (secondary oil data refresh)"

PRODUCT_TO_COMMODITY = {
    "GASOLINE": "Gasoline",
    "JETKERO": "Jet",
    "KEROSENE": "Jet",
    "GASDIES": "Diesel",
}

ENERGY_PRODUCT_NAMES = {
    "GASOLINE": "Motor and aviation gasoline",
    "JETKERO": "Kerosene type jet fuel",
    "KEROSENE": "Kerosenes",
    "GASDIES": "Gas/diesel oil",
}

FLOW_BREAKDOWN_NAMES = {
    "REFGROUT": "Refinery output",
    "RECEIPTS": "Receipts",
    "TOTIMPSB": "Imports",
    "TOTEXPSB": "Exports",
    "PTRANSF": "Products transferred",
    "IPTRANSF": "Interproduct transfers",
    "STOCKCH": "Stock change",
    "STATDIFF": "Statistical difference",
    "TOTDEMO": "Demand",
    "CLOSTLV": "Closing stocks",
}

UNIT_MEASURE_NAMES = {
    "KBD": "Thousand Barrels per day (kb/d)",
    "KBBL": "Thousand Barrels (kbbl)",
    "KL": "Thousand Kilolitres (kl)",
    "KTONS": "Thousand Metric Tons (kmt)",
    "CONVBBL": "Conversion factor barrels/ktons",
}

ASSESSMENT_CODE_NAMES = {
    "1": "Results of the assessment show reasonable levels of comparability",
    "2": "Consult metadata/Use with caution",
    "3": "Data has not been assessed",
    "4": "Data under verification",
}

COUNTRY_NAMES = {
    "AL": "Albania",
    "AM": "Armenia",
    "AO": "Angola",
    "AT": "Austria",
    "AZ": "Azerbaijan",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BY": "Belarus",
    "CH": "Switzerland",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "DZ": "Algeria",
    "EE": "Estonia",
    "EG": "Egypt",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GA": "Gabon",
    "GB": "United Kingdom",
    "GE": "Georgia",
    "GM": "Gambia",
    "GQ": "Equatorial Guinea",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IS": "Iceland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "LY": "Libya",
    "MA": "Morocco",
    "MD": "Moldova",
    "MK": "North Macedonia",
    "MT": "Malta",
    "MU": "Mauritius",
    "NE": "Niger",
    "NG": "Nigeria",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "SD": "Sudan",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "SZ": "Eswatini",
    "TN": "Tunisia",
    "TR": "Turkey",
    "UA": "Ukraine",
    "ZA": "South Africa",
}

NWE_COUNTRIES = {
    "AT",
    "BE",
    "CH",
    "CZ",
    "DE",
    "DK",
    "EE",
    "FI",
    "FR",
    "GB",
    "IE",
    "IS",
    "LT",
    "LU",
    "LV",
    "NL",
    "NO",
    "PL",
    "SE",
    "SK",
}
MED_COUNTRIES = {
    "AL",
    "BG",
    "CY",
    "ES",
    "GR",
    "HR",
    "IT",
    "MK",
    "MT",
    "PT",
    "RO",
    "RS",
    "SI",
    "TR",
}
OTHER_EUROPE_COUNTRIES = {"AM", "AZ", "BY", "GE", "HU", "MD", "RU", "UA"}
NORTH_AFRICA_COUNTRIES = {"DZ", "EG", "LY", "MA", "TN"}
EAST_AFRICA_COUNTRIES = {"MU", "SD"}
WEST_AFRICA_COUNTRIES = {"AO", "GA", "GM", "GQ", "NE", "NG"}
OTHER_AFRICA_COUNTRIES = {"SZ", "ZA"}

EUROPE_COUNTRIES = NWE_COUNTRIES | MED_COUNTRIES | OTHER_EUROPE_COUNTRIES
AFRICA_COUNTRIES = NORTH_AFRICA_COUNTRIES | EAST_AFRICA_COUNTRIES | WEST_AFRICA_COUNTRIES | OTHER_AFRICA_COUNTRIES

OUTPUT_FIELDS = [
    "period_month",
    "source_year",
    "region",
    "region_detail",
    "country_code",
    "country_name",
    "commodity",
    "source_energy_product",
    "source_energy_product_code",
    "flow_breakdown",
    "flow_breakdown_code",
    "unit_measure",
    "unit_measure_code",
    "value",
    "value_status",
    "assessment",
    "assessment_code",
]


@dataclass(frozen=True)
class DownloadResult:
    year: int
    url: str
    attempted_urls: list[str]
    path: Path | None
    status: str
    bytes: int = 0
    sha256: str = ""
    error: str = ""


def clean_output_dir(path: Path) -> None:
    path.mkdir(exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    RAW_DIR.mkdir(exist_ok=True)


def url_candidates_for_year(year: int) -> list[str]:
    secondary_year_url = SECONDARY_YEAR_URL.format(year=year)
    historical_year_url = HISTORICAL_YEAR_URL.format(year=year)
    if year >= CURRENT_YEAR:
        return [secondary_year_url, historical_year_url]
    return [historical_year_url, secondary_year_url]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_year(year: int) -> DownloadResult:
    attempted_urls = url_candidates_for_year(year)
    errors: list[str] = []
    for url in attempted_urls:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = response.read()
            break
        except urllib.error.HTTPError as exc:
            errors.append(f"{url}: HTTP {exc.code}: {exc.reason}")
            continue
        except urllib.error.URLError as exc:
            errors.append(f"{url}: {exc.reason}")
            continue
    else:
        status = "missing_future" if year > CURRENT_YEAR and all("HTTP 404" in error for error in errors) else "error"
        return DownloadResult(
            year=year,
            url=attempted_urls[0],
            attempted_urls=attempted_urls,
            path=None,
            status=status,
            error="; ".join(errors),
        )

    path = RAW_DIR / f"secondaryyear{year}.csv"
    path.write_bytes(body)
    return DownloadResult(
        year=year,
        url=url,
        attempted_urls=attempted_urls,
        path=path,
        status="downloaded",
        bytes=len(body),
        sha256=sha256(body),
    )


def parse_number(value: str) -> tuple[str, str]:
    text = value.strip()
    if text in {"", "-", "x", "X", "NA", "N/A"}:
        return "", text
    try:
        return str(float(text)), ""
    except ValueError:
        return "", text


def region_for_country(country_code: str) -> tuple[str, str] | None:
    if country_code in NWE_COUNTRIES:
        return "Europe", "NWE"
    if country_code in MED_COUNTRIES:
        return "Europe", "MED"
    if country_code in OTHER_EUROPE_COUNTRIES:
        return "Europe", "Other Europe"
    if country_code in NORTH_AFRICA_COUNTRIES:
        return "Africa", "North Africa"
    if country_code in EAST_AFRICA_COUNTRIES:
        return "Africa", "East Africa"
    if country_code in WEST_AFRICA_COUNTRIES:
        return "Africa", "West Africa"
    if country_code in OTHER_AFRICA_COUNTRIES:
        return "Africa", "Other Africa"
    return None


def normalize_row(row: dict[str, str], source_year: int) -> dict[str, str] | None:
    country_code = row["REF_AREA"].strip()
    region = region_for_country(country_code)
    if region is None:
        return None

    source_product = row["ENERGY_PRODUCT"].strip()
    commodity = PRODUCT_TO_COMMODITY.get(source_product)
    if commodity is None:
        return None
    flow_code = row["FLOW_BREAKDOWN"].strip()
    unit_code = row["UNIT_MEASURE"].strip()
    assessment_code = row["ASSESSMENT_CODE"].strip()

    value, value_status = parse_number(row["OBS_VALUE"])
    return {
        "period_month": f"{row['TIME_PERIOD'].strip()}-01",
        "source_year": str(source_year),
        "region": region[0],
        "region_detail": region[1],
        "country_code": country_code,
        "country_name": COUNTRY_NAMES.get(country_code, country_code),
        "commodity": commodity,
        "source_energy_product": ENERGY_PRODUCT_NAMES.get(source_product, source_product),
        "source_energy_product_code": source_product,
        "flow_breakdown": FLOW_BREAKDOWN_NAMES.get(flow_code, flow_code),
        "flow_breakdown_code": flow_code,
        "unit_measure": UNIT_MEASURE_NAMES.get(unit_code, unit_code),
        "unit_measure_code": unit_code,
        "value": value,
        "value_status": value_status,
        "assessment": ASSESSMENT_CODE_NAMES.get(assessment_code, assessment_code),
        "assessment_code": assessment_code,
    }


def iter_rows(downloads: list[DownloadResult]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for download in downloads:
        if download.status != "downloaded" or download.path is None:
            continue
        with download.path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            missing_fields = set(["REF_AREA", "TIME_PERIOD", "ENERGY_PRODUCT", "FLOW_BREAKDOWN", "UNIT_MEASURE", "OBS_VALUE", "ASSESSMENT_CODE"]) - set(reader.fieldnames or [])
            if missing_fields:
                raise RuntimeError(f"{download.path} missing required columns: {sorted(missing_fields)}")
            for row in reader:
                normalized = normalize_row(row, download.year)
                if normalized is not None:
                    rows.append(normalized)
    rows.sort(
        key=lambda row: (
            row["region"],
            row["commodity"],
            row["country_code"],
            row["period_month"],
            row["flow_breakdown_code"],
            row["unit_measure_code"],
            row["source_energy_product_code"],
        )
    )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    tmp_path = path.with_suffix(".csv.tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def output_name(region: str, commodity: str) -> str:
    return f"{region.lower()}_{commodity.lower()}.csv"


def summarize_output(path: Path, rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "path": str(path),
        "rows": len(rows),
        "bytes": path.stat().st_size,
        "countries": sorted({row["country_code"] for row in rows}),
        "region_details": sorted({row["region_detail"] for row in rows}),
        "min_period_month": min((row["period_month"] for row in rows), default=""),
        "max_period_month": max((row["period_month"] for row in rows), default=""),
    }


def write_outputs(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for region in ["Europe", "Africa"]:
        for commodity in ["Gasoline", "Jet", "Diesel"]:
            subset = [row for row in rows if row["region"] == region and row["commodity"] == commodity]
            path = OUT_DIR / output_name(region, commodity)
            write_csv(path, subset)
            outputs[f"{region}_{commodity}"] = summarize_output(path, subset)
    return outputs


def build_context_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    products: dict[str, Any] = {}
    for product_key, commodity in [("diesel", "Diesel"), ("jet", "Jet")]:
        latest_periods: list[str] = []
        region_rows: list[dict[str, Any]] = []
        for region in ["Europe", "Africa"]:
            subset = [row for row in rows if row["region"] == region and row["commodity"] == commodity]
            by_period: dict[str, dict[str, Any]] = {}
            latest_period = ""
            for row in subset:
                if row["unit_measure_code"] != "KBD" or not row["value"] or row["value_status"] == "-":
                    continue
                period = row["period_month"]
                latest_period = max(latest_period, period)
                bucket = by_period.setdefault(
                    period,
                    {
                        "demandKbd": 0.0,
                        "importsKbd": 0.0,
                        "exportsKbd": 0.0,
                        "countries": set(),
                        "assessed": 0,
                        "latestRows": 0,
                    },
                )
                value = float(row["value"])
                flow = row["flow_breakdown_code"]
                if flow == "TOTDEMO":
                    bucket["demandKbd"] += value
                elif flow == "TOTIMPSB":
                    bucket["importsKbd"] += value
                elif flow == "TOTEXPSB":
                    bucket["exportsKbd"] += value
                if row["country_code"]:
                    bucket["countries"].add(row["country_code"])
                if row["assessment_code"] == "1":
                    bucket["assessed"] += 1
                bucket["latestRows"] += 1

            if latest_period:
                latest_periods.append(latest_period)
            latest = by_period.get(latest_period)
            if not latest:
                continue
            latest_rows = latest["latestRows"]
            region_rows.append(
                {
                    "region": region,
                    "demandKbd": round(latest["demandKbd"], 2),
                    "importsKbd": round(latest["importsKbd"], 2),
                    "exportsKbd": round(latest["exportsKbd"], 2),
                    "countries": len(latest["countries"]),
                    "rows": len(subset),
                    "assessedShare": round(latest["assessed"] / latest_rows * 100, 1) if latest_rows else 0,
                }
            )
        products[product_key] = {
            "latestPeriod": sorted(latest_periods)[-1] if latest_periods else "",
            "regions": region_rows,
            "note": (
                f"JODI {product_key} regional context aggregates KBD demand, imports, "
                "and exports for Europe and Africa when local JODI files are present."
            ),
        }
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "products": products,
    }


def write_context_summary(rows: list[dict[str, str]]) -> None:
    tmp_path = OUT_DIR / "context_summary.json.tmp"
    tmp_path.write_text(json.dumps(build_context_summary(rows), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(OUT_DIR / "context_summary.json")


def write_manifest(downloads: list[DownloadResult], outputs: dict[str, dict[str, Any]]) -> None:
    payload = {
        "pipeline_name": "jodi_secondary",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_year": START_YEAR,
        "end_year_attempted": END_YEAR,
        "future_year_probe_count": FUTURE_YEAR_PROBE_COUNT,
        "url_patterns": {
            "current_and_future_first": SECONDARY_YEAR_URL,
            "historical_fallback": HISTORICAL_YEAR_URL,
        },
        "source_page": "https://www.jodidata.org/oil/database/data-downloads.aspx",
        "product_mapping": PRODUCT_TO_COMMODITY,
        "item_name_source": "https://www.jodidata.org/_resources/files/downloads/oil-data/jodi-oil-wdb-item-names-ver2017.pdf",
        "item_names": {
            "ENERGY_PRODUCT": ENERGY_PRODUCT_NAMES,
            "FLOW_BREAKDOWN": FLOW_BREAKDOWN_NAMES,
            "UNIT_MEASURE": UNIT_MEASURE_NAMES,
            "ASSESSMENT_CODE": ASSESSMENT_CODE_NAMES,
        },
        "region_mapping": {
            "Europe": {
                "NWE": sorted(NWE_COUNTRIES),
                "MED": sorted(MED_COUNTRIES),
                "Other Europe": sorted(OTHER_EUROPE_COUNTRIES),
            },
            "Africa": {
                "North Africa": sorted(NORTH_AFRICA_COUNTRIES),
                "East Africa": sorted(EAST_AFRICA_COUNTRIES),
                "West Africa": sorted(WEST_AFRICA_COUNTRIES),
                "Other Africa": sorted(OTHER_AFRICA_COUNTRIES),
            },
        },
        "downloads": [
            {
                "year": item.year,
                "url": item.url,
                "attempted_urls": item.attempted_urls,
                "path": str(item.path) if item.path else "",
                "status": item.status,
                "bytes": item.bytes,
                "sha256": item.sha256,
                "error": item.error,
            }
            for item in downloads
        ],
        "outputs": outputs,
    }
    tmp_path = OUT_DIR / "manifest.json.tmp"
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(OUT_DIR / "manifest.json")


def main() -> int:
    if END_YEAR < START_YEAR:
        raise RuntimeError(f"JODI_END_YEAR={END_YEAR} is before JODI_START_YEAR={START_YEAR}")

    clean_output_dir(OUT_DIR)
    years = list(range(START_YEAR, END_YEAR + 1))
    fetched_by_year: dict[int, DownloadResult] = {}
    with ThreadPoolExecutor(max_workers=min(CONCURRENCY, len(years))) as executor:
        futures = {executor.submit(fetch_year, year): year for year in years}
        for future in as_completed(futures):
            item = future.result()
            fetched_by_year[item.year] = item

    downloads = [fetched_by_year[year] for year in years]
    required_errors = [item for item in downloads if item.status == "error" and item.year <= CURRENT_YEAR]
    if required_errors:
        detail = "; ".join(f"{item.year}: {item.error}" for item in required_errors)
        raise RuntimeError(f"JODI required-year downloads failed: {detail}")

    rows = iter_rows(downloads)
    outputs = write_outputs(rows)
    write_context_summary(rows)
    write_manifest(downloads, outputs)

    downloaded_count = sum(1 for item in downloads if item.status == "downloaded")
    future_missing = [item.year for item in downloads if item.status == "missing_future"]
    print(
        f"jodi downloaded_years={downloaded_count} rows={len(rows)} "
        f"outputs={len(outputs)} missing_future_years={future_missing}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
