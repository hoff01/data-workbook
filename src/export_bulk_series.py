from __future__ import annotations

import csv
from pathlib import Path

from export_raw_headers import (
    MONTHLY_BULK_SOURCE,
    MONTHLY_DISTILLATE_EXCLUDE_PHRASES,
    MONTHLY_IMPORT_PADD_CATEGORIES,
    is_monthly_annual_capacity_series,
    is_monthly_common_series,
    is_monthly_product_series,
    iter_monthly_bulk_items,
    monthly_country_category,
    monthly_export_padd_categories,
    monthly_flow_country,
    monthly_region_label,
)


OUT_DIR = Path("eia_monthly")
OUTPUT = OUT_DIR / "bulk_series.csv"
PRODUCTS = ["Distillate Fuel Oil", "Kerosene-Type Jet Fuel"]
COLUMNS = [
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


def text(value: object) -> str:
    return "" if value is None else str(value)


def item_region(item: dict[str, object]) -> str:
    return monthly_region_label(text(item.get("name"))) or text(item.get("geography")) or "Other"


def is_monthly_flow_bucket_source(item: dict[str, object], product: str) -> bool:
    if item.get("f") != "M" or item.get("units") != "Thousand Barrels":
        return False
    name = text(item.get("name"))
    if product not in name or any(phrase in name for phrase in MONTHLY_DISTILLATE_EXCLUDE_PHRASES):
        return False
    for flow, padd_categories in [
        ("Exports", monthly_export_padd_categories(product)),
        ("Imports", MONTHLY_IMPORT_PADD_CATEGORIES.get(product, {})),
    ]:
        for padd, categories in padd_categories.items():
            if name == f"{padd} {flow} of {product}, Monthly":
                return True
            country = monthly_flow_country(name, product, padd, flow)
            if country is not None and monthly_country_category(categories, country) in categories:
                return True
    return False


def is_needed_monthly_item(item: dict[str, object]) -> bool:
    name = text(item.get("name"))
    units = text(item.get("units"))
    if is_monthly_common_series(name) or is_monthly_annual_capacity_series(name, units):
        return True
    if any(is_monthly_product_series(name, product) for product in PRODUCTS):
        return True
    return any(is_monthly_flow_bucket_source(item, product) for product in PRODUCTS)


def sort_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (row["region"], row["frequency"], row["name"], row["series_id"])


def main() -> int:
    if not MONTHLY_BULK_SOURCE.exists():
        raise RuntimeError(f"Missing required EIA monthly bulk file {MONTHLY_BULK_SOURCE}")
    OUT_DIR.mkdir(exist_ok=True)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in iter_monthly_bulk_items():
        series_id = text(item.get("series_id")).strip()
        if not series_id or series_id in seen or not is_needed_monthly_item(item):
            continue
        seen.add(series_id)
        rows.append(
            {
                "bulk_source": "PET",
                "series_id": series_id,
                "name": text(item.get("name")).strip(),
                "region": item_region(item),
                "frequency": text(item.get("f")).strip(),
                "units": text(item.get("units")),
                "start": text(item.get("start")),
                "end": text(item.get("end")),
                "last_updated": text(item.get("last_updated")),
                "v2_seriesid_route": f"/v2/seriesid/{series_id}",
            }
        )
    if not rows:
        raise RuntimeError("No needed monthly PET bulk series matched the local dashboard configuration")
    rows.sort(key=sort_key)
    tmp_path = OUTPUT.with_suffix(".csv.tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(OUTPUT)
    print(f"wrote {OUTPUT} rows={len(rows)} source=PET filtered=needed-monthly-dashboard-series bytes={OUTPUT.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
