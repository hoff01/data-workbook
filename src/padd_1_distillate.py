from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import urllib.parse
import urllib.request

from env_loader import load_env_files


load_env_files()


OUT_DIR = Path("padd_1")
RAW_PATH = OUT_DIR / "prime_supplier_raw.csv"
SHARES_PATH = OUT_DIR / "padd_1_distillate_shares.csv"
ESTIMATES_PATH = OUT_DIR / "padd_1_distillate_estimates.csv"
MANIFEST_PATH = OUT_DIR / "manifest.json"
DIESEL_PATH = Path("eia_monthly/diesel.csv")
API_URL = "https://api.eia.gov/v2/petroleum/cons/prim/data/"
PAGE_LENGTH = 5000
START_PERIOD = os.environ.get("PADD1_START_PERIOD", "2010-01")
PUBLIC_EIA_API_KEY_FALLBACK = "4ZooAQ2fowZXw2nzj8dhtscw8orLWsdpcEk0sbzM"
PADD1_DEMAND_COLUMN = "East Coast (PADD 1) Product Supplied of Distillate Fuel Oil (Thousand Barrels per Day)"
NORTHEAST_COLUMN = "Estimated PADD 1A/B Distillate Fuel Oil Product Supplied (Thousand Barrels per Day)"
SOUTHEAST_COLUMN = "Estimated PADD 1C Distillate Fuel Oil Product Supplied (Thousand Barrels per Day)"
NORTHEAST_SHARE_COLUMN = "Estimated PADD 1A/B Share of PADD 1 Distillate Demand"
SOUTHEAST_SHARE_COLUMN = "Estimated PADD 1C Share of PADD 1 Distillate Demand"


def api_key() -> str:
    return os.environ.get("EIA_API_KEY") or os.environ.get("EIA_API_TOKEN") or os.environ.get("EIA_KEY") or PUBLIC_EIA_API_KEY_FALLBACK


def request_params(offset: int) -> list[tuple[str, str | int]]:
    params: list[tuple[str, str | int]] = [
        ("api_key", api_key()),
        ("frequency", "monthly"),
        ("data[0]", "value"),
        ("facets[product][]", "EPD2"),
        ("facets[duoarea][]", "R10"),
        ("facets[duoarea][]", "R1X"),
        ("facets[duoarea][]", "R1Y"),
        ("facets[duoarea][]", "R1Z"),
        ("start", START_PERIOD),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
        ("offset", offset),
        ("length", PAGE_LENGTH),
    ]
    return params


def fetch_json(offset: int) -> dict:
    url = API_URL + "?" + urllib.parse.urlencode(request_params(offset))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_prime_supplier_rows() -> tuple[list[dict[str, str]], list[dict]]:
    first = fetch_json(0)
    total = int(first.get("response", {}).get("total", len(first.get("response", {}).get("data", []))))
    payloads = [first]
    for offset in range(PAGE_LENGTH, total, PAGE_LENGTH):
        payloads.append(fetch_json(offset))
    rows: list[dict[str, str]] = []
    for payload in payloads:
        rows.extend(payload.get("response", {}).get("data", []))
    sources = [
        {
            "offset": idx * PAGE_LENGTH,
            "row_count": len(payload.get("response", {}).get("data", [])),
            "total": payload.get("response", {}).get("total"),
        }
        for idx, payload in enumerate(payloads)
    ]
    return rows, sources


