#!/usr/bin/env python3

from __future__ import annotations

import csv
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from export_raw_headers import (  # noqa: E402
    preserve_existing_weekly_gaps,
    read_existing_weekly_history,
)


with TemporaryDirectory() as temporary_directory:
    source = Path(temporary_directory) / "diesel.csv"
    with source.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["week_ending", "Blender production", "Reported exports"])
        writer.writeheader()
        writer.writerow({"week_ending": "2026-06-19", "Blender production": "25", "Reported exports": "1394"})

    existing = read_existing_weekly_history(source, ["Blender production", "Reported exports"])
    rows = {
        "2026-06-19": {
            "week_ending": "2026-06-19",
            "Blender production": None,
            "Reported exports": 1400.0,
        },
        "2026-06-26": {
            "week_ending": "2026-06-26",
            "Blender production": None,
            "Reported exports": 1500.0,
        },
    }
    preserved = preserve_existing_weekly_gaps(rows, existing, ["Blender production", "Reported exports"])
    assert preserved == 1
    assert rows["2026-06-19"]["Blender production"] == "25"
    assert rows["2026-06-19"]["Reported exports"] == 1400.0, "new nonblank values must win"
    assert rows["2026-06-26"]["Blender production"] is None, "missing prior values must stay missing"

print("weekly clean export continuity contract ok")
