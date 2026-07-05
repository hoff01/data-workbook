from __future__ import annotations

from datetime import date
from io import BytesIO
import hashlib
import re
from pathlib import Path
from typing import Any

import polars as pl

from kpler_config import CONFIG_DIR, OUTPUT_DIR, PullSpec, load_yaml


LONG_COLUMNS = [
    "date",
    "pull_set",
    "family",
    "geography",
    "commodity",
    "kpler_product",
    "flow_direction",
    "origin_country",
    "destination_country",
    "origin_trading_region",
    "destination_trading_region",
    "origin_padd",
    "destination_padd",
    "region_detail",
    "balance_group",
    "route_group",
    "unit",
    "value_kbd",
    "with_intra_country",
    "with_intra_region",
    "with_forecast",
    "only_realized",
    "snapshot_date",
    "source_hash",
]

US_GROUPS = ["canada", "latin_america", "europe", "asia", "middle_east", "africa", "other"]
EUROPE_REGIONS = ["nwe", "med", "other_europe"]
DOMESTIC_ROUTES = ["padd3_to_padd1ab", "padd3_to_padd1c", "padd3_to_padd5"]
PADD1_IMPORT_GUIDE_REGIONS = ["padd1ab", "padd1c"]
PADD1_IMPORT_GUIDE_DESTINATIONS = {
    "padd1ab": ["PADD1A", "PADDIA", "NEWENGLAND", "PADD1B", "PADDIB", "CENTRALATLANTIC"],
    "padd1c": ["PADD1C", "PADDIC", "LOWERATLANTIC"],
}
BALANCE_GUIDE_FREQUENCIES = {
    "weekly": ("week_ending", "weekly"),
    "monthly": ("month", "monthly"),
}
PADD_MATCHES = {
    "padd1ab": ["PADD1A", "PADDIA", "NEWENGLAND", "PADD1B", "PADDIB", "CENTRALATLANTIC"],
    "padd1c": ["PADD1C", "PADDIC", "LOWERATLANTIC"],
    "padd1": ["PADD1", "PADDI", "EASTCOAST"],
    "padd2": ["PADD2", "PADDII", "MIDWEST"],
    "padd3": ["PADD3", "PADDIII", "GULFCOAST"],
    "padd4": ["PADD4", "PADDIV", "ROCKYMOUNTAIN"],
    "padd5": ["PADD5", "PADDV", "WESTCOAST"],
}


def empty_long() -> pl.DataFrame:
    return pl.DataFrame({column: [] for column in LONG_COLUMNS})