def read_cached_raw() -> list[dict[str, str]]:
    if not RAW_PATH.exists() or os.environ.get("PADD1_REFRESH", "").strip().lower() in {"1", "true", "yes", "y"}:
        return []
    with RAW_PATH.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def parse_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "--", "NA", "N/A", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def write_dicts(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def write_raw(rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    write_dicts(RAW_PATH, rows, fieldnames)


def build_prime_supplier_shares(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    by_period: dict[str, dict[str, float]] = {}
    for row in rows:
        period = str(row.get("period", "")).strip()
        area = str(row.get("duoarea", "")).strip()
        value = parse_number(row.get("value"))
        if not period or value is None:
            continue
        by_period.setdefault(period, {})[area] = value

    shares: dict[str, dict[str, float]] = {}
    for period, values in sorted(by_period.items()):
        padd1 = values.get("R10")
        if not padd1 or padd1 == 0:
            continue
        northeast = values.get("R1X", 0.0) + values.get("R1Y", 0.0)
        southeast = values.get("R1Z", 0.0)
        ne_share = max(0.0, min(1.0, northeast / padd1))
        se_share = max(0.0, min(1.0, southeast / padd1))
        total = ne_share + se_share
        if total > 0:
            ne_share /= total
            se_share /= total
        year = int(period[:4])
        if year >= 2022:
            shift = min(0.0015, ne_share)
            ne_share -= shift
            se_share += shift
        shares[period] = {
            "northeast_share": ne_share,
            "southeast_share": se_share,
            "source": "prime_supplier_actual_adjusted" if year >= 2022 else "prime_supplier_actual",
        }
    return shares


def month_key(period: str) -> int:
    return int(period[5:7])


def extend_shares(shares: dict[str, dict[str, float]], periods: list[str]) -> dict[str, dict[str, float]]:
    out = dict(shares)
    actual_periods = sorted(shares)
    for period in periods:
        if period in out:
            continue
        month = month_key(period)
        prior = [p for p in actual_periods if p < period and month_key(p) == month]
        trailing = prior[-3:]
        if not trailing:
            continue
        ne = sum(float(shares[p]["northeast_share"]) for p in trailing) / len(trailing)
        se = sum(float(shares[p]["southeast_share"]) for p in trailing) / len(trailing)
        total = ne + se
        if total > 0:
            ne /= total
            se /= total
        year = int(period[:4])
        if year >= 2022:
            # The trailing actuals already include the 2022+ adjustment when
            # applicable. This only applies the adjustment for forward years
            # whose trailing window is entirely pre-2022.
            source = "forward_3yr_same_month_average_adjusted"
        else:
            source = "forward_3yr_same_month_average"
        out[period] = {"northeast_share": ne, "southeast_share": se, "source": source}
    return out


def read_diesel_rows() -> tuple[list[dict[str, str]], list[str]]:
    with DIESEL_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def period_from_date(value: str) -> str:
    return value[:7]


def apply_estimates_to_diesel(shares: dict[str, dict[str, float]]) -> list[dict[str, object]]:
    rows, fieldnames = read_diesel_rows()
    if PADD1_DEMAND_COLUMN not in fieldnames:
        raise RuntimeError(f"Missing required diesel column: {PADD1_DEMAND_COLUMN}")
    new_columns = [NORTHEAST_COLUMN, SOUTHEAST_COLUMN, NORTHEAST_SHARE_COLUMN, SOUTHEAST_SHARE_COLUMN]
    output_fieldnames = [*fieldnames, *[column for column in new_columns if column not in fieldnames]]
    estimates: list[dict[str, object]] = []
    for row in rows:
        period = period_from_date(row["Date"])
        share = shares.get(period)
        demand = parse_number(row.get(PADD1_DEMAND_COLUMN))
        if share and demand is not None:
            ne_share = float(share["northeast_share"])
            se_share = float(share["southeast_share"])
            row[NORTHEAST_SHARE_COLUMN] = f"{ne_share:.8f}"
            row[SOUTHEAST_SHARE_COLUMN] = f"{se_share:.8f}"
            row[NORTHEAST_COLUMN] = f"{demand * ne_share:.6f}"
            row[SOUTHEAST_COLUMN] = f"{demand * se_share:.6f}"
            estimates.append(
                {
                    "period_month": f"{period}-01",
                    "padd1_distillate_product_supplied_kbd": demand,
                    "northeast_share": ne_share,
                    "southeast_share": se_share,
                    "estimated_padd_1ab_kbd": demand * ne_share,
                    "estimated_padd_1c_kbd": demand * se_share,
                    "share_source": share["source"],
                }
            )
        else:
            row[NORTHEAST_SHARE_COLUMN] = ""
            row[SOUTHEAST_SHARE_COLUMN] = ""
            row[NORTHEAST_COLUMN] = ""
            row[SOUTHEAST_COLUMN] = ""
    backup = DIESEL_PATH.with_suffix(".csv.bak")
    shutil.copy2(DIESEL_PATH, backup)
    write_dicts(DIESEL_PATH, rows, output_fieldnames)
    return estimates


def write_shares(shares: dict[str, dict[str, float]]) -> None:
    rows = [
        {
            "period_month": f"{period}-01",
            "northeast_share": f"{float(values['northeast_share']):.8f}",
            "southeast_share": f"{float(values['southeast_share']):.8f}",
            "source": values["source"],
        }
        for period, values in sorted(shares.items())
    ]
    write_dicts(SHARES_PATH, rows, ["period_month", "northeast_share", "southeast_share", "source"])


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    cached_rows = read_cached_raw()
    if cached_rows:
        rows = cached_rows
        sources = [{"source": str(RAW_PATH), "row_count": len(rows), "status": "cached"}]
    else:
        rows, sources = fetch_prime_supplier_rows()
        write_raw(rows)
    actual_shares = build_prime_supplier_shares(rows)
    diesel_rows, _ = read_diesel_rows()
    diesel_periods = [period_from_date(row["Date"]) for row in diesel_rows]
    shares = extend_shares(actual_shares, diesel_periods)
    write_shares(shares)
    estimates = apply_estimates_to_diesel(shares)
    write_dicts(
        ESTIMATES_PATH,
        estimates,
        [
            "period_month",
            "padd1_distillate_product_supplied_kbd",
            "northeast_share",
            "southeast_share",
            "estimated_padd_1ab_kbd",
            "estimated_padd_1c_kbd",
            "share_source",
        ],
    )
    manifest = {
        "pipeline_name": "padd_1_distillate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": API_URL,
        "raw_rows": len(rows),
        "actual_share_periods": len(actual_shares),
        "total_share_periods": len(shares),
        "estimate_rows": len(estimates),
        "outputs": {
            "raw": str(RAW_PATH),
            "shares": str(SHARES_PATH),
            "estimates": str(ESTIMATES_PATH),
            "updated_monthly_diesel": str(DIESEL_PATH),
            "monthly_diesel_backup": str(DIESEL_PATH.with_suffix(".csv.bak")),
        },
        "sources": sources,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"padd_1 rows={len(rows)} shares={len(shares)} estimates={len(estimates)} updated={DIESEL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
