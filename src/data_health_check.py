from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any


PRODUCTS = ["diesel", "jet", "gasoline"]
REPORT_PATH = Path("data_health_report.json")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def add_check(checks: list[dict[str, Any]], name: str, status: str, **details: Any) -> None:
    checks.append({"name": name, "status": status, **details})


def parse_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def parse_timestamp_day(value: str) -> date | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def csv_summary(path: Path, date_column: str) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "rows": 0, "columns": 0, "min_date": "", "max_date": ""}
    rows = 0
    min_date = ""
    max_date = ""
    columns = 0
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        columns = len(reader.fieldnames or [])
        for row in reader:
            rows += 1
            value = str(row.get(date_column, "")).strip()
            if value:
                min_date = value if not min_date or value < min_date else min_date
                max_date = value if not max_date or value > max_date else max_date
    return {
        "path": str(path),
        "exists": True,
        "rows": rows,
        "columns": columns,
        "min_date": min_date,
        "max_date": max_date,
    }


def duplicate_count(path: Path, key_columns: list[str]) -> int:
    if not path.exists():
        return 0
    seen: set[tuple[str, ...]] = set()
    duplicates = 0
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            key = tuple(str(row.get(column, "")) for column in key_columns)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
    return duplicates


def csv_unique_values(path: Path, column: str) -> set[str]:
    values: set[str] = set()
    if not path.exists():
        return values
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            value = str(row.get(column, "")).strip()
            if value:
                values.add(value)
    return values


def check_eia_tables(checks: list[dict[str, Any]], report: dict[str, Any], today: date) -> None:
    weekly: dict[str, dict[str, Any]] = {}
    monthly: dict[str, dict[str, Any]] = {}
    for product in PRODUCTS:
        weekly[product] = csv_summary(Path("eia_weekly") / f"{product}.csv", "week_ending")
        monthly[product] = csv_summary(Path("eia_monthly") / f"{product}.csv", "Date")

    report["eia_weekly"] = weekly
    report["eia_monthly"] = monthly

    for product, stats in weekly.items():
        status = "pass" if stats["exists"] and stats["rows"] >= 500 and stats["max_date"] else "fail"
        add_check(checks, f"eia_weekly_{product}", status, **stats)
    weekly_latest = {product: stats["max_date"] for product, stats in weekly.items()}
    latest_values = set(weekly_latest.values())
    add_check(
        checks,
        "eia_weekly_latest_aligned",
        "pass" if len(latest_values) == 1 and "" not in latest_values else "fail",
        latest_by_product=weekly_latest,
    )
    if latest_values and "" not in latest_values:
        latest = parse_day(max(latest_values))
        add_check(
            checks,
            "eia_weekly_freshness",
            "pass" if latest >= today - timedelta(days=14) else "fail",
            latest=str(latest),
            today=str(today),
            max_allowed_age_days=14,
        )

    for product, stats in monthly.items():
        status = "pass" if stats["exists"] and stats["rows"] >= 100 and stats["max_date"] else "fail"
        add_check(checks, f"eia_monthly_{product}", status, **stats)
    monthly_latest = {product: stats["max_date"] for product, stats in monthly.items()}
    latest_values = set(monthly_latest.values())
    add_check(
        checks,
        "eia_monthly_latest_aligned",
        "pass" if len(latest_values) == 1 and "" not in latest_values else "fail",
        latest_by_product=monthly_latest,
    )
    if latest_values and "" not in latest_values:
        latest = parse_day(max(latest_values))
        add_check(
            checks,
            "eia_monthly_freshness",
            "pass" if latest >= today - timedelta(days=150) else "fail",
            latest=str(latest),
            today=str(today),
            max_allowed_age_days=150,
        )


def check_kpler(checks: list[dict[str, Any]], report: dict[str, Any]) -> None:
    for label, path in {
        "kpler": Path("Kpler/manifest.json"),
        "kpler_padd1_eia_split": Path("Kpler/padd1_eia_split_manifest.json"),
    }.items():
        if not path.exists():
            add_check(checks, label, "fail", path=str(path), error="missing manifest")
            continue
        manifest = read_json(path)
        rows = int((manifest.get("normalized_long") or {}).get("rows") or 0)
        mode = str(manifest.get("mode", ""))
        report[label] = {
            "path": str(path),
            "mode": mode,
            "rows": rows,
            "generated_at": manifest.get("generated_at", ""),
        }
        add_check(
            checks,
            label,
            "pass" if mode != "dry_run" and rows > 0 else "fail",
            path=str(path),
            mode=mode,
            rows=rows,
        )


