from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weekly_xls import require_weekly_continuity, weekly_continuity_breaks  # noqa: E402


def weekly_rows(*weeks: str) -> list[dict[str, str]]:
    return [{"week_ending": week, "period_type": "weekly"} for week in weeks]


class WeeklyContinuityTests(unittest.TestCase):
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
