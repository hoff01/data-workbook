from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import polars as pl

from kpler_config import BASE_DIR, OUTPUT_DIR, RAW_DIR, PullSpec, build_pull_specs, credential_pair, ensure_directories, runtime_config
from kpler_http import KplerHttpClient
from kpler_transform import LONG_COLUMNS, build_outputs, kpler_content_to_long
from kpler_validate import validate_outputs


SPLIT_PARAM_VALUES = {
    "destination countries": "Destination Countries",
    "destination padds": "Destination Padds",
    "destination trading regions": "Destination Trading Regions",
    "origin countries": "Origin Countries",
    "origin padds": "Origin Padds",
    "origin trading regions": "Origin Trading Regions",
    "products": "Products",
    "total": "Total",
}


def list_param(values: list[str] | None) -> str | None:
    return ",".join(values) if values else None


def split_param(values: list[str] | None) -> str | None:
    if not values:
        return None
    return SPLIT_PARAM_VALUES.get(values[0].lower(), values[0])


def bool_param(value: bool | None) -> str | None:
    return str(value).lower() if value is not None else None


EIA_PRODUCT_LABELS = {
    "diesel": ["Distillate Fuel Oil"],
    "jet": ["Kerosene-Type Jet Fuel"],
    "gasoline": ["Finished Motor Gasoline", "Fuel Ethanol", "Gasoline Blending Components"],
}

WEEKLY_US_EXPORT_COLUMNS = {
    "diesel": ["weekly U.S. Exports of Total Distillate"],
    "jet": ["weekly U.S. Exports of Total Distillate"],
    "gasoline": [],
}

REPO_DIR = Path(__file__).resolve().parents[1]
EIA_SOURCE_DIRS = {
    "monthly": REPO_DIR / "eia_monthly",
    "weekly": REPO_DIR / "eia_weekly",
}


def has_kpler_credentials() -> bool:
    username = os.environ.get("KPLER_EMAIL") or os.environ.get("KPLER_USERNAME")
    return bool(username and os.environ.get("KPLER_PASSWORD"))


