from __future__ import annotations

import csv
import shutil
from pathlib import Path


TIME_SERIES_FILES = [
    Path("eia_monthly/diesel.csv"),
    Path("eia_monthly/jet.csv"),
    Path("eia_monthly/gasoline.csv"),
    Path("eia_weekly/diesel.csv"),
    Path("eia_weekly/jet.csv"),
    Path("eia_weekly/gasoline.csv"),
]

GASOLINE_OUTPUTS = {
    Path("eia_monthly/gasoline.csv"),
    Path("eia_weekly/gasoline.csv"),
}

LEGACY_OUTPUTS = {
    Path("eia_monthly/diesel_monthly.csv"): Path("eia_monthly/diesel.csv"),
    Path("eia_monthly/jet_monthly.csv"): Path("eia_monthly/jet.csv"),
    Path("eia_weekly/EIA_Weekly_Diesel.csv"): Path("eia_weekly/diesel.csv"),
    Path("eia_weekly/EIA_Weekly_Jet.csv"): Path("eia_weekly/jet.csv"),
    Path("eia_weekly/EIA_Weekly_Gasoline.csv"): Path("eia_weekly/gasoline.csv"),
}

PRUNE_PATHS = [
    Path("eia_monthly/raw"),
    Path("eia_monthly/raw.csv"),
    Path("eia_monthly/clean"),
    Path("eia_monthly/series.csv"),
    Path("eia_monthly/diesel_monthly.csv.bak"),
    Path("eia_monthly/diesel.csv.bak"),
    Path("eia_weekly/raw"),
    Path("eia_weekly/raw.csv.tar.xz"),
    Path("eia_weekly/series.csv"),
]

GASOLINE_DROP_TERMS = [
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

GASOLINE_TRADE_PRODUCTS = [
    "Finished Motor Gasoline",
    "Gasoline Blending Components",
    "Fuel Ethanol",
]

GASOLINE_TRADE_TOKENS = [
    " Imports",
    " Exports",
    " Net Imports",
]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def canonicalize_output_names() -> list[dict[str, str]]:
    moved: list[dict[str, str]] = []
    for source, target in LEGACY_OUTPUTS.items():
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        moved.append({"source": str(source), "target": str(target)})
    return moved


def prune_non_output_artifacts() -> list[str]:
    removed: list[str] = []
    for path in PRUNE_PATHS:
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path))
    return removed


def drop_monthly_barrel_duplicates(fieldnames: list[str]) -> tuple[list[str], list[str]]:
    per_day_columns = set(fieldnames)
    drop: list[str] = []
    for column in fieldnames:
        if "(Thousand Barrels)" not in column:
            continue
        per_day = column.replace("(Thousand Barrels)", "(Thousand Barrels per Day)")
        if per_day in per_day_columns:
            drop.append(column)
    keep = [column for column in fieldnames if column not in set(drop)]
    return keep, drop


def drop_gasoline_component_subtypes(fieldnames: list[str]) -> tuple[list[str], list[str]]:
    drop = [
        column
        for column in fieldnames
        if any(term.lower() in column.lower() for term in GASOLINE_DROP_TERMS)
    ]
    keep = [column for column in fieldnames if column not in set(drop)]
    return keep, drop


def is_trade_column(column: str) -> bool:
    if column.startswith("Kpler ") or column.startswith("Estimated PADD "):
        return False
    return any(token in column for token in GASOLINE_TRADE_TOKENS)


def has_gasoline_trade_product(column: str) -> bool:
    return any(product in column for product in GASOLINE_TRADE_PRODUCTS)