def check_capacity(checks: list[dict[str, Any]], report: dict[str, Any], today: date) -> None:
    manifest_path = Path("eia_capacity/manifest.json")
    if not manifest_path.exists():
        add_check(checks, "eia_capacity_manifest", "fail", path=str(manifest_path), error="missing manifest")
        return
    manifest = read_json(manifest_path)
    report["eia_capacity"] = manifest
    current_month = today.strftime("%Y-%m")
    prior_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    add_check(
        checks,
        "eia_capacity_manifest",
        "pass"
        if int(manifest.get("monthly_rows") or 0) > 0
        and int(manifest.get("high_level_monthly_rows") or 0) > 0
        and str(manifest.get("end_month", "")) >= prior_month
        else "fail",
        end_month=manifest.get("end_month", ""),
        current_month=current_month,
        min_allowed_end_month=prior_month,
        monthly_rows=manifest.get("monthly_rows", 0),
        high_level_monthly_rows=manifest.get("high_level_monthly_rows", 0),
    )
    outputs = manifest.get("outputs") or {}
    monthly_path = Path(str(outputs.get("monthly_long", "eia_capacity/downstream_charge_capacity_monthly.csv")))
    high_level_path = Path(str(outputs.get("high_level_monthly", "eia_capacity/downstream_charge_capacity_high_level_monthly.csv")))
    group_map_path = Path(str(outputs.get("capacity_group_map", "eia_capacity/capacity_group_map.csv")))
    monthly_dupes = duplicate_count(monthly_path, ["period_month", "series_id"])
    high_level_dupes = duplicate_count(
        high_level_path,
        ["period_month", "geography_code", "capacity_group_id", "capacity_basis"],
    )
    add_check(checks, "eia_capacity_monthly_duplicates", "pass" if monthly_dupes == 0 else "fail", duplicates=monthly_dupes)
    add_check(checks, "eia_capacity_high_level_duplicates", "pass" if high_level_dupes == 0 else "fail", duplicates=high_level_dupes)
    groups = csv_unique_values(group_map_path, "capacity_group")
    required_groups = {"FCC Capacity", "Hydrocracking Capacity", "Reforming Capacity"}
    add_check(
        checks,
        "eia_capacity_high_level_groups",
        "pass" if required_groups.issubset(groups) else "fail",
        required=sorted(required_groups),
        available_count=len(groups),
    )
    manual_input = manifest.get("manual_input") or {}
    manual_path = Path(str(manual_input.get("path", "eia_capacity/manual_capacity.csv")))
    manual_template = Path(str(manual_input.get("template", "eia_capacity/manual_capacity_template.csv")))
    add_check(
        checks,
        "eia_capacity_manual_input",
        "pass" if manual_path.exists() and manual_template.exists() else "fail",
        manual_path=str(manual_path),
        template=str(manual_template),
        mode=manual_input.get("mode", ""),
    )


def check_balances(checks: list[dict[str, Any]], report: dict[str, Any]) -> None:
    balances: dict[str, dict[str, Any]] = {}
    for product, folder in {"diesel": "Diesel_Balance", "jet": "Jet_Balance"}.items():
        path = Path(folder) / "manifest.json"
        if not path.exists():
            add_check(checks, f"{product}_balance_manifest", "fail", path=str(path), error="missing manifest")
            continue
        manifest = read_json(path)
        balances[product] = {
            "path": str(path),
            "generated_at": manifest.get("generatedAt", ""),
            "latest_weekly": manifest.get("latestWeekly", ""),
            "latest_monthly": manifest.get("latestMonthly", ""),
        }
        weekly_latest = (report.get("eia_weekly") or {}).get(product, {}).get("max_date", "")
        monthly_latest = (report.get("eia_monthly") or {}).get(product, {}).get("max_date", "")
        add_check(
            checks,
            f"{product}_balance_latest",
            "pass"
            if manifest.get("latestWeekly") == weekly_latest and manifest.get("latestMonthly") == monthly_latest
            else "fail",
            balance_weekly=manifest.get("latestWeekly", ""),
            eia_weekly=weekly_latest,
            balance_monthly=manifest.get("latestMonthly", ""),
            eia_monthly=monthly_latest,
        )
    report["balances"] = balances


