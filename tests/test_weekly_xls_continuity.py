from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weekly_xls import clean_output_dir, require_weekly_continuity, weekly_continuity_breaks  # noqa: E402


def weekly_rows(*weeks: str) -> list[dict[str, str]]:
    return [{"week_ending": week, "period_type": "weekly"} for week in weeks]


class WeeklyContinuityTests(unittest.TestCase):
    def test_cleanup_preserves_prior_clean_exports_for_gap_filling(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            for filename in ["diesel.csv", "jet.csv", "gasoline.csv", "raw", "manifest.json"]:
                (output / filename).write_text("prior", encoding="utf-8")

            clean_output_dir(output)

            for filename in ["diesel.csv", "jet.csv", "gasoline.csv"]:
                self.assertTrue((output / filename).is_file())
            self.assertFalse((output / "raw").exists())
            self.assertFalse((output / "manifest.json").exists())

    def test_accepts_consecutive_week_endings(self) -> None:
        rows = weekly_rows("2026-07-10", "2026-07-17", "2026-07-24", "2026-07-31")

        self.assertEqual(weekly_continuity_breaks(rows), [])
        require_weekly_continuity(rows)

    def test_rejects_silently_skipped_weeks(self) -> None:
        rows = weekly_rows("2026-07-10", "2026-07-31", "2026-08-07")

        self.assertEqual(weekly_continuity_breaks(rows), [("2026-07-10", "2026-07-31", 21)])
        with self.assertRaisesRegex(ValueError, "2026-07-10->2026-07-31"):
            require_weekly_continuity(rows)


if __name__ == "__main__":
    unittest.main()
