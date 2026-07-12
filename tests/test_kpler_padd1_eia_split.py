from __future__ import annotations

import csv
import math
from pathlib import Path
import sys
import tempfile
import unittest

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kpler_padd1_eia_split import (  # noqa: E402
    add_shares,
    load_share_lookup,
    merge_one_eia_file,
    valid_share_pair,
)


class KplerPadd1EiaSplitTests(unittest.TestCase):
    def test_weekly_share_uses_kpler_region_over_total_padd1(self) -> None:
        frame = pl.DataFrame(
            {
                "week_ending": ["2026-07-03"],
                "commodity": ["diesel"],
                "flow_direction": ["import"],
                "padd1ab_kbd": [75.0],
                "padd1c_kbd": [25.0],
                "padd1_other_kbd": [0.0],
            }
        )

        row = add_shares(frame, "week_ending").row(0, named=True)

        self.assertEqual(row["padd1_total_kbd"], 100.0)
        self.assertEqual(row["padd1ab_share"], 0.75)
        self.assertEqual(row["padd1c_share"], 0.25)

    def test_zero_or_invalid_kpler_total_defaults_to_northeast(self) -> None:
        frame = pl.DataFrame(
            {
                "week_ending": ["2026-07-03", "2026-06-26"],
                "commodity": ["diesel", "diesel"],
                "flow_direction": ["import", "import"],
                "padd1ab_kbd": [0.0, math.nan],
                "padd1c_kbd": [0.0, 10.0],
                "padd1_other_kbd": [0.0, 0.0],
            }
        )

        rows = add_shares(frame, "week_ending").rows(named=True)

        for row in rows:
            self.assertEqual(row["padd1ab_share"], 1.0)
            self.assertEqual(row["padd1c_share"], 0.0)

    def test_missing_week_allocates_full_eia_value_to_northeast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "diesel.csv"
            source = "weekly East Coast (PADD 1) Imports of Distillate Fuel Oil"
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=["week_ending", source])
                writer.writeheader()
                writer.writerow({"week_ending": "2026-07-03", source: "80"})

            merge_one_eia_file(path, "diesel", "weekly", {})

            with path.open(newline="", encoding="utf-8") as file:
                row = next(csv.DictReader(file))
            self.assertEqual(float(row["Kpler PADD 1A/B Share of PADD 1 Imports"]), 1.0)
            self.assertEqual(float(row["Kpler PADD 1C Share of PADD 1 Imports"]), 0.0)
            self.assertEqual(float(row["Estimated PADD 1A/B Imports of Distillate Fuel Oil (Kpler Split)"]), 80.0)
            self.assertEqual(float(row["Estimated PADD 1C Imports of Distillate Fuel Oil (Kpler Split)"]), 0.0)

    def test_invalid_share_file_entry_defaults_to_northeast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "shares.csv"
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "week_ending",
                        "commodity",
                        "flow_direction",
                        "padd1ab_share",
                        "padd1c_share",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "week_ending": "2026-07-03",
                        "commodity": "diesel",
                        "flow_direction": "import",
                        "padd1ab_share": "nan",
                        "padd1c_share": "0.25",
                    }
                )

            shares = load_share_lookup(path, "week_ending")

            self.assertEqual(shares[("2026-07-03", "diesel", "import")], (1.0, 0.0))

    def test_out_of_range_share_pair_defaults_to_northeast(self) -> None:
        self.assertEqual(valid_share_pair(-0.1, 1.1), (1.0, 0.0))
        self.assertEqual(valid_share_pair(0.0, 0.0), (1.0, 0.0))
        self.assertEqual(valid_share_pair(0.6, 0.2), (1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