def clean_name(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    text = text.replace("\n", " ")
    return re.sub(r"\s+", " ", text)


def snake(value: str) -> str:
    text = value.strip().lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def compact_name(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", clean_name(value).upper())


def split_header(value: str) -> list[str]:
    text = clean_name(value)
    for delimiter in [" | ", "|", " > ", " :: ", " -- "]:
        if delimiter in text:
            return [part.strip() for part in text.split(delimiter)]
    return [text]


def split_to_column(split_name: str) -> str:
    return {
        "origin countries": "origin_country",
        "destination countries": "destination_country",
        "origin trading regions": "origin_trading_region",
        "destination trading regions": "destination_trading_region",
        "origin padds": "origin_padd",
        "destination padds": "destination_padd",
        "products": "kpler_product",
    }.get(split_name, snake(split_name))


def raw_csv_to_frame(content: bytes) -> pl.DataFrame:
    if not content:
        return pl.DataFrame()
    return pl.read_csv(BytesIO(content), separator=";", infer_schema_length=2000, ignore_errors=True)


def date_column(frame: pl.DataFrame) -> str | None:
    for column in frame.columns:
        if column.lower() in {"date", "day", "period", "time", "timestamp"}:
            return column
    return frame.columns[0] if frame.columns else None


def value_column(frame: pl.DataFrame) -> str | None:
    for column in frame.columns:
        if column.lower() in {"value", "value_kbd", "kbd", "flow", "flows"}:
            return column
    return None


def normalized_date_expr(column: str) -> pl.Expr:
    raw = pl.col(column).cast(pl.Utf8)
    normalized = pl.when(raw.str.contains(r"^\d{4}-\d{2}$")).then(pl.concat_str([raw, pl.lit("-01")])).otherwise(raw)
    return normalized.cast(pl.Date, strict=False).cast(pl.Utf8).alias("date")


def kpler_content_to_long(content: bytes, spec: PullSpec) -> pl.DataFrame:
    frame = raw_csv_to_frame(content)
    if frame.is_empty():
        return empty_long()
    source_hash = hashlib.sha256(content).hexdigest()
    dcol = date_column(frame)
    vcol = value_column(frame)
    if not dcol:
        return empty_long()
    if vcol:
        return long_like_to_long(frame, spec, source_hash, dcol, vcol)
    return wide_to_long(frame, spec, source_hash, dcol)


def base_literals(spec: PullSpec, source_hash: str) -> list[pl.Expr]:
    return [
        pl.lit(spec.name).alias("pull_set"),
        pl.lit(spec.family).alias("family"),
        pl.lit(spec.geography).alias("geography"),
        pl.lit(spec.commodity).alias("commodity"),
        pl.lit(spec.kpler_product).alias("kpler_product"),
        pl.lit(spec.flow_direction).alias("flow_direction"),
        pl.lit("").alias("origin_country"),
        pl.lit("").alias("destination_country"),
        pl.lit("").alias("origin_trading_region"),
        pl.lit("").alias("destination_trading_region"),
        pl.lit("").alias("origin_padd"),
        pl.lit("").alias("destination_padd"),
        pl.lit(spec.region_detail).alias("region_detail"),
        pl.lit("").alias("balance_group"),
        pl.lit(spec.route_group).alias("route_group"),
        pl.lit(spec.unit).alias("unit"),
        pl.lit(spec.with_intra_country).alias("with_intra_country"),
        pl.lit(spec.with_intra_region).alias("with_intra_region"),
        pl.lit(spec.with_forecast).alias("with_forecast"),
        pl.lit(spec.only_realized).alias("only_realized"),
        pl.lit("").alias("snapshot_date"),
        pl.lit(source_hash).alias("source_hash"),
    ]


def long_like_to_long(frame: pl.DataFrame, spec: PullSpec, source_hash: str, dcol: str, vcol: str) -> pl.DataFrame:
    expressions = [
        normalized_date_expr(dcol),
        pl.col(vcol).cast(pl.Float64, strict=False).alias("value_kbd"),
        *base_literals(spec, source_hash),
    ]
    out = frame.select(expressions)
    for split_name in spec.split:
        target = split_to_column(split_name)
        candidates = [target, split_name, split_name.replace(" ", "_"), split_name.title(), split_name.upper()]
        for candidate in candidates:
            if candidate in frame.columns:
                out = out.with_columns(pl.Series(target, frame[candidate].cast(pl.Utf8).fill_null("")))
                break
    return out.select(LONG_COLUMNS)


def wide_to_long(frame: pl.DataFrame, spec: PullSpec, source_hash: str, dcol: str) -> pl.DataFrame:
    value_columns = [column for column in frame.columns if column != dcol]
    if not value_columns:
        return empty_long()
    melted = frame.unpivot(index=dcol, on=value_columns, variable_name="dynamic_column", value_name="value_kbd")
    split_targets = [split_to_column(name) for name in spec.split]
    out = melted.select(
        [
            normalized_date_expr(dcol),
            pl.col("dynamic_column").cast(pl.Utf8),
            pl.col("value_kbd").cast(pl.Float64, strict=False),
            *base_literals(spec, source_hash),
        ]
    ).filter(pl.col("value_kbd").is_not_null())

    # Kpler dynamic CSV headers vary by split count. If a header cannot be
    # decomposed, assign it to the first requested split so totals still land in
    # the correct balance bucket where possible.
    parts = [split_header(column) for column in out["dynamic_column"].to_list()]
    updates = {target: [] for target in split_targets}
    for column_parts in parts:
        for idx, target in enumerate(split_targets):
            updates[target].append(column_parts[idx] if idx < len(column_parts) else "")
    for target, values in updates.items():
        out = out.with_columns(pl.Series(target, values))
    return out.drop("dynamic_column").select(LONG_COLUMNS)


def load_region_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "regions.yml")


def _members(config: dict[str, Any], key: str) -> set[str]:
    return {clean_name(value) for value in config.get(key, [])}


def classify_us_group(country: str, trading_region: str, regions: dict[str, Any]) -> str:
    country = clean_name(country)
    trading_region = clean_name(trading_region)
    for group, config in regions["us_trade_groups"].items():
        if country and country in _members(config, "countries"):
            return group
        if trading_region and trading_region in _members(config, "trading_regions"):
            return group
    return "other"


def add_us_balance_group(rows: pl.DataFrame) -> pl.DataFrame:
    regions = load_region_config()
    groups = []
    for row in rows.iter_rows(named=True):
        if row["flow_direction"] == "import":
            groups.append(classify_us_group(row.get("origin_country", ""), row.get("origin_trading_region", ""), regions))
        else:
            groups.append(classify_us_group(row.get("destination_country", ""), row.get("destination_trading_region", ""), regions))
    return rows.with_columns(pl.Series("balance_group", groups))


def classify_domestic_route(origin: str, destination: str, regions: dict[str, Any]) -> str:
    origin = clean_name(origin)
    destination = clean_name(destination)
    for route, config in regions["domestic_padd_routes"].items():
        if origin in _members(config, "origin_padds") and destination in _members(config, "destination_padds"):
            return route
    return ""


def add_domestic_route(rows: pl.DataFrame) -> pl.DataFrame:
    regions = load_region_config()
    routes = [
        classify_domestic_route(row.get("origin_padd", ""), row.get("destination_padd", ""), regions)
        for row in rows.iter_rows(named=True)
    ]
    return rows.with_columns(pl.Series("route_group", routes))


def date_calendar(start_date: date, end_date: date) -> pl.DataFrame:
    return pl.DataFrame({"date": pl.date_range(start_date, end_date, interval="1d", eager=True).cast(pl.Utf8)})


def complete_daily(frame: pl.DataFrame, start_date: date, end_date: date, fixed: dict[str, str]) -> pl.DataFrame:
    calendar = date_calendar(start_date, end_date)
    merged = calendar.join(frame, on="date", how="left")
    for key, value in fixed.items():
        merged = merged.with_columns(pl.lit(value).alias(key))
    for column in [column for column in merged.columns if column.endswith("_kbd")]:
        merged = merged.with_columns(pl.col(column).cast(pl.Float64, strict=False).fill_null(0.0).alias(column))
    return merged


def weekly_average(daily: pl.DataFrame) -> pl.DataFrame:
    numeric_columns = [column for column in daily.columns if column.endswith("_kbd")]
    fixed_columns = [column for column in daily.columns if column not in numeric_columns + ["date"]]
    frame = daily.with_columns(
        [
            pl.col("date").cast(pl.Date).alias("_date"),
            (pl.col("date").cast(pl.Date) + pl.duration(days=((5 - pl.col("date").cast(pl.Date).dt.weekday()) % 7))).alias("week_ending"),
        ]
    )
    frame = frame.with_columns(pl.col("week_ending").cast(pl.Utf8))
    counts = frame.group_by("week_ending").agg(pl.len().alias("_day_count"))
    frame = frame.join(counts, on="week_ending").filter(pl.col("_day_count") == 7)
    aggregations = [pl.col(column).mean().alias(column) for column in numeric_columns]
    aggregations.extend(pl.col(column).first().alias(column) for column in fixed_columns)
    return frame.group_by("week_ending").agg(aggregations).sort("week_ending").select(["week_ending", *fixed_columns, *numeric_columns])


def monthly_average(daily: pl.DataFrame) -> pl.DataFrame:
    numeric_columns = [column for column in daily.columns if column.endswith("_kbd")]
    fixed_columns = [column for column in daily.columns if column not in numeric_columns + ["date"]]
    frame = daily.with_columns(pl.col("date").cast(pl.Date).dt.truncate("1mo").cast(pl.Utf8).alias("month"))
    aggregations = [pl.col(column).mean().alias(column) for column in numeric_columns]
    aggregations.extend(pl.col(column).first().alias(column) for column in fixed_columns)
    return frame.group_by("month").agg(aggregations).sort("month").select(["month", *fixed_columns, *numeric_columns])


def ensure_columns(frame: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    out = frame
    for column in columns:
        if column not in out.columns:
            out = out.with_columns(pl.lit(0.0 if column.endswith("_kbd") else "").alias(column))
    return out.select(columns)


def add_missing_columns(frame: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    out = frame
    for column in columns:
        if column not in out.columns:
            out = out.with_columns(pl.lit(0.0 if column.endswith("_kbd") else "").alias(column))
    return out


def write_output_set(name: str, daily: pl.DataFrame) -> dict[str, Any]:
    daily_path = OUTPUT_DIR / "daily" / f"{name}_daily.csv"
    weekly_path = OUTPUT_DIR / "weekly" / f"{name}_weekly.csv"
    monthly_path = OUTPUT_DIR / "monthly" / f"{name}_monthly.csv"
    daily.write_csv(daily_path)
    weekly = weekly_average(daily)
    monthly = monthly_average(daily)
    weekly.write_csv(weekly_path)
    monthly.write_csv(monthly_path)
    dates = daily["date"].to_list() if "date" in daily.columns and daily.height else []
    return {
        "daily_path": str(daily_path),
        "weekly_path": str(weekly_path),
        "monthly_path": str(monthly_path),
        "daily_rows": int(daily.height),
        "weekly_rows": int(weekly.height),
        "monthly_rows": int(monthly.height),
        "min_date": min(dates) if dates else "",
        "max_date": max(dates) if dates else "",
    }


def build_us_external_outputs(long_rows: pl.DataFrame, start_date: date, end_date: date) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    schema = load_yaml(CONFIG_DIR / "output_schema.yml")["us_external_columns"]
    rows = long_rows.filter((pl.col("family") == "external") & (pl.col("geography") == "us"))
    if rows.height:
        rows = add_us_balance_group(rows)
    for commodity in ["diesel", "jet", "gasoline"]:
        commodity_rows = rows.filter(pl.col("commodity") == commodity)
        daily = pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
        for flow, direction in [("imports", "import"), ("exports", "export")]:
            flow_rows = commodity_rows.filter(pl.col("flow_direction") == direction)
            total = flow_rows.group_by("date").agg(pl.col("value_kbd").sum().alias(f"{flow}_total_kbd")) if flow_rows.height else pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
            daily = total if daily.is_empty() else daily.join(total, on="date", how="outer", coalesce=True)
            grouped = flow_rows.group_by(["date", "balance_group"]).agg(pl.col("value_kbd").sum()) if flow_rows.height else pl.DataFrame({"date": [], "balance_group": [], "value_kbd": []})
            pivot = grouped.pivot(index="date", columns="balance_group", values="value_kbd", aggregate_function="sum") if grouped.height else pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
            rename = {group: f"{flow}_{group}_kbd" for group in US_GROUPS if group in pivot.columns}
            pivot = pivot.rename(rename)
            keep = ["date", *[f"{flow}_{group}_kbd" for group in US_GROUPS]]
            pivot = ensure_columns(pivot, keep)
            daily = daily.join(pivot, on="date", how="outer", coalesce=True) if not daily.is_empty() else pivot
        daily = ensure_columns(daily, schema[:-2])
        daily = daily.with_columns(
            [
                (pl.col("imports_total_kbd") - pl.col("exports_total_kbd")).alias("net_imports_kbd"),
                (pl.col("exports_total_kbd") - pl.col("imports_total_kbd")).alias("net_exports_kbd"),
            ]
        )
        daily = complete_daily(daily, start_date, end_date, {"commodity": commodity})
        outputs[f"us_{commodity}"] = write_output_set(f"us_{commodity}", ensure_columns(daily, schema))
    return outputs


def build_europe_external_outputs(long_rows: pl.DataFrame, start_date: date, end_date: date) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    schema = load_yaml(CONFIG_DIR / "output_schema.yml")["europe_external_columns"]
    rows = long_rows.filter((pl.col("family") == "external") & (pl.col("geography") == "europe"))
    for commodity in ["diesel", "jet", "gasoline"]:
        commodity_rows = rows.filter(pl.col("commodity") == commodity)
        daily = pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
        for region in EUROPE_REGIONS:
            region_rows = commodity_rows.filter(pl.col("region_detail") == region)
            for flow, direction in [("imports", "import"), ("exports", "export")]:
                subset = region_rows.filter(pl.col("flow_direction") == direction)
                col = f"{region}_{flow}_total_kbd"
                total = subset.group_by("date").agg(pl.col("value_kbd").sum().alias(col)) if subset.height else pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
                daily = total if daily.is_empty() else daily.join(total, on="date", how="outer", coalesce=True)
            daily = ensure_columns(daily, ["date", f"{region}_imports_total_kbd", f"{region}_exports_total_kbd"])
            daily = daily.with_columns(
                [
                    (pl.col(f"{region}_imports_total_kbd") - pl.col(f"{region}_exports_total_kbd")).alias(f"{region}_net_imports_kbd"),
                    (pl.col(f"{region}_exports_total_kbd") - pl.col(f"{region}_imports_total_kbd")).alias(f"{region}_net_exports_kbd"),
                ]
            )
        daily = ensure_columns(daily, [column for column in schema if column not in {"commodity", "europe_imports_total_kbd", "europe_exports_total_kbd", "europe_net_imports_kbd", "europe_net_exports_kbd"}])
        daily = daily.with_columns(
            [
                sum(pl.col(f"{region}_imports_total_kbd") for region in EUROPE_REGIONS).alias("europe_imports_total_kbd"),
                sum(pl.col(f"{region}_exports_total_kbd") for region in EUROPE_REGIONS).alias("europe_exports_total_kbd"),
            ]
        ).with_columns(
            [
                (pl.col("europe_imports_total_kbd") - pl.col("europe_exports_total_kbd")).alias("europe_net_imports_kbd"),
                (pl.col("europe_exports_total_kbd") - pl.col("europe_imports_total_kbd")).alias("europe_net_exports_kbd"),
            ]
        )
        daily = complete_daily(daily, start_date, end_date, {"commodity": commodity})
        outputs[f"europe_{commodity}"] = write_output_set(f"europe_{commodity}", ensure_columns(daily, schema))
    return outputs


def build_domestic_padd_outputs(long_rows: pl.DataFrame, start_date: date, end_date: date) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    schema = load_yaml(CONFIG_DIR / "output_schema.yml")["domestic_padd_columns"]
    rows = long_rows.filter(pl.col("family") == "domestic_padd")
    if rows.height:
        rows = add_domestic_route(rows).filter(pl.col("route_group") != "")
    all_daily: list[pl.DataFrame] = []
    for commodity in ["diesel", "jet", "gasoline"]:
        commodity_rows = rows.filter(pl.col("commodity") == commodity)
        grouped = commodity_rows.group_by(["date", "route_group"]).agg(pl.col("value_kbd").sum()) if commodity_rows.height else pl.DataFrame({"date": [], "route_group": [], "value_kbd": []})
        daily = grouped.pivot(index="date", columns="route_group", values="value_kbd", aggregate_function="sum") if grouped.height else pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
        daily = daily.rename({route: f"{route}_kbd" for route in DOMESTIC_ROUTES if route in daily.columns})
        daily = ensure_columns(daily, ["date", *[f"{route}_kbd" for route in DOMESTIC_ROUTES]])
        daily = daily.with_columns(sum(pl.col(f"{route}_kbd") for route in DOMESTIC_ROUTES).alias("padd3_total_selected_kbd"))
        daily = complete_daily(daily, start_date, end_date, {"commodity": commodity})
        daily = ensure_columns(daily, schema)
        all_daily.append(daily)
        outputs[f"us_{commodity}_padd_movements"] = write_output_set(f"us_{commodity}_padd_movements", daily)
    combined = pl.concat(all_daily, how="vertical") if all_daily else pl.DataFrame({column: [] for column in schema})
    outputs["us_padd_movements"] = write_output_set("us_padd_movements", combined)
    return outputs


def country_total(rows: pl.DataFrame, country: str, alias: str) -> pl.DataFrame:
    countries = [country]
    if country == "United States":
        countries.extend(["United States of America", "USA"])
    subset = rows.filter(pl.col("origin_country").is_in(countries))
    return subset.group_by("date").agg(pl.col("value_kbd").sum().alias(alias)) if subset.height else pl.DataFrame({"date": []}, schema={"date": pl.Utf8})


def flow_total(rows: pl.DataFrame, alias: str) -> pl.DataFrame:
    return rows.group_by("date").agg(pl.col("value_kbd").sum().alias(alias)) if rows.height else pl.DataFrame({"date": []}, schema={"date": pl.Utf8})


def join_daily_frame(daily: pl.DataFrame, frame: pl.DataFrame) -> pl.DataFrame:
    if daily.is_empty():
        return frame
    return daily.join(frame, on="date", how="outer", coalesce=True)


def filter_padd1_import_destination(rows: pl.DataFrame, region: str) -> pl.DataFrame:
    if rows.is_empty():
        return rows
    targets = PADD1_IMPORT_GUIDE_DESTINATIONS[region]
    matches = [any(target in compact_name(value) for target in targets) for value in rows["destination_padd"].to_list()]
    return rows.with_columns(pl.Series("_destination_match", matches)).filter(pl.col("_destination_match")).drop("_destination_match")


def build_padd1_import_guide_outputs(long_rows: pl.DataFrame, start_date: date, end_date: date) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    schema = load_yaml(CONFIG_DIR / "output_schema.yml")["padd1_import_guide_columns"]
    rows = long_rows.filter(pl.col("family") == "padd1_import_guides")
    if rows.is_empty():
        return outputs
    commodities = sorted(rows.select("commodity").unique().to_series().to_list())
    for commodity in commodities:
        commodity_rows = rows.filter(pl.col("commodity") == commodity)
        daily = pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
        for region in PADD1_IMPORT_GUIDE_REGIONS:
            region_rows = filter_padd1_import_destination(commodity_rows.filter(pl.col("region_detail") == region), region)
            total_col = f"{region}_imports_total_kbd"
            canada_col = f"{region}_imports_canada_kbd"
            non_canada_col = f"{region}_imports_non_canada_kbd"
            intra_us_col = f"{region}_imports_intra_us_kbd"
            daily = join_daily_frame(daily, flow_total(region_rows, total_col))
            daily = join_daily_frame(daily, country_total(region_rows, "Canada", canada_col))
            daily = join_daily_frame(daily, country_total(region_rows, "United States", intra_us_col))
            daily = add_missing_columns(daily, ["date", total_col, canada_col, intra_us_col])
            daily = daily.with_columns(
                pl.when((pl.col(total_col) - pl.col(canada_col)) > 0)
                .then(pl.col(total_col) - pl.col(canada_col))
                .otherwise(0.0)
                .alias(non_canada_col)
            )
        daily = complete_daily(daily, start_date, end_date, {"commodity": commodity})
        outputs[f"us_{commodity}_padd1_import_guides"] = write_output_set(
            f"us_{commodity}_padd1_import_guides",
            ensure_columns(daily, schema),
        )
    return outputs


def padd_group(value: Any) -> str:
    text = compact_name(value)
    if not text:
        return ""
    for group in ["padd1ab", "padd1c", "padd2", "padd3", "padd4", "padd5"]:
        if any(token in text for token in PADD_MATCHES[group]):
            return group
    if any(token in text for token in PADD_MATCHES["padd1"]):
        return "padd1"
    return ""


def is_padd1(group: str) -> bool:
    return group in {"padd1", "padd1ab", "padd1c"}


def is_canada(country: Any) -> bool:
    return clean_name(country).lower() == "canada"


def is_united_states(country: Any) -> bool:
    return clean_name(country).lower() in {"united states", "united states of america", "usa"}


def balance_destination_group(row: dict[str, Any], regions: dict[str, Any]) -> str:
    return classify_us_group(row.get("destination_country", ""), row.get("destination_trading_region", ""), regions)


def add_balance_value(summary: dict[str, dict[str, float]], period: str, column: str, value: float) -> None:
    if not period or not column or not value:
        return
    bucket = summary.setdefault(period, {})
    bucket[column] = float(bucket.get(column, 0.0)) + float(value)


def guide_period(value: Any, frequency: str) -> str:
    text = clean_name(value)
    if not text:
        return ""
    return text[:10] if frequency == "weekly" else text[:7]


def derive_balance_guide_columns(values: dict[str, float]) -> None:
    for prefix in ["padd1", "padd1ab", "padd1c", "us"]:
        total_col = f"{prefix}_imports_total_kbd"
        canada_col = f"{prefix}_imports_canada_kbd"
        non_canada_col = f"{prefix}_imports_non_canada_kbd"
        if total_col in values or canada_col in values:
            values[non_canada_col] = max(0.0, values.get(total_col, 0.0) - values.get(canada_col, 0.0))
    values["padd1ab_exports_other_kbd"] = max(
        0.0,
        values.get("padd1ab_exports_total_kbd", 0.0) - values.get("padd1ab_exports_europe_kbd", 0.0),
    )
    values["padd3_exports_other_kbd"] = max(
        0.0,
        values.get("padd3_exports_total_kbd", 0.0)
        - values.get("padd3_exports_africa_kbd", 0.0)
        - values.get("padd3_exports_europe_kbd", 0.0)
        - values.get("padd3_exports_latin_america_kbd", 0.0),
    )


def balance_guide_frame(
    rows: pl.DataFrame,
    commodity: str,
    frequency: str,
    period_column: str,
    schema: list[str],
) -> pl.DataFrame:
    regions = load_region_config()
    summary: dict[str, dict[str, float]] = {}
    subset = rows.filter((pl.col("commodity") == commodity) & (pl.col("region_detail") == frequency))
    for row in subset.iter_rows(named=True):
        route = row.get("route_group", "")
        period = guide_period(row.get("date", ""), frequency)
        value = float(row.get("value_kbd") or 0.0)
        origin_group = padd_group(row.get("origin_padd", ""))
        destination_group = padd_group(row.get("destination_padd", ""))
        destination_trade_group = balance_destination_group(row, regions)
        origin_country = row.get("origin_country", "")

        if route in {"diesel_padd1ab_imports_external", "padd1_imports_external"} and commodity == "diesel":
            add_balance_value(summary, period, "padd1ab_imports_total_kbd", value)
            if is_canada(origin_country):
                add_balance_value(summary, period, "padd1ab_imports_canada_kbd", value)

        elif route in {"jet_padd1_imports_external", "padd1_imports_external"} and commodity == "jet":
            add_balance_value(summary, period, "padd1_imports_total_kbd", value)
            if is_canada(origin_country):
                add_balance_value(summary, period, "padd1_imports_canada_kbd", value)

        elif route in {"diesel_padd1c_imports_intracountry", "padd1c_imports_intracountry"} and commodity == "diesel":
            add_balance_value(summary, period, "padd1c_imports_total_kbd", value)
            if is_canada(origin_country):
                add_balance_value(summary, period, "padd1c_imports_canada_kbd", value)
            if is_united_states(origin_country):
                add_balance_value(summary, period, "padd1c_imports_intra_us_kbd", value)

        elif route in {"diesel_padd1ab_exports_external", "padd1_exports_external"} and commodity == "diesel":
            add_balance_value(summary, period, "padd1ab_exports_total_kbd", value)
            if destination_trade_group == "europe":
                add_balance_value(summary, period, "padd1ab_exports_europe_kbd", value)

        elif route in {"diesel_padd1c_exports_external", "padd1_exports_external"} and commodity == "diesel":
            add_balance_value(summary, period, "padd1c_exports_total_kbd", value)

        elif route in {"jet_padd1_exports_external", "padd1_exports_external"} and commodity == "jet":
            add_balance_value(summary, period, "padd1_exports_total_kbd", value)

        elif route == "padd3_exports_external":
            add_balance_value(summary, period, "padd3_exports_total_kbd", value)
            if destination_trade_group in {"africa", "europe", "latin_america"}:
                add_balance_value(summary, period, f"padd3_exports_{destination_trade_group}_kbd", value)

        elif route == "padd5_imports_external":
            add_balance_value(summary, period, "padd5_imports_total_kbd", value)

        elif route == "padd5_exports_external":
            add_balance_value(summary, period, "padd5_exports_total_kbd", value)

        elif route == "us_imports_external":
            add_balance_value(summary, period, "us_imports_total_kbd", value)
            if is_canada(origin_country):
                add_balance_value(summary, period, "us_imports_canada_kbd", value)

        elif route == "us_exports_external":
            add_balance_value(summary, period, "us_exports_total_kbd", value)
            if destination_trade_group in {"europe", "latin_america"}:
                add_balance_value(summary, period, f"us_exports_{destination_trade_group}_kbd", value)

        elif route in {"diesel_padd3_to_padd1ab", "padd3_domestic_receipts"} and commodity == "diesel":
            add_balance_value(summary, period, "padd3_to_padd1ab_kbd", value)
            add_balance_value(summary, period, "padd3_to_padd1_kbd", value)

        elif route in {"diesel_padd3_to_padd1c", "padd3_domestic_receipts"} and commodity == "diesel":
            add_balance_value(summary, period, "padd3_to_padd1c_kbd", value)
            add_balance_value(summary, period, "padd3_to_padd1_kbd", value)

        elif route == "jet_padd3_to_padd1" and commodity == "jet":
            add_balance_value(summary, period, "padd3_to_padd1_kbd", value)

        elif route in {"jet_padd3_to_padd5", "padd3_domestic_receipts"} and commodity == "jet":
            add_balance_value(summary, period, "padd3_to_padd5_kbd", value)

    output_rows: list[dict[str, Any]] = []
    for period, values in sorted(summary.items()):
        derive_balance_guide_columns(values)
        output_rows.append({period_column: period, "commodity": commodity, **values})
    frame = pl.DataFrame(output_rows) if output_rows else pl.DataFrame({period_column: []}, schema={period_column: pl.Utf8})
    return ensure_columns(frame, [period_column, *schema])


def write_balance_guide_output_set(name: str, weekly: pl.DataFrame, monthly: pl.DataFrame, schema: list[str]) -> dict[str, Any]:
    daily_path = OUTPUT_DIR / "daily" / f"{name}_daily.csv"
    weekly_path = OUTPUT_DIR / "weekly" / f"{name}_weekly.csv"
    monthly_path = OUTPUT_DIR / "monthly" / f"{name}_monthly.csv"
    daily = pl.DataFrame({"date": []}, schema={"date": pl.Utf8})
    daily = ensure_columns(daily, ["date", *schema])
    daily.write_csv(daily_path)
    weekly.write_csv(weekly_path)
    monthly.write_csv(monthly_path)
    weekly_dates = weekly["week_ending"].to_list() if "week_ending" in weekly.columns and weekly.height else []
    monthly_dates = monthly["month"].to_list() if "month" in monthly.columns and monthly.height else []
    dates = [*weekly_dates, *monthly_dates]
    return {
        "daily_path": str(daily_path),
        "weekly_path": str(weekly_path),
        "monthly_path": str(monthly_path),
        "daily_rows": 0,
        "weekly_rows": int(weekly.height),
        "monthly_rows": int(monthly.height),
        "min_date": min(dates) if dates else "",
        "max_date": max(dates) if dates else "",
    }


def build_balance_guide_outputs(long_rows: pl.DataFrame) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    schema = load_yaml(CONFIG_DIR / "output_schema.yml")["balance_guide_columns"]
    rows = long_rows.filter(pl.col("family") == "balance_guides")
    if rows.is_empty():
        return outputs
    for commodity in ["diesel", "jet"]:
        weekly = balance_guide_frame(rows, commodity, "weekly", "week_ending", schema)
        monthly = balance_guide_frame(rows, commodity, "monthly", "month", schema)
        if weekly.is_empty() and monthly.is_empty():
            continue
        outputs[f"us_{commodity}_balance_guides"] = write_balance_guide_output_set(
            f"us_{commodity}_balance_guides",
            weekly,
            monthly,
            schema,
        )
    return outputs


def build_outputs(long_rows: pl.DataFrame, start_date: date, end_date: date) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    outputs.update(build_us_external_outputs(long_rows, start_date, end_date))
    outputs.update(build_europe_external_outputs(long_rows, start_date, end_date))
    outputs.update(build_domestic_padd_outputs(long_rows, start_date, end_date))
    outputs.update(build_padd1_import_guide_outputs(long_rows, start_date, end_date))
    outputs.update(build_balance_guide_outputs(long_rows))
    return outputs