def check_context_feeds(checks: list[dict[str, Any]], report: dict[str, Any], today: date) -> None:
    jodi_path = Path("Jodi_Data/manifest.json")
    if jodi_path.exists():
        manifest = read_json(jodi_path)
        outputs = manifest.get("outputs") or {}
        latest_periods = [
            str(output.get("max_period_month", ""))
            for output in outputs.values()
            if isinstance(output, dict) and output.get("max_period_month")
        ]
        row_counts = [int(output.get("rows") or 0) for output in outputs.values() if isinstance(output, dict)]
        latest = max(latest_periods) if latest_periods else ""
        monthly_latest = max(
            (str(stats.get("max_date", "")) for stats in (report.get("eia_monthly") or {}).values()),
            default="",
        )
        report["jodi"] = {
            "path": str(jodi_path),
            "generated_at": manifest.get("generated_at", ""),
            "latest_period_month": latest,
            "outputs": len(outputs),
            "rows": sum(row_counts),
        }
        add_check(
            checks,
            "jodi_outputs",
            "pass" if latest[:7] >= monthly_latest[:7] and sum(row_counts) > 0 else "warn",
            latest_period_month=latest,
            eia_monthly_latest=monthly_latest,
            rows=sum(row_counts),
        )
    else:
        add_check(checks, "jodi_outputs", "warn", path=str(jodi_path), error="missing manifest")

    power_path = Path("power_generation_dfo/manifest.json")
    if power_path.exists():
        manifest = read_json(power_path)
        run_end = parse_day(str(manifest.get("run_end", "1900-01-01")))
        row_counts = manifest.get("row_counts") or {}
        report["power_generation_dfo"] = {
            "path": str(power_path),
            "generated_at": manifest.get("generated_at", ""),
            "run_end": manifest.get("run_end", ""),
            "row_counts": row_counts,
        }
        add_check(
            checks,
            "power_generation_dfo",
            "pass" if run_end >= today - timedelta(days=7) and all(int(value or 0) > 0 for value in row_counts.values()) else "warn",
            run_end=str(run_end),
            today=str(today),
        )
    else:
        add_check(checks, "power_generation_dfo", "warn", path=str(power_path), error="missing manifest")

    hourly_path = Path("power_generation_dfo/hourly_forecast_manifest.json")
    if hourly_path.exists():
        manifest = read_json(hourly_path)
        generated_day = parse_timestamp_day(str(manifest.get("generated_at", "")))
        row_counts = manifest.get("row_counts") or {}
        report["power_generation_dfo_hourly"] = {
            "path": str(hourly_path),
            "generated_at": manifest.get("generated_at", ""),
            "row_counts": row_counts,
        }
        add_check(
            checks,
            "power_generation_dfo_hourly",
            "pass"
            if generated_day is not None
            and generated_day >= today - timedelta(days=7)
            and all(int(value or 0) > 0 for value in row_counts.values())
            else "warn",
            generated_day=str(generated_day) if generated_day else "",
            today=str(today),
        )


def main() -> int:
    today = date.today()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today": str(today),
    }
    checks: list[dict[str, Any]] = []
    check_eia_tables(checks, report, today)
    check_kpler(checks, report)
    check_capacity(checks, report, today)
    check_balances(checks, report)
    check_context_feeds(checks, report, today)

    counts = Counter(check["status"] for check in checks)
    report["checks"] = checks
    report["summary"] = dict(counts)
    report["status"] = "fail" if counts.get("fail", 0) else "pass"
    write_json(REPORT_PATH, report)

    print(
        f"data health {report['status'].upper()} "
        f"pass={counts.get('pass', 0)} warn={counts.get('warn', 0)} fail={counts.get('fail', 0)} "
        f"report={REPORT_PATH}"
    )
    for check in checks:
        if check["status"] == "fail":
            print(f"FAIL {check['name']}: {json.dumps(check, sort_keys=True)}")
    return 1 if counts.get("fail", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
