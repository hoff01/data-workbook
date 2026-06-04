from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import polars as pl

from kpler_config import BASE_DIR, RAW_DIR, PullSpec, credential_pair, ensure_directories, runtime_config
from kpler_http import KplerHttpClient
from kpler_pull import fallback_long_row, has_kpler_credentials, iter_days, month_end_exclusive, parse_eia_date, spec_to_kpler_params
from kpler_transform import LONG_COLUMNS, complete_daily, kpler_content_to_long


COMMODITIES = {
    "diesel": {
        "kpler_product": "Gasoil/Diesel",
        "monthly": Path("eia_monthly/diesel.csv"),
        "weekly": Path("eia_weekly/diesel.csv"),
    },
    "jet": {
        "kpler_product": "Kero/Jet",
        "monthly": Path("eia_monthly/jet.csv"),
        "weekly": Path("eia_weekly/jet.csv"),
    },
    "gasoline": {
        "kpler_product": "Light Ends",
        "monthly": Path("eia_monthly/gasoline.csv"),
        "weekly": Path("eia_weekly/gasoline.csv"),
    },
}

PADD1_SPLIT_DIR = BASE_DIR / "output" / "padd1_split"
PADD1_RAW_DIR = RAW_DIR / "padd1_split"
PADD1_MANIFEST = BASE_DIR / "padd1_eia_split_manifest.json"

SHARE_COLUMNS = {
    "import": [
        "Kpler PADD 1A/B Share of PADD 1 Imports",
        "Kpler PADD 1C Share of PADD 1 Imports",
    ],
    "export": [
        "Kpler PADD 1A/B Share of PADD 1 Exports",
        "Kpler PADD 1C Share of PADD 1 Exports",
    ],
}


def bool_label(value: bool) -> str:
    return str(value).lower()


def build_padd1_specs() -> list[PullSpec]:
    config = runtime_config()
    specs: list[PullSpec] = []
    for commodity, meta in COMMODITIES.items():
        for direction in ["import", "export"]:
            specs.append(
                PullSpec(
                    name=f"padd1_split_{commodity}_{direction}s",
                    family="padd1_split",
                    geography="us",
                    commodity=commodity,
                    kpler_product=str(meta["kpler_product"]),
                    flow_direction=direction,
                    split=[
                        "destination padds" if direction == "import" else "origin padds",
                        "products",
                    ],
                    from_zones=["United States"] if direction == "export" else None,
                    to_zones=["United States"] if direction == "import" else None,
                    with_intra_country=False,
                    with_intra_region=config.with_intra_region,
                    with_forecast=config.with_forecast,
                    only_realized=config.only_realized,
                    unit=config.unit,
                    granularity=config.granularity,
                    start_date=config.start_date,
                    end_date=config.end_date,
                )
            )
    return specs


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def write_raw(spec: PullSpec, content: bytes) -> dict[str, Any]:
    PADD1_RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = PADD1_RAW_DIR / f"{spec.name}.csv"
    path.write_bytes(content)
    return {
        "path": str(path),
        "rows": max(0, content.count(b"\n") - 1),
        "bytes": path.stat().st_size,
    }


def fetch_spec(
    spec: PullSpec,
    client: KplerHttpClient,
    snapshot_date: date | None,
    retry_count: int,
    retry_backoff_seconds: float,
) -> tuple[PullSpec, bytes, dict[str, Any]]:
    params = spec_to_kpler_params(spec, snapshot_date=snapshot_date)
    last_error: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            response = client.get("flows", params)
            return spec, response.content, {
                "status": "ok",
                "attempts": attempt,
                "raw": write_raw(spec, response.content),
                "params": {key: value for key, value in params.items() if value not in (None, "")},
                "url": response.url,
            }
        except Exception as exc:
            last_error = exc
            if attempt < retry_count:
                time.sleep(retry_backoff_seconds * attempt)
    raise RuntimeError(f"{spec.name} failed after {retry_count} attempts: {last_error}") from last_error


def load_existing_raw(specs: list[PullSpec]) -> tuple[list[pl.DataFrame], dict[str, Any]]:
    frames: list[pl.DataFrame] = []
    status: dict[str, Any] = {}
    for spec in specs:
        path = PADD1_RAW_DIR / f"{spec.name}.csv"
        if not path.exists():
            raise RuntimeError(f"missing existing Kpler raw file: {path}")
        content = path.read_bytes()
        frames.append(kpler_content_to_long(content, spec))
        status[spec.name] = {"status": "existing_raw", "raw": {"path": str(path), "bytes": path.stat().st_size}}
    return frames, status