def parse_eia_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def iter_days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def month_end_exclusive(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def as_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def sum_columns(row: dict[str, str], columns: list[str]) -> float:
    return sum(as_float(row.get(column, "")) for column in columns)


def read_eia_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def is_aggregate_trade_column(column: str, product: str, flow: str, weekly: bool) -> bool:
    lower = column.lower()
    if flow == "import" and " imports of " not in lower:
        return False
    if flow == "export" and " exports of " not in lower:
        return False
    if f" of {product.lower()}" not in lower:
        return False
    if " from " in lower or " to " in lower:
        return False
    if weekly:
        return column.startswith("weekly ") and ("u.s." not in lower and "u. s." not in lower)
    return any(
        column.startswith(prefix)
        for prefix in ["East Coast (PADD 1)", "Midwest (PADD 2)", "Gulf Coast (PADD 3)", "Rocky Mountain", "West Coast (PADD 5)"]
    )


def weekly_trade_columns(columns: list[str], commodity: str, flow: str) -> list[str]:
    if flow == "export":
        configured = [column for column in WEEKLY_US_EXPORT_COLUMNS[commodity] if column in columns]
        if configured:
            return configured
    us_columns: list[str] = []
    aggregate_columns: list[str] = []
    for product in EIA_PRODUCT_LABELS[commodity]:
        for column in columns:
            lower = column.lower()
            if flow == "import" and column == f"weekly U.S. Imports of {product}":
                us_columns.append(column)
            elif flow == "export" and column == f"weekly U.S. Exports of {product}":
                us_columns.append(column)
            elif is_aggregate_trade_column(column, product, flow, weekly=True):
                aggregate_columns.append(column)
    return us_columns or aggregate_columns


def monthly_trade_columns(columns: list[str], commodity: str, flow: str) -> list[str]:
    us_columns: list[str] = []
    aggregate_columns: list[str] = []
    for product in EIA_PRODUCT_LABELS[commodity]:
        for column in columns:
            lower = column.lower()
            if f" of {product.lower()}" not in lower:
                continue
            if flow == "import" and " imports of " not in lower:
                continue
            if flow == "export" and " exports of " not in lower:
                continue
            if " from " in lower or " to " in lower:
                continue
            if column.startswith("U.S.") or column.startswith("U. S."):
                us_columns.append(column)
            elif any(
                column.startswith(prefix)
                for prefix in [
                    "East Coast (PADD 1)",
                    "Midwest (PADD 2)",
                    "Gulf Coast (PADD 3)",
                    "Rocky Mountain",
                    "West Coast (PADD 5)",
                ]
            ):
                aggregate_columns.append(column)
    return us_columns or aggregate_columns


def monthly_eia_daily_values(commodity: str, flow: str, start_date: date, end_date: date) -> dict[date, float]:
    path = EIA_SOURCE_DIRS["monthly"] / f"{commodity}.csv"
    columns, rows = read_eia_rows(path)
    if not columns:
        return {}
    source_columns = monthly_trade_columns(columns, commodity, flow)
    if not source_columns:
        return {}
    values: dict[date, float] = {}
    date_column = columns[0]
    for row in rows:
        parsed = parse_eia_date(row.get(date_column, ""))
        if not parsed:
            continue
        month_start = parsed.replace(day=1)
        month_end = month_end_exclusive(month_start)
        value = sum_columns(row, source_columns)
        for current in iter_days(max(start_date, month_start), min(end_date, month_end - timedelta(days=1))):
            values[current] = value
    return values


def weekly_eia_daily_values(commodity: str, flow: str, start_date: date, end_date: date) -> dict[date, float]:
    path = EIA_SOURCE_DIRS["weekly"] / f"{commodity}.csv"
    columns, rows = read_eia_rows(path)
    if not columns:
        return {}
    source_columns = weekly_trade_columns(columns, commodity, flow)
    if not source_columns:
        return {}
    values: dict[date, float] = {}
    date_column = columns[0]
    for row in rows:
        week_ending = parse_eia_date(row.get(date_column, ""))
        if not week_ending:
            continue
        week_start = week_ending - timedelta(days=6)
        value = sum_columns(row, source_columns)
        for current in iter_days(max(start_date, week_start), min(end_date, week_ending)):
            values[current] = value
    return values


def fallback_long_row(day: date, spec: PullSpec, value: float) -> dict[str, Any]:
    row: dict[str, Any] = {column: "" for column in LONG_COLUMNS}
    is_import = spec.flow_direction == "import"
    row.update(
        {
            "date": day.isoformat(),
            "pull_set": spec.name,
            "family": spec.family,
            "geography": spec.geography,
            "commodity": spec.commodity,
            "kpler_product": spec.kpler_product,
            "flow_direction": spec.flow_direction,
            "origin_country": "EIA fallback" if is_import else "United States",
            "destination_country": "United States" if is_import else "EIA fallback",
            "origin_trading_region": "EIA fallback" if is_import else "",
            "destination_trading_region": "" if is_import else "EIA fallback",
            "origin_padd": "" if is_import else "PADD 1A/B",
            "destination_padd": "PADD 1A/B" if is_import else "",
            "region_detail": spec.region_detail,
            "route_group": spec.route_group,
            "unit": spec.unit,
            "value_kbd": value,
            "with_intra_country": spec.with_intra_country,
            "with_intra_region": spec.with_intra_region,
            "with_forecast": spec.with_forecast,
            "only_realized": spec.only_realized,
            "snapshot_date": "",
            "source_hash": "eia_fallback",
        }
    )
    return row


def build_eia_fallback_long(specs: list[PullSpec], start_date: date, end_date: date) -> tuple[pl.DataFrame, dict[str, Any]]:
    us_specs = {
        (spec.commodity, spec.flow_direction): spec
        for spec in specs
        if spec.family == "external" and spec.geography == "us" and spec.commodity in EIA_PRODUCT_LABELS
    }
    rows: list[dict[str, Any]] = []
    status: dict[str, Any] = {}
    for commodity in EIA_PRODUCT_LABELS:
        for flow in ["import", "export"]:
            spec = us_specs.get((commodity, flow))
            if spec is None:
                continue
            daily_values = monthly_eia_daily_values(commodity, flow, start_date, end_date)
            daily_values.update(weekly_eia_daily_values(commodity, flow, start_date, end_date))
            for day, value in sorted(daily_values.items()):
                rows.append(fallback_long_row(day, spec, value))
            status[spec.name] = {
                "status": "eia_fallback",
                "source": "EIA clean weekly/monthly exports",
                "assumption": "no Kpler credentials; EIA import/export values are staged as Kpler-shaped rows",
                "rows": len(daily_values),
            }
    if not rows:
        return pl.DataFrame({column: [] for column in LONG_COLUMNS}), status
    return pl.DataFrame(rows).select(LONG_COLUMNS), status


def csv_filter_values(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def filter_pull_specs(specs: list[PullSpec]) -> list[PullSpec]:
    families = csv_filter_values(os.environ.get("KPLER_PULL_FAMILIES"))
    names = csv_filter_values(os.environ.get("KPLER_PULL_NAMES"))
    route_groups = csv_filter_values(os.environ.get("KPLER_PULL_ROUTE_GROUPS"))
    filtered = [
        spec
        for spec in specs
        if (not families or spec.family in families)
        and (not names or spec.name in names)
        and (not route_groups or spec.route_group in route_groups)
    ]
    if (families or names or route_groups) and not filtered:
        raise RuntimeError("Kpler pull filters matched no specs.")
    return filtered


def spec_to_kpler_params(spec: PullSpec, snapshot_date=None) -> dict[str, Any]:
    return {
        "flowDirection": spec.flow_direction,
        "split": split_param(spec.split),
        "granularity": spec.granularity,
        "startDate": spec.start_date.isoformat(),
        "endDate": spec.end_date.isoformat(),
        "fromZones": list_param(spec.from_zones),
        "toZones": list_param(spec.to_zones),
        "products": spec.kpler_product,
        "onlyRealized": bool_param(spec.only_realized),
        "unit": spec.unit,
        "withIntraCountry": bool_param(spec.with_intra_country),
        "withIntraRegion": bool_param(spec.with_intra_region),
        "withForecast": bool_param(spec.with_forecast),
        "withFreightView": "false",
        "withProductEstimation": "false",
        "snapshotDate": snapshot_date.isoformat() if snapshot_date else None,
    }
    


def safe_file_fragment(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def write_raw_response(spec: PullSpec, content: bytes, suffix: str | None = None) -> dict[str, Any]:
    raw_dir = RAW_DIR / spec.family
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = spec.name if not suffix else f"{spec.name}__{safe_file_fragment(suffix)}"
    path = raw_dir / f"{stem}.csv"
    path.write_bytes(content)
    return {
        "path": str(path),
        "rows": max(0, content.count(b"\n") - 1),
        "columns": content.splitlines()[0].decode("utf-8", errors="replace").split(";") if content else [],
        "bytes": path.stat().st_size,
    }


def fetch_single_split(
    spec: PullSpec,
    client: KplerHttpClient,
    snapshot_date,
    retry_count: int,
    retry_backoff_seconds: float,
    suffix: str | None = None,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    params = spec_to_kpler_params(spec, snapshot_date=snapshot_date)
    last_error: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            response = client.get("flows", params)
            raw_info = write_raw_response(spec, response.content, suffix=suffix)
            long_rows = kpler_content_to_long(response.content, spec)
            return long_rows, {
                "status": "ok",
                "attempts": attempt,
                "raw": raw_info,
                "params": {key: value for key, value in params.items() if value is not None},
                "url": response.url,
            }
        except Exception as exc:
            last_error = exc
            if attempt < retry_count:
                time.sleep(retry_backoff_seconds * attempt)
    raise RuntimeError(f"{spec.name} failed after {retry_count} attempts: {last_error}") from last_error


def fetch_spec(spec: PullSpec, client: KplerHttpClient, snapshot_date, retry_count: int, retry_backoff_seconds: float) -> tuple[PullSpec, pl.DataFrame, dict[str, Any]]:
    split_values = spec.split or [""]
    frames: list[pl.DataFrame] = []
    split_statuses: list[dict[str, Any]] = []
    for split_value in split_values:
        single_split_spec = replace(spec, split=[split_value] if split_value else [])
        split_label = split_param(single_split_spec.split) or "total"
        frame, status = fetch_single_split(
            single_split_spec,
            client,
            snapshot_date,
            retry_count,
            retry_backoff_seconds,
            suffix=split_label if len(split_values) > 1 else None,
        )
        frames.append(frame)
        split_statuses.append({"split": split_label, **status})
    long_frame = pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame({column: [] for column in LONG_COLUMNS})
    return spec, long_frame, {
        "status": "ok",
        "splits": split_statuses,
        "rows": int(long_frame.height),
    }


def write_manifest(payload: dict[str, Any]) -> None:
    path = BASE_DIR / "manifest.json"
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def cleanup_inactive_output_files(outputs: dict[str, dict[str, Any]]) -> list[str]:
    active_paths: set[Path] = set()
    for output in outputs.values():
        for key, value in output.items():
            if key.endswith("_path") and value:
                active_paths.add(Path(str(value)).resolve())
    removed: list[str] = []
    for folder in [OUTPUT_DIR / "daily", OUTPUT_DIR / "weekly", OUTPUT_DIR / "monthly"]:
        if not folder.exists():
            continue
        for path in folder.glob("*.csv"):
            if path.resolve() in active_paths:
                continue
            path.unlink()
            removed.append(str(path))
    return removed


def dry_run_manifest(specs: list[PullSpec]) -> dict[str, Any]:
    return {
        "pipeline_name": "kpler_flows",
        "mode": "dry_run",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpler_access_mode": "direct_http",
        "pull_count": len(specs),
        "pulls": [spec.manifest_dict() for spec in specs],
    }


def run(args: argparse.Namespace) -> int:
    ensure_directories()
    config = runtime_config()
    specs = filter_pull_specs(build_pull_specs(config))
    if args.dry_run or args.preflight:
        payload = dry_run_manifest(specs)
        payload["runtime_config"] = {
            **asdict(config),
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "snapshot_date": config.snapshot_date.isoformat() if config.snapshot_date else "",
        }
        write_manifest(payload)
        mode = "preflight" if args.preflight else "dry-run"
        print(
            f"kpler {mode} pull_specs={len(specs)} start={config.start_date} end={config.end_date} "
            f"manifest={BASE_DIR / 'manifest.json'}"
        )
        return 0

    mode = "live"
    access_mode = "direct_http"
    if has_kpler_credentials():
        client = KplerHttpClient(config)
        all_long: list[pl.DataFrame] = []
        pull_status: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
            futures = {
                executor.submit(fetch_spec, spec, client, config.snapshot_date, config.retry_count, config.retry_backoff_seconds): spec
                for spec in specs
            }
            for future in as_completed(futures):
                spec, long_rows, status = future.result()
                pull_status[spec.name] = status
                all_long.append(long_rows)
                print(f"kpler pulled {spec.name} rows={long_rows.height}")
        long_frame = pl.concat(all_long, how="diagonal_relaxed") if all_long else pl.DataFrame({column: [] for column in LONG_COLUMNS})
    else:
        mode = "eia_fallback"
        access_mode = "eia_fallback_no_credentials"
        long_frame, pull_status = build_eia_fallback_long(specs, config.start_date, config.end_date)
        print(f"kpler eia fallback rows={long_frame.height} start={config.start_date} end={config.end_date}")

    normalized_path = BASE_DIR / "raw" / "daily" / "normalized_long.csv"
    long_frame.write_csv(normalized_path)
    outputs = build_outputs(long_frame, config.start_date, config.end_date)
    removed_outputs = cleanup_inactive_output_files(outputs)
    validation = validate_outputs(outputs)
    manifest = {
        "pipeline_name": "kpler_flows",
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpler_access_mode": access_mode,
        "runtime_config": {
            **asdict(config),
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "snapshot_date": config.snapshot_date.isoformat() if config.snapshot_date else "",
        },
        "pull_count": len(specs),
        "pulls": [spec.manifest_dict() for spec in specs],
        "pull_status": pull_status,
        "normalized_long": {"path": str(normalized_path), "rows": int(long_frame.height)},
        "outputs": outputs,
        "removed_outputs": removed_outputs,
        "validation": validation,
    }
    write_manifest(manifest)
    print(f"kpler mode={mode} rows={long_frame.height} outputs={len(outputs)} manifest={BASE_DIR / 'manifest.json'}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Kpler flows and build balance-ready outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Build pull specs and manifest without importing/calling Kpler.")
    parser.add_argument("--preflight", action="store_true", help="Show dynamic runtime settings and write a manifest without calling Kpler.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(sys.argv[1:] if argv is None else argv))
    except RuntimeError as exc:
        print(f"kpler error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
