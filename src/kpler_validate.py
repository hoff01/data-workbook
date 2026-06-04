from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl


def validate_output_file(path: Path, date_column: str) -> dict[str, Any]:
    frame = pl.read_csv(path) if path.exists() and path.stat().st_size else pl.DataFrame()
    checks: dict[str, Any] = {
        "path": str(path),
        "rows": int(frame.height),
        "duplicate_dates": False,
        "all_weekly_dates_friday": True,
        "numeric_kbd_columns": True,
    }
    if date_column in frame.columns and frame.height:
        subset = [date_column, "commodity"] if "commodity" in frame.columns else [date_column]
        checks["duplicate_dates"] = bool(frame.select(pl.struct(subset).is_duplicated().any()).item())
        if date_column == "week_ending":
            checks["all_weekly_dates_friday"] = bool(
                frame.select((pl.col(date_column).cast(pl.Date).dt.weekday() == 5).all()).item()
            )
    for column in [column for column in frame.columns if column.endswith("_kbd")]:
        null_count = frame.select(pl.col(column).cast(pl.Float64, strict=False).is_null().sum()).item()
        if null_count:
            checks["numeric_kbd_columns"] = False
    return checks


def validate_outputs(output_manifest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    file_checks = []
    for output in output_manifest.values():
        file_checks.append(validate_output_file(Path(output["daily_path"]), "date"))
        file_checks.append(validate_output_file(Path(output["weekly_path"]), "week_ending"))
        file_checks.append(validate_output_file(Path(output["monthly_path"]), "month"))
    return {
        "file_checks": file_checks,
        "all_weekly_dates_friday": all(item["all_weekly_dates_friday"] for item in file_checks),
        "no_duplicate_dates": not any(item["duplicate_dates"] for item in file_checks),
        "numeric_kbd_columns": all(item["numeric_kbd_columns"] for item in file_checks),
    }
