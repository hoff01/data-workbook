from __future__ import annotations

import csv
import json
from pathlib import Path
from zipfile import ZipFile


OUT_DIR = Path("eia_monthly")
OUTPUT = OUT_DIR / "bulk_series.csv"
BULK_SOURCES = [
    ("PET", Path("PET.zip")),
    ("TOTAL", Path("TOTAL.zip")),
    ("SEDS", Path("SEDS.zip")),
]
INCLUDED_FREQUENCIES = {"A", "M"}
REGION_ORDER = [
    "East Coast",
    "U.S.",
    "Gulf Coast",
    "Midwest",
    "Rocky Mountain",
    "West Coast",
    "New England",
    "Central Atlantic",
    "Lower Atlantic",
]
STATE_NAMES = [
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
]
STATE_ABBREVIATIONS = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
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


def infer_region(name: str, geography: str) -> str:
    haystack = f"{name} {geography}"
    regional_markers = [
        ("Central Atlantic", ["Central Atlantic", "PADD 1B"]),
        ("Lower Atlantic", ["Lower Atlantic", "PADD 1C"]),
        ("New England", ["New England", "PADD 1A"]),
        ("East Coast", ["East Coast", "PADD 1"]),
        ("Gulf Coast", ["Gulf Coast", "PADD 3"]),
        ("Midwest", ["Midwest", "PADD 2"]),
        ("Rocky Mountain", ["Rocky Mountain", "PADD 4"]),
        ("West Coast", ["West Coast", "PADD 5"]),
    ]
    for region, markers in regional_markers:
        if any(marker in haystack for marker in markers):
            return region
    if "New York Harbor" in haystack:
        return "New York"
    for code, state in STATE_ABBREVIATIONS.items():
        if f", {code} " in haystack or haystack.endswith(f", {code}") or f" {code}," in haystack:
            return state
    for state in STATE_NAMES:
        if f", {state}" in haystack or haystack.endswith(f" {state}") or f" {state}," in haystack:
            return state
    if "U.S." in haystack or "United States" in haystack:
        return "U.S."
    return "Other"


def frequency_rank(frequency: str) -> int:
    return 0 if frequency == "M" else 1


def sort_key(row: dict[str, str]) -> tuple[int, int | str, int, str, str, str]:
    region = row["region"]
    end_desc = "".join(chr(255 - ord(char)) for char in row["end"])
    if region in REGION_ORDER:
        return (0, REGION_ORDER.index(region), frequency_rank(row["frequency"]), end_desc, row["name"], row["series_id"])
    if region in STATE_NAMES:
        return (1, region, frequency_rank(row["frequency"]), end_desc, row["name"], row["series_id"])
    return (2, region, frequency_rank(row["frequency"]), end_desc, row["name"], row["series_id"])


def iter_bulk_records(source_name: str, zip_path: Path):
    with ZipFile(zip_path) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise RuntimeError(f"{zip_path} must contain exactly one txt file")
        with archive.open(names[0]) as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"{zip_path}:{line_number} is not valid JSON") from exc
                series_id = text(item.get("series_id")).strip()
                name = text(item.get("name")).strip()
                frequency = text(item.get("f")).strip()
                if not series_id or not name or frequency not in INCLUDED_FREQUENCIES:
                    continue
                route = f"/v2/seriesid/{series_id}"
                region = infer_region(name, text(item.get("geography")))
                yield {
                    "bulk_source": source_name,
                    "series_id": series_id,
                    "name": name,
                    "region": region,
                    "frequency": frequency,
                    "units": text(item.get("units")),
                    "start": text(item.get("start")),
                    "end": text(item.get("end")),
                    "last_updated": text(item.get("last_updated")),
                    "v2_seriesid_route": route,
                }


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    tmp_path = OUTPUT.with_suffix(".csv.tmp")
    rows = []
    for source_name, zip_path in BULK_SOURCES:
        if not zip_path.exists():
            raise RuntimeError(f"Missing required EIA bulk file {zip_path}")
        rows.extend(iter_bulk_records(source_name, zip_path))
    rows.sort(key=sort_key)
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(OUTPUT)
    print(f"wrote {OUTPUT} rows={len(rows)} bytes={OUTPUT.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