def is_allowed_gasoline_monthly_trade(column: str) -> bool:
    for product in GASOLINE_TRADE_PRODUCTS:
        padd1_prefix = f"East Coast (PADD 1) Imports of {product}"
        if column == f"{padd1_prefix} (Thousand Barrels per Day)":
            return True
        if column in {
            f"{padd1_prefix} from Europe (Thousand Barrels per Day)",
            f"{padd1_prefix} from Africa (Thousand Barrels per Day)",
            f"{padd1_prefix} from Middle East (Thousand Barrels per Day)",
            f"{padd1_prefix} from Canada/Other (Thousand Barrels per Day)",
        }:
            return True

        padd5_prefix = f"West Coast (PADD 5) Imports of {product}"
        if column == f"{padd5_prefix} (Thousand Barrels per Day)":
            return True
        if column in {
            f"{padd5_prefix} from Asia including India (Thousand Barrels per Day)",
            f"{padd5_prefix} from Other (Thousand Barrels per Day)",
        }:
            return True

        padd3_prefix = f"Gulf Coast (PADD 3) Exports of {product}"
        if column == f"{padd3_prefix} (Thousand Barrels per Day)":
            return True
        if column in {
            f"{padd3_prefix} to Africa (Thousand Barrels per Day)",
            f"{padd3_prefix} to Latin America (Thousand Barrels per Day)",
            f"{padd3_prefix} to Other (Thousand Barrels per Day)",
        }:
            return True
    return False


def is_allowed_gasoline_weekly_trade(column: str) -> bool:
    for product in GASOLINE_TRADE_PRODUCTS:
        if column in {
            f"weekly East Coast (PADD 1) Imports of {product}",
            f"weekly Midwest (PADD 2) Imports of {product}",
            f"weekly Gulf Coast (PADD 3) Imports of {product}",
            f"weekly Rocky Mountain (PADD 4) Imports of {product}",
            f"weekly West Coast (PADD 5) Imports of {product}",
        }:
            return True
    return False


def drop_gasoline_trade_detail_columns(path: Path, fieldnames: list[str]) -> tuple[list[str], list[str]]:
    drop: list[str] = []
    for column in fieldnames:
        if not is_trade_column(column):
            continue
        if path.parts[0] == "eia_monthly":
            if not is_allowed_gasoline_monthly_trade(column):
                drop.append(column)
            continue
        if path.parts[0] == "eia_weekly":
            if not is_allowed_gasoline_weekly_trade(column):
                drop.append(column)
            continue
    keep = [column for column in fieldnames if column not in set(drop)]
    return keep, drop


def clean_time_series(path: Path) -> dict[str, object]:
    fieldnames, rows = read_csv(path)
    if not fieldnames:
        return {"path": str(path), "rows": 0, "dropped_columns": []}
    date_col = fieldnames[0]
    rows.sort(key=lambda row: row.get(date_col, ""), reverse=True)
    dropped: list[str] = []
    if path.parts[0] == "eia_monthly":
        fieldnames, dropped = drop_monthly_barrel_duplicates(fieldnames)
    if path in GASOLINE_OUTPUTS:
        fieldnames, gasoline_dropped = drop_gasoline_component_subtypes(fieldnames)
        dropped.extend(gasoline_dropped)
        fieldnames, gasoline_trade_dropped = drop_gasoline_trade_detail_columns(path, fieldnames)
        dropped.extend(gasoline_trade_dropped)
    write_csv(path, fieldnames, rows)
    return {
        "path": str(path),
        "rows": len(rows),
        "date_column": date_col,
        "latest": rows[0].get(date_col, "") if rows else "",
        "oldest": rows[-1].get(date_col, "") if rows else "",
        "dropped_columns": dropped,
        "column_count": len(fieldnames),
    }


def main() -> int:
    moved = canonicalize_output_names()
    results = [clean_time_series(path) for path in TIME_SERIES_FILES if path.exists()]
    removed = prune_non_output_artifacts()
    for item in moved:
        print(f"renamed {item['source']} -> {item['target']}")
    for item in results:
        print(
            f"{item['path']} rows={item['rows']} columns={item['column_count']} "
            f"latest={item['latest']} oldest={item['oldest']} dropped={len(item['dropped_columns'])}"
        )
    if removed:
        print(f"removed non-output artifacts={len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