def eia_padd1_daily_values(
    path: Path,
    commodity: str,
    flow: str,
    frequency: str,
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    fieldnames, rows = read_csv(path)
    if not fieldnames:
        return {}
    date_column = fieldnames[0]
    source_columns = [column for column in fieldnames if is_aggregate_trade_column(column, flow)]
    if not source_columns:
        return {}
    daily: dict[date, float] = {}
    for row in rows:
        parsed = parse_eia_date(row.get(date_column, ""))
        if not parsed:
            continue
        value = sum(as_float(row.get(column, "")) for column in source_columns)
        if frequency == "monthly":
            period_start = parsed.replace(day=1)
            period_end = month_end_exclusive(period_start) - timedelta(days=1)
        else:
            period_end = parsed
            period_start = period_end - timedelta(days=6)
        for current in iter_days(max(start_date, period_start), min(end_date, period_end)):
            daily[current] = value
    return daily


def build_eia_padd1_fallback_long(specs: list[PullSpec]) -> tuple[pl.DataFrame, dict[str, Any]]:
    config = runtime_config()
    spec_lookup = {(spec.commodity, spec.flow_direction): spec for spec in specs}
    rows: list[dict[str, Any]] = []
    status: dict[str, Any] = {}
    for commodity, meta in COMMODITIES.items():
        for flow in ["import", "export"]:
            spec = spec_lookup[(commodity, flow)]
            daily_values = eia_padd1_daily_values(
                Path(meta["monthly"]),
                commodity,
                flow,
                "monthly",
                config.start_date,
                config.end_date,
            )
            daily_values.update(
                eia_padd1_daily_values(
                    Path(meta["weekly"]),
                    commodity,
                    flow,
                    "weekly",
                    config.start_date,
                    config.end_date,
                )
            )
            for day, value in sorted(daily_values.items()):
                rows.append(fallback_long_row(day, spec, value))
            status[spec.name] = {
                "status": "eia_fallback",
                "source": "EIA PADD 1 aggregate import/export columns",
                "assumption": "no Kpler credentials; all available PADD 1 trade is assigned to PADD 1A/B Northeast",
                "rows": len(daily_values),
            }
    if not rows:
        return pl.DataFrame({column: [] for column in LONG_COLUMNS}), status
    return pl.DataFrame(rows).select(LONG_COLUMNS), status


def pull_kpler_long(specs: list[PullSpec], use_existing_raw: bool = False) -> tuple[pl.DataFrame, dict[str, Any]]:
    config = runtime_config()
    if use_existing_raw:
        frames, status = load_existing_raw(specs)
    elif not has_kpler_credentials():
        return build_eia_padd1_fallback_long(specs)
    else:
        credential_pair()
        client = KplerHttpClient(config)
        client.validate_auth()
        frames = []
        status = {}
        with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
            futures = {
                executor.submit(fetch_spec, spec, client, config.snapshot_date, config.retry_count, config.retry_backoff_seconds): spec
                for spec in specs
            }
            for future in as_completed(futures):
                spec, content, spec_status = future.result()
                frame = kpler_content_to_long(content, spec)
                frames.append(frame)
                status[spec.name] = spec_status
                print(f"kpler padd1 pulled {spec.name} rows={frame.height}")
    if frames:
        return pl.concat(frames, how="diagonal_relaxed"), status
    return pl.DataFrame({column: [] for column in LONG_COLUMNS}), status


def normalize_padd(value: Any) -> str:
    text = "" if value is None else str(value).upper()
    return re.sub(r"[^A-Z0-9]+", "", text)


def padd1_group(value: Any) -> str:
    text = normalize_padd(value)
    if not text:
        return ""
    if any(token in text for token in ["PADD1A", "PADDIA", "NEWENGLAND"]):
        return "padd1ab"
    if any(token in text for token in ["PADD1B", "PADDIB", "CENTRALATLANTIC"]):
        return "padd1ab"
    if any(token in text for token in ["PADD1C", "PADDIC", "LOWERATLANTIC"]):
        return "padd1c"
    if "PADD1" in text or "PADDI" in text or "EASTCOAST" in text:
        return "padd1_other"
    return ""


def week_ending_expr(column: str) -> pl.Expr:
    dt = pl.col(column).cast(pl.Date)
    return (dt + pl.duration(days=((5 - dt.dt.weekday()) % 7))).cast(pl.Utf8)


def monthly_expr(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Date).dt.truncate("1mo").cast(pl.Utf8)


def share_frame_for_period(daily: pl.DataFrame, period_column: str, assume_padd1ab: bool = False) -> pl.DataFrame:
    grouped = daily.group_by(["commodity", "flow_direction", period_column]).agg(
        [
            pl.col("padd1ab_kbd").sum().alias("padd1ab_kbd"),
            pl.col("padd1c_kbd").sum().alias("padd1c_kbd"),
            pl.col("padd1_other_kbd").sum().alias("padd1_other_kbd"),
        ]
    )
    return add_shares(grouped, period_column, assume_padd1ab=assume_padd1ab)


def add_shares(frame: pl.DataFrame, date_column: str, assume_padd1ab: bool = False) -> pl.DataFrame:
    zero_total_padd1ab_share = 1.0 if assume_padd1ab else 0.0
    return (
        frame.with_columns(
            (pl.col("padd1ab_kbd") + pl.col("padd1c_kbd") + pl.col("padd1_other_kbd")).alias("padd1_total_kbd")
        )
        .with_columns(
            [
                pl.when(pl.col("padd1_total_kbd") > 0)
                .then(pl.col("padd1ab_kbd") / pl.col("padd1_total_kbd"))
                .otherwise(zero_total_padd1ab_share)
                .alias("padd1ab_share"),
                pl.when(pl.col("padd1_total_kbd") > 0)
                .then(pl.col("padd1c_kbd") / pl.col("padd1_total_kbd"))
                .otherwise(0.0)
                .alias("padd1c_share"),
            ]
        )
        .sort([date_column, "commodity", "flow_direction"], descending=[True, False, False])
    )


def build_share_outputs(long_rows: pl.DataFrame, assume_padd1ab: bool = False) -> dict[str, str]:
    config = runtime_config()
    PADD1_SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    rows = long_rows.filter(pl.col("family") == "padd1_split")
    if rows.is_empty():
        raise RuntimeError("Kpler PADD 1 split returned no rows.")
    groups = []
    for row in rows.iter_rows(named=True):
        padd_value = row["destination_padd"] if row["flow_direction"] == "import" else row["origin_padd"]
        groups.append(padd1_group(padd_value))
    rows = rows.with_columns(pl.Series("padd1_group", groups)).filter(pl.col("padd1_group") != "")
    if rows.is_empty():
        raise RuntimeError("Kpler rows were pulled, but no PADD 1A/B/1C split rows were found.")

    outputs: dict[str, str] = {}
    all_daily: list[pl.DataFrame] = []
    for commodity in COMMODITIES:
        for direction in ["import", "export"]:
            subset = rows.filter((pl.col("commodity") == commodity) & (pl.col("flow_direction") == direction))
            grouped = (
                subset.group_by(["date", "padd1_group"]).agg(pl.col("value_kbd").sum())
                if subset.height
                else pl.DataFrame({"date": [], "padd1_group": [], "value_kbd": []})
            )
            pivot = (
                grouped.pivot(index="date", on="padd1_group", values="value_kbd", aggregate_function="sum")
                if grouped.height
                else pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
            )
            for column in ["padd1ab", "padd1c", "padd1_other"]:
                if column not in pivot.columns:
                    pivot = pivot.with_columns(pl.lit(0.0).alias(column))
            daily = pivot.rename(
                {"padd1ab": "padd1ab_kbd", "padd1c": "padd1c_kbd", "padd1_other": "padd1_other_kbd"}
            ).select(["date", "padd1ab_kbd", "padd1c_kbd", "padd1_other_kbd"])
            daily = complete_daily(daily, config.start_date, config.end_date, {"commodity": commodity, "flow_direction": direction})
            daily = add_shares(daily, "date", assume_padd1ab=assume_padd1ab).select(
                [
                    "date",
                    "commodity",
                    "flow_direction",
                    "padd1ab_kbd",
                    "padd1c_kbd",
                    "padd1_other_kbd",
                    "padd1_total_kbd",
                    "padd1ab_share",
                    "padd1c_share",
                ]
            )
            all_daily.append(daily)

    daily = pl.concat(all_daily, how="vertical")
    weekly = daily.with_columns(week_ending_expr("date").alias("week_ending"))
    counts = weekly.group_by(["week_ending", "commodity", "flow_direction"]).agg(pl.len().alias("_days"))
    weekly = (
        weekly.join(counts, on=["week_ending", "commodity", "flow_direction"])
        .filter(pl.col("_days") == 7)
        .drop("_days")
    )
    weekly = share_frame_for_period(weekly, "week_ending", assume_padd1ab=assume_padd1ab).select(
        ["week_ending", "commodity", "flow_direction", "padd1ab_kbd", "padd1c_kbd", "padd1_other_kbd", "padd1_total_kbd", "padd1ab_share", "padd1c_share"]
    )
    monthly = daily.with_columns(monthly_expr("date").alias("month"))
    monthly = share_frame_for_period(monthly, "month", assume_padd1ab=assume_padd1ab).select(
        ["month", "commodity", "flow_direction", "padd1ab_kbd", "padd1c_kbd", "padd1_other_kbd", "padd1_total_kbd", "padd1ab_share", "padd1c_share"]
    )

    for name, frame in [("daily", daily), ("weekly", weekly), ("monthly", monthly)]:
        path = PADD1_SPLIT_DIR / f"padd1_import_export_shares_{name}.csv"
        frame.write_csv(path)
        outputs[name] = str(path)
    return outputs


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def as_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def clean_suffix(column: str) -> str:
    text = re.sub(r"^weekly\s+", "", column, flags=re.IGNORECASE)
    text = text.replace("East Coast (PADD 1) ", "")
    text = re.sub(r"\s*\(Thousand Barrels per Day\)\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_aggregate_trade_column(column: str, flow: str) -> bool:
    lower = column.lower()
    if "east coast (padd 1)" not in lower:
        return False
    if flow == "import" and "imports" not in lower:
        return False
    if flow == "export" and "exports" not in lower:
        return False
    if flow == "import":
        if " from " in lower and "all countries" not in lower:
            return False
    if flow == "export":
        if re.search(r"\bexports?\s+to\b", lower):
            return False
    return True


def load_share_lookup(path: Path, date_column: str) -> dict[tuple[str, str, str], tuple[float, float]]:
    lookup: dict[tuple[str, str, str], tuple[float, float]] = {}
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            lookup[(row[date_column], row["commodity"], row["flow_direction"])] = (
                as_float(row["padd1ab_share"]),
                as_float(row["padd1c_share"]),
            )
    return lookup


def month_start(value: str) -> str:
    if not value:
        return ""
    parsed = datetime.strptime(value[:10], "%Y-%m-%d").date()
    return parsed.replace(day=1).isoformat()


def remove_old_kpler_columns(fieldnames: list[str], rows: list[dict[str, str]]) -> list[str]:
    drop = {
        column
        for column in fieldnames
        if column.startswith("Kpler PADD 1A/B Share of PADD 1 ")
        or column.startswith("Kpler PADD 1C Share of PADD 1 ")
        or (column.startswith("Estimated PADD 1A/B ") and column.endswith(" (Kpler Split)"))
        or (column.startswith("Estimated PADD 1C ") and column.endswith(" (Kpler Split)"))
    }
    if not drop:
        return fieldnames
    for row in rows:
        for column in drop:
            row.pop(column, None)
    return [column for column in fieldnames if column not in drop]


def merge_one_eia_file(path: Path, commodity: str, frequency: str, shares: dict[tuple[str, str, str], tuple[float, float]]) -> dict[str, Any]:
    fieldnames, rows = read_csv(path)
    if not fieldnames:
        return {"path": str(path), "rows": 0, "added_columns": 0, "split_source_columns": []}
    date_col = fieldnames[0]
    fieldnames = remove_old_kpler_columns(fieldnames, rows)
    source_columns: list[tuple[str, str]] = []
    for column in fieldnames:
        for flow in ["import", "export"]:
            if is_aggregate_trade_column(column, flow):
                source_columns.append((column, flow))

    additions: list[str] = []
    for flow, columns in SHARE_COLUMNS.items():
        if any(source_flow == flow for _, source_flow in source_columns):
            additions.extend(columns)
    estimate_columns: dict[str, tuple[str, str, str]] = {}
    for source, flow in source_columns:
        suffix = clean_suffix(source)
        for region, label in [("padd1ab", "PADD 1A/B"), ("padd1c", "PADD 1C")]:
            column = f"Estimated {label} {suffix} (Kpler Split)"
            additions.append(column)
            estimate_columns[column] = (source, flow, region)

    new_fieldnames = [date_col, *additions, *[column for column in fieldnames if column != date_col]]
    for row in rows:
        period = row.get(date_col, "")
        key_period = month_start(period) if frequency == "monthly" else period
        for flow in ["import", "export"]:
            ab_share, c_share = shares.get((key_period, commodity, flow), (0.0, 0.0))
            if any(source_flow == flow for _, source_flow in source_columns):
                row[SHARE_COLUMNS[flow][0]] = f"{ab_share:.8f}"
                row[SHARE_COLUMNS[flow][1]] = f"{c_share:.8f}"
        for column, (source, flow, region) in estimate_columns.items():
            ab_share, c_share = shares.get((key_period, commodity, flow), (0.0, 0.0))
            share = ab_share if region == "padd1ab" else c_share
            row[column] = f"{as_float(row.get(source, 0.0)) * share:.6f}"
    rows.sort(key=lambda item: item.get(date_col, ""), reverse=True)
    write_csv(path, new_fieldnames, rows)
    return {
        "path": str(path),
        "rows": len(rows),
        "date_column": date_col,
        "latest": rows[0].get(date_col, "") if rows else "",
        "oldest": rows[-1].get(date_col, "") if rows else "",
        "added_columns": len(additions),
        "split_source_columns": [column for column, _ in source_columns],
    }


def merge_eia_outputs(share_outputs: dict[str, str]) -> list[dict[str, Any]]:
    weekly_shares = load_share_lookup(Path(share_outputs["weekly"]), "week_ending")
    monthly_shares = load_share_lookup(Path(share_outputs["monthly"]), "month")
    results: list[dict[str, Any]] = []
    for commodity, meta in COMMODITIES.items():
        results.append(merge_one_eia_file(Path(meta["monthly"]), commodity, "monthly", monthly_shares))
        results.append(merge_one_eia_file(Path(meta["weekly"]), commodity, "weekly", weekly_shares))
    return results


def run(args: argparse.Namespace) -> int:
    ensure_directories()
    PADD1_SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    PADD1_RAW_DIR.mkdir(parents=True, exist_ok=True)
    config = runtime_config()
    specs = build_padd1_specs()
    if args.preflight:
        write_json(
            PADD1_MANIFEST,
            {
                "pipeline_name": "kpler_padd1_eia_split",
                "mode": "preflight",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "runtime_config": {
                    **asdict(config),
                    "start_date": config.start_date.isoformat(),
                    "end_date": config.end_date.isoformat(),
                    "snapshot_date": config.snapshot_date.isoformat() if config.snapshot_date else "",
                },
                "pull_count": len(specs),
                "pulls": [spec.manifest_dict() for spec in specs],
            },
        )
        print(f"kpler padd1 preflight pull_specs={len(specs)} manifest={PADD1_MANIFEST}")
        return 0

    mode = "existing_raw" if args.use_existing_raw else "live" if has_kpler_credentials() else "eia_fallback"
    long_rows, pull_status = pull_kpler_long(specs, use_existing_raw=args.use_existing_raw)
    normalized_path = PADD1_SPLIT_DIR / "padd1_import_export_normalized_long.csv"
    long_rows.write_csv(normalized_path)
    share_outputs = build_share_outputs(long_rows, assume_padd1ab=mode == "eia_fallback")
    merge_results = merge_eia_outputs(share_outputs)
    write_json(
        PADD1_MANIFEST,
        {
            "pipeline_name": "kpler_padd1_eia_split",
            "mode": mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "runtime_config": {
                **asdict(config),
                "start_date": config.start_date.isoformat(),
                "end_date": config.end_date.isoformat(),
                "snapshot_date": config.snapshot_date.isoformat() if config.snapshot_date else "",
            },
            "pull_count": len(specs),
            "pulls": [spec.manifest_dict() for spec in specs],
            "pull_status": pull_status,
            "normalized_long": {"path": str(normalized_path), "rows": int(long_rows.height)},
            "share_outputs": share_outputs,
            "eia_merge_results": merge_results,
        },
    )
    for result in merge_results:
        print(
            f"{result['path']} rows={result['rows']} added_columns={result['added_columns']} "
            f"latest={result['latest']} oldest={result['oldest']} split_sources={len(result['split_source_columns'])}"
        )
    print(f"kpler padd1 eia split manifest={PADD1_MANIFEST}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Kpler PADD 1 import/export shares and merge them into EIA files.")
    parser.add_argument("--preflight", action="store_true", help="Write the dynamic pull plan without calling Kpler.")
    parser.add_argument("--use-existing-raw", action="store_true", help="Build shares from existing Kpler raw CSVs without calling Kpler.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(sys.argv[1:] if argv is None else argv))
    except RuntimeError as exc:
        print(f"kpler padd1 error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
