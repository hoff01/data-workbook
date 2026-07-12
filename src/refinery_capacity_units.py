from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import ZipFile

from env_loader import load_env_files


load_env_files()


OUT_DIR = Path("eia_capacity")
RAW_DIR = OUT_DIR / "raw"
RAW_XLSX = RAW_DIR / "refcap25.xlsx"
OUTPUT = OUT_DIR / "refinery_unit_capacities_2025.csv"
MANIFEST = OUT_DIR / "refinery_unit_capacities_manifest.json"

DEFAULT_URL = "https://www.eia.gov/petroleum/refinerycapacity/refcap25.xlsx"
REFCAP_URL = os.environ.get("EIA_REFCAP_URL", DEFAULT_URL)
SOURCE_YEAR = int(os.environ.get("EIA_REFCAP_YEAR", "2025"))
USER_AGENT = "python-pulls-eia-refinery-units/0.1"

CALENDAR_DOWNSTREAM = "Downstream Charge Capacity, Current Year (barrels per calendar day)"
ATMOS_SUPPLY = "Atmospheric Crude Distillation Capacity (barrels per calendar day)"

UNIT_DEFS = [
    {
        "unit_key": "atmos_distillation",
        "unit_label": "Atmos Distillation",
        "products": ["OPERATING CAPACITY"],
        "supplies": [ATMOS_SUPPLY],
    },
    {
        "unit_key": "distillate_hydrocracking",
        "unit_label": "Distillate Hydrocracking",
        "products": ["CAT HYDROCRACKING, DISTILLATE"],
        "supplies": [CALENDAR_DOWNSTREAM],
    },
    {
        "unit_key": "gasoil_resid_hydrocracking",
        "unit_label": "Gasoil & Resid Hydrocracking",
        "products": ["CAT HYDROCRACKING, RESIDUAL", "CAT HYDROCRACKING, GAS OIL"],
        "supplies": [CALENDAR_DOWNSTREAM],
    },
    {
        "unit_key": "fcc",
        "unit_label": "FCC",
        "products": ["CAT CRACKING: FRESH FEED"],
        "supplies": [CALENDAR_DOWNSTREAM],
    },
    {
        "unit_key": "coking",
        "unit_label": "Coking",
        "products": ["THERM CRACKING, DELAYED COKING", "THERM CRACKING, FLUID COKING"],
        "supplies": [CALENDAR_DOWNSTREAM],
    },
]

OUTPUT_COLUMNS = [
    "source_year",
    "refinery_id",
    "refinery_name",
    "company_name",
    "site",
    "state",
    "rdist_label",
    "padd",
    "unit_key",
    "unit_label",
    "source_products",
    "source_supplies",
    "quantity_bpcd",
    "capacity_kbd",
    "source_file",
    "generated_at",
]


