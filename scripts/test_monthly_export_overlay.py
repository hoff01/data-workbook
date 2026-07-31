from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import export_raw_headers


PRODUCT = "Distillate Fuel Oil"


def assert_export_overlay() -> None:
    padd = "Gulf Coast (PADD 3)"
    volume_column = f"{padd} Exports of {PRODUCT} (Thousand Barrels)"
    daily_column = f"{padd} Exports of {PRODUCT} (Thousand Barrels per Day)"
    other_column = f"{padd} Exports of {PRODUCT} to Other (Thousand Barrels per Day)"
    bulk_item = {
        "f": "M",
        "units": "Thousand Barrels",
        "name": f"{padd} Exports of {PRODUCT}, Monthly",
        "data": [["202604", 39_963]],
    }
    rows_by_month: dict[str, dict[str, object]] = {
        "2026-04-15": {"Date": "2026-04-15", volume_column: 39_963},
        "2026-05-15": {"Date": "2026-05-15", volume_column: 45_773},
    }

    assert export_raw_headers.is_monthly_flow_total_volume_series(bulk_item, PRODUCT)
    with patch.object(export_raw_headers, "iter_monthly_bulk_items", return_value=iter([bulk_item])):
        export_raw_headers.add_monthly_destination_exports(rows_by_month, PRODUCT)

    april = rows_by_month["2026-04-15"]
    may = rows_by_month["2026-05-15"]
    assert april[daily_column] == 1_332.1
    assert may[daily_column] == 1_476.548
    assert may[other_column] == 1_476.548


def assert_import_overlay() -> None:
    padd = "East Coast (PADD 1)"
    volume_column = f"{padd} Imports of {PRODUCT} (Thousand Barrels)"
    daily_column = f"{padd} Imports of {PRODUCT} (Thousand Barrels per Day)"
    other_column = f"{padd} Imports of {PRODUCT} from Other (Thousand Barrels per Day)"
    bulk_item = {
        "f": "M",
        "units": "Thousand Barrels",
        "name": f"{padd} Imports of {PRODUCT}, Monthly",
        "data": [["202604", 2_914]],
    }
    rows_by_month: dict[str, dict[str, object]] = {
        "2026-04-15": {"Date": "2026-04-15", volume_column: 2_914},
        "2026-05-15": {"Date": "2026-05-15", volume_column: 3_100},
    }

    assert export_raw_headers.is_monthly_flow_total_volume_series(bulk_item, PRODUCT)
    with patch.object(export_raw_headers, "iter_monthly_bulk_items", return_value=iter([bulk_item])):
        export_raw_headers.add_monthly_origin_imports(rows_by_month, PRODUCT)

    april = rows_by_month["2026-04-15"]
    may = rows_by_month["2026-05-15"]
    assert april[daily_column] == 97.133
    assert may[daily_column] == 100.0
    assert may[other_column] == 100.0


def main() -> None:
    assert_export_overlay()
    assert_import_overlay()
    print("monthly flow overlay ok: live May PADD totals override lagging April PET bulk data")


if __name__ == "__main__":
    main()