def fetch_source() -> bytes:
    request = Request(REFCAP_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=180) as response:
        return response.read()


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def title_like(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    keep_upper = {"LP", "LLC", "INC", "CO", "USA", "US", "LTD", "PLC", "CORP", "NA", "NORTH", "AMERICA"}
    parts = []
    for token in text.split(" "):
        stripped = re.sub(r"[^A-Z0-9]", "", token.upper())
        if stripped in keep_upper or len(stripped) <= 2 and stripped.isalpha():
            parts.append(token.upper())
        else:
            parts.append(token[:1].upper() + token[1:].lower())
    return " ".join(parts)


def slug(value: str) -> str:
    text = value.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def parse_quantity(value: object) -> float:
    text = str(value or "").replace(",", "").strip()
    if not text or text in {".", "--"}:
        return 0.0
    try:
        parsed = float(text)
    except ValueError:
        return 0.0
    return parsed if parsed == parsed else 0.0


def ensure_source_file() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        RAW_XLSX.write_bytes(fetch_source())
    except Exception:
        if not RAW_XLSX.exists():
            raise


def load_rows() -> list[dict[str, Any]]:
    matrix = read_xlsx_first_sheet(RAW_XLSX)
    if not matrix:
        raise RuntimeError(f"{RAW_XLSX} is empty")
    header = [clean_text(cell) for cell in matrix[0]]
    expected = ["COMPANY_NAME", "RDIST_LABEL", "STATE_NAME", "SITE", "PADD", "PRODUCT", "SUPPLY", "QUANTITY"]
    missing = [name for name in expected if name not in header]
    if missing:
        raise RuntimeError(f"{RAW_XLSX} missing expected columns: {', '.join(missing)}")
    rows = []
    for raw in matrix[1:]:
        row = {header[idx]: raw[idx] if idx < len(raw) else "" for idx in range(len(header))}
        rows.append(row)
    return rows


def xml_text(element: ElementTree.Element) -> str:
    return "".join(element.itertext())


def column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return max(0, index - 1)


def read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    strings = []
    for item in root:
        strings.append(xml_text(item))
    return strings


def worksheet_path(archive: ZipFile) -> str:
    names = archive.namelist()
    if "xl/worksheets/sheet1.xml" in names:
        return "xl/worksheets/sheet1.xml"
    matches = sorted(name for name in names if name.startswith("xl/worksheets/") and name.endswith(".xml"))
    if not matches:
        raise RuntimeError(f"{RAW_XLSX} does not contain a worksheet XML file")
    return matches[0]


def cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> object:
    cell_type = cell.attrib.get("t", "")
    value_node = next((child for child in cell if child.tag.endswith("}v") or child.tag == "v"), None)
    if value_node is None:
        inline = next((child for child in cell if child.tag.endswith("}is") or child.tag == "is"), None)
        return xml_text(inline) if inline is not None else ""
    raw = clean_text(value_node.text)
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "str":
        return raw
    if re.fullmatch(r"-?\d+(\.\d+)?", raw):
        number = float(raw)
        return int(number) if number.is_integer() else number
    return raw


def read_xlsx_first_sheet(path: Path) -> list[list[object]]:
    with ZipFile(path) as archive:
        shared_strings = read_shared_strings(archive)
        root = ElementTree.fromstring(archive.read(worksheet_path(archive)))
    rows: list[list[object]] = []
    for row in root.iter():
        if not row.tag.endswith("}row") and row.tag != "row":
            continue
        cells: list[object] = []
        for cell in row:
            if not cell.tag.endswith("}c") and cell.tag != "c":
                continue
            idx = column_index(cell.attrib.get("r", ""))
            while len(cells) <= idx:
                cells.append("")
            cells[idx] = cell_value(cell, shared_strings)
        if any(clean_text(value) for value in cells):
            rows.append(cells)
    return rows


def refinery_key(row: dict[str, Any]) -> str:
    company = clean_text(row.get("COMPANY_NAME"))
    site = clean_text(row.get("SITE"))
    state = clean_text(row.get("STATE_NAME"))
    padd = clean_text(row.get("PADD"))
    return f"{company}|{site}|{state}|{padd}"


def refinery_name(row: dict[str, Any]) -> str:
    return f"{title_like(row.get('COMPANY_NAME'))} - {title_like(row.get('SITE'))}".strip(" -")


def build_output_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_refinery: dict[str, list[dict[str, Any]]] = {}
    first_row: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = refinery_key(row)
        by_refinery.setdefault(key, []).append(row)
        first_row.setdefault(key, row)

    generated_at = datetime.now(timezone.utc).isoformat()
    output_rows: list[dict[str, Any]] = []
    for key, refinery_rows in by_refinery.items():
        first = first_row[key]
        company = title_like(first.get("COMPANY_NAME"))
        site = title_like(first.get("SITE"))
        state = title_like(first.get("STATE_NAME"))
        rdist = title_like(first.get("RDIST_LABEL"))
        padd = clean_text(first.get("PADD"))
        refinery_id = slug(f"{company}_{site}_{state}_padd_{padd}")
        for unit in UNIT_DEFS:
            matched = [
                row
                for row in refinery_rows
                if clean_text(row.get("PRODUCT")) in unit["products"]
                and clean_text(row.get("SUPPLY")) in unit["supplies"]
            ]
            quantity = sum(parse_quantity(row.get("QUANTITY")) for row in matched)
            if quantity <= 0:
                continue
            output_rows.append(
                {
                    "source_year": SOURCE_YEAR,
                    "refinery_id": refinery_id,
                    "refinery_name": refinery_name(first),
                    "company_name": company,
                    "site": site,
                    "state": state,
                    "rdist_label": rdist,
                    "padd": f"padd{padd}" if padd else "",
                    "unit_key": unit["unit_key"],
                    "unit_label": unit["unit_label"],
                    "source_products": "; ".join(unit["products"]),
                    "source_supplies": "; ".join(unit["supplies"]),
                    "quantity_bpcd": f"{quantity:.0f}",
                    "capacity_kbd": f"{quantity / 1000.0:.3f}",
                    "source_file": REFCAP_URL,
                    "generated_at": generated_at,
                }
            )
    output_rows.sort(key=lambda row: (row["padd"], row["refinery_name"], row["unit_label"]))
    return output_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def write_manifest(rows: list[dict[str, Any]]) -> None:
    refineries = {row["refinery_id"] for row in rows}
    payload = {
        "source_url": REFCAP_URL,
        "source_year": SOURCE_YEAR,
        "source_path": str(RAW_XLSX),
        "source_sha256": checksum(RAW_XLSX),
        "output_path": str(OUTPUT),
        "rows": len(rows),
        "refineries": len(refineries),
        "units": [unit["unit_key"] for unit in UNIT_DEFS],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = MANIFEST.with_suffix(MANIFEST.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(MANIFEST)


def main() -> None:
    ensure_source_file()
    rows = build_output_rows(load_rows())
    if not rows:
        raise RuntimeError("No refinery unit capacities were extracted from EIA refinery capacity workbook")
    write_csv(OUTPUT, rows)
    write_manifest(rows)
    print(f"wrote {OUTPUT} rows={len(rows)} refineries={len({row['refinery_id'] for row in rows})}")


if __name__ == "__main__":
    main()
