from __future__ import annotations

import csv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import statistics
import sys
import urllib.parse
import urllib.request

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
from src.env_loader import load_env_files


load_env_files()


OUT_DIR = Path(__file__).resolve().parent
HOURLY_REGION_RAW_PATH = OUT_DIR / "hourly_region_data_raw.csv"
HOURLY_OIL_RAW_PATH = OUT_DIR / "hourly_oil_generation_raw.csv"
HOURLY_MODEL_INPUT_PATH = OUT_DIR / "hourly_dfo_model_input.csv"
WEATHER_14D_PATH = OUT_DIR / "weather_14d_padd1_cities.csv"
FORECAST_24H_PATH = OUT_DIR / "dfo_generation_forecast_24h.csv"
FORECAST_CHART_PATH = OUT_DIR / "dfo_generation_forecast_24h.jpg"
FORECAST_MANIFEST_PATH = OUT_DIR / "hourly_forecast_manifest.json"
CALIBRATION_MANIFEST_PATH = OUT_DIR / "manifest.json"
OBSOLETE_OUTPUTS = [OUT_DIR / "weather_14d_boston_newyork.csv"]

REGION_DATA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
FUEL_TYPE_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
PAGE_LENGTH = int(os.environ.get("POWER_DFO_HOURLY_PAGE_LENGTH", "5000"))
FETCH_CONCURRENCY = max(1, int(os.environ.get("POWER_DFO_HOURLY_FETCH_CONCURRENCY", "4")))
WEATHER_CONCURRENCY = max(1, int(os.environ.get("POWER_DFO_WEATHER_CONCURRENCY", "4")))
MAX_REGION_ROWS = int(os.environ.get("POWER_DFO_HOURLY_REGION_ROWS", "40000"))
MAX_OIL_ROWS = int(os.environ.get("POWER_DFO_HOURLY_OIL_ROWS", "20000"))
PROFILE_HISTORY_HOURS = int(os.environ.get("POWER_DFO_PROFILE_HISTORY_HOURS", "2160"))
RECENT_DEFAULT_HOURS = int(os.environ.get("POWER_DFO_RECENT_DEFAULT_HOURS", "336"))
PUBLIC_EIA_API_KEY_FALLBACK = "4ZooAQ2fowZXw2nzj8dhtscw8orLWsdpcEk0sbzM"
RESPONDENTS = ["MIDA", "NE"]
FORECAST_HOURS = int(os.environ.get("POWER_DFO_FORECAST_HOURS", "24"))
WEATHER_DAYS = int(os.environ.get("POWER_DFO_WEATHER_DAYS", "14"))
NWS_USER_AGENT = os.environ.get("NWS_USER_AGENT", "python-pulls-power-generation-dfo/0.1 alexhoffmann")

WEATHER_POINTS = {
    "ct_hartford": ("CT", "Hartford", 41.7658, -72.6734),
    "dc_washington": ("DC", "Washington", 38.9072, -77.0369),
    "de_wilmington": ("DE", "Wilmington", 39.7391, -75.5398),
    "ma_boston": ("MA", "Boston", 42.3601, -71.0589),
    "md_baltimore": ("MD", "Baltimore", 39.2904, -76.6122),
    "me_portland": ("ME", "Portland", 43.6591, -70.2568),
    "nh_manchester": ("NH", "Manchester", 42.9956, -71.4548),
    "nj_newark": ("NJ", "Newark", 40.7357, -74.1724),
    "ny_new_york": ("NY", "New York", 40.7128, -74.0060),
    "pa_philadelphia": ("PA", "Philadelphia", 39.9526, -75.1652),
    "ri_providence": ("RI", "Providence", 41.8240, -71.4128),
    "va_richmond": ("VA", "Richmond", 37.5407, -77.4360),
    "vt_burlington": ("VT", "Burlington", 44.4759, -73.2121),
    "wv_charleston": ("WV", "Charleston", 38.3498, -81.6326),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def api_key() -> str:
    return os.environ.get("EIA_API_KEY") or os.environ.get("EIA_API_TOKEN") or os.environ.get("EIA_KEY") or PUBLIC_EIA_API_KEY_FALLBACK


def parse_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "--", "NA", "N/A", "null", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_eia_hour(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)


def format_hour(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H")


def request_json(url: str, params: list[tuple[str, str | int]], headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers or {"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def request_json_url(url: str, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {"Accept": "application/geo+json", "User-Agent": NWS_USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_eia_pages(url: str, base_params: list[tuple[str, str | int]], max_rows: int) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    first_params = [*base_params, ("offset", 0), ("length", PAGE_LENGTH)]
    first_payload = request_json(url, first_params)
    first_data = first_payload.get("response", {}).get("data", [])
    total = int(first_payload.get("response", {}).get("total", len(first_data)))
    limit = min(max_rows, total)
    payloads_by_offset: dict[int, dict] = {0: first_payload}
    offsets = list(range(PAGE_LENGTH, limit, PAGE_LENGTH))
    if offsets:
        with ThreadPoolExecutor(max_workers=min(FETCH_CONCURRENCY, len(offsets))) as executor:
            futures = {
                executor.submit(request_json, url, [*base_params, ("offset", offset), ("length", PAGE_LENGTH)]): offset
                for offset in offsets
            }
            for future in as_completed(futures):
                payloads_by_offset[futures[future]] = future.result()

    rows: list[dict[str, str]] = []
    sources: list[dict[str, object]] = []
    for offset in sorted(payloads_by_offset):
        payload = payloads_by_offset[offset]
        data = payload.get("response", {}).get("data", [])
        rows.extend(data)
        sources.append({"url": url, "offset": offset, "row_count": len(data), "total": total})
    return rows, sources


def write_dicts(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def write_raw(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    write_dicts(path, rows, fieldnames)


def region_params() -> list[tuple[str, str | int]]:
    params: list[tuple[str, str | int]] = [
        ("api_key", api_key()),
        ("frequency", "hourly"),
        ("data[0]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
    ]
    params.extend(("facets[respondent][]", respondent) for respondent in RESPONDENTS)
    return params


def oil_params() -> list[tuple[str, str | int]]:
    params: list[tuple[str, str | int]] = [
        ("api_key", api_key()),
        ("frequency", "hourly"),
        ("data[0]", "value"),
        ("facets[fueltype][]", "OIL"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
    ]
    params.extend(("facets[respondent][]", respondent) for respondent in RESPONDENTS)
    return params


def load_dfo_factor() -> tuple[float, str]:
    if not CALIBRATION_MANIFEST_PATH.exists():
        return 1.0, "missing_manifest_default_1"
    manifest = json.loads(CALIBRATION_MANIFEST_PATH.read_text(encoding="utf-8"))
    factor = parse_number(manifest.get("calibration", {}).get("current_dfo_consumption_per_oil_mwh"))
    if factor is None or factor <= 0:
        return 1.0, "missing_factor_default_1"
    return factor, str(manifest.get("calibration", {}).get("latest_factor_year", "latest"))


def aggregate_region(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        period = str(row.get("period", ""))
        data_type = str(row.get("type", ""))
        value = parse_number(row.get("value"))
        if not period or value is None:
            continue
        if data_type in {"D", "DF"}:
            out[period][data_type] += value
    return out


def aggregate_oil(rows: list[dict[str, str]]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for row in rows:
        period = str(row.get("period", ""))
        value = parse_number(row.get("value"))
        if period and value is not None:
            out[period] += value
    return out


def build_model_input(
    region_rows: list[dict[str, str]],
    oil_rows: list[dict[str, str]],
    dfo_factor: float,
) -> list[dict[str, object]]:
    region = aggregate_region(region_rows)
    oil = aggregate_oil(oil_rows)
    periods = sorted(set(region) | set(oil))
    rows: list[dict[str, object]] = []
    for period in periods:
        hour = parse_eia_hour(period)
        oil_mwh = oil.get(period, 0.0)
        demand_actual = region.get(period, {}).get("D", 0.0)
        demand_forecast = region.get(period, {}).get("DF", 0.0)
        rows.append(
            {
                "period": period,
                "hour_utc": hour.hour,
                "weekday_utc": hour.weekday(),
                "mida_ne_actual_demand_mwh": f"{demand_actual:.6f}",
                "mida_ne_dayahead_demand_forecast_mwh": f"{demand_forecast:.6f}",
                "mida_ne_oil_generation_mwh": f"{oil_mwh:.6f}",
                "estimated_dfo_generation": f"{oil_mwh * dfo_factor:.6f}",
            }
        )
    return rows


def point_forecast_url(lat: float, lon: float) -> str:
    payload = request_json_url(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    return str(payload["properties"]["forecastHourly"])


def parse_nws_temperature(value: object) -> float | None:
    parsed = parse_number(value)
    return parsed


def fetch_weather_hourly() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    def fetch_city_weather(city_key: str, state: str, city_name: str, lat: float, lon: float) -> tuple[str, list[dict[str, object]], dict[str, object]]:
        forecast_url = point_forecast_url(lat, lon)
        payload = request_json_url(forecast_url)
        periods = payload.get("properties", {}).get("periods", [])
        rows: list[dict[str, object]] = []
        for period in periods:
            start_time = str(period.get("startTime", ""))
            if not start_time:
                continue
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(timezone.utc)
            temperature = parse_nws_temperature(period.get("temperature"))
            if temperature is None:
                continue
            rows.append(
                {
                    "period": format_hour(start),
                    "city_key": city_key,
                    "state": state,
                    "city": city_name,
                    "temperature_f": temperature,
                    "source": "nws_hourly",
                }
            )
        source = {
            "state": state,
            "city": city_name,
            "city_key": city_key,
            "points": f"{lat:.4f},{lon:.4f}",
            "forecast_hourly_url": forecast_url,
            "hourly_rows": len(rows),
        }
        return city_key, rows, source

    city_rows: dict[str, list[dict[str, object]]] = {}
    sources: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=min(WEATHER_CONCURRENCY, len(WEATHER_POINTS))) as executor:
        futures = {
            executor.submit(fetch_city_weather, city_key, state, city_name, lat, lon): city_key
            for city_key, (state, city_name, lat, lon) in WEATHER_POINTS.items()
        }
        for future in as_completed(futures):
            city_key, rows, source = future.result()
            city_rows[city_key] = rows
            sources.append(source)
    sources.sort(key=lambda source: str(source["city_key"]))

    combined_by_period: dict[str, dict[str, float]] = defaultdict(dict)
    source_by_period: dict[str, str] = {}
    for city_key, rows in city_rows.items():
        for row in rows:
            combined_by_period[str(row["period"])][city_key] = float(row["temperature_f"])
            source_by_period[str(row["period"])] = "nws_hourly"

    if combined_by_period:
        last_period = parse_eia_hour(max(combined_by_period))
        first_period = parse_eia_hour(min(combined_by_period))
    else:
        first_period = utc_now().replace(minute=0, second=0, microsecond=0)
        last_period = first_period

    target_end = first_period + timedelta(days=WEATHER_DAYS)
    period = first_period
    while period < target_end:
        key = format_hour(period)
        if key not in combined_by_period:
            lookback = format_hour(period - timedelta(days=1))
            fallback = combined_by_period.get(lookback) or combined_by_period.get(format_hour(last_period), {})
            combined_by_period[key].update(fallback)
            source_by_period[key] = "extended_from_nws_hourly_profile"
        period += timedelta(hours=1)

    out: list[dict[str, object]] = []
    for period_key in sorted(combined_by_period):
        temps = combined_by_period[period_key]
        available = [temps.get(city_key) for city_key in WEATHER_POINTS if temps.get(city_key) is not None]
        avg_temp = sum(available) / len(available) if available else 65.0
        hdd = max(0.0, 65.0 - avg_temp)
        cdd = max(0.0, avg_temp - 65.0)
        row = {
            "period": period_key,
            "avg_temperature_f": f"{avg_temp:.2f}",
            "hdd_65": f"{hdd:.2f}",
            "cdd_65": f"{cdd:.2f}",
            "source": source_by_period.get(period_key, "nws_hourly"),
        }
        for city_key in WEATHER_POINTS:
            value = temps.get(city_key)
            row[f"{city_key}_temperature_f"] = f"{value:.2f}" if value is not None else ""
        out.append(row)
    return out, sources


def median(values: list[float], default: float = 0.0) -> float:
    clean = [value for value in values if math.isfinite(value)]
    return statistics.median(clean) if clean else default


def percentile(values: list[float], quantile: float, default: float = 0.0) -> float:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return default
    if len(clean) == 1:
        return clean[0]
    rank = max(0.0, min(1.0, quantile)) * (len(clean) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return clean[lower]
    weight = rank - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def forecast_with_chronos2(model_input: list[dict[str, object]], horizon_periods: list[str]) -> tuple[list[float] | None, str]:
    try:
        import pandas as pd
        from autogluon.timeseries import TimeSeriesDataFrame, TimeSeriesPredictor
    except Exception:
        return None, "chronos2_unavailable_autogluon_not_installed"

    try:
        history = [
            {"item_id": "mida_ne_oil", "timestamp": parse_eia_hour(str(row["period"])), "target": float(row["mida_ne_oil_generation_mwh"])}
            for row in model_input
            if float(row["mida_ne_oil_generation_mwh"]) > 0
        ]
        if len(history) < 48:
            return None, "chronos2_skipped_insufficient_history"
        train_data = TimeSeriesDataFrame.from_data_frame(pd.DataFrame(history), id_column="item_id", timestamp_column="timestamp")
        predictor = TimeSeriesPredictor(prediction_length=len(horizon_periods), target="target", freq="h", verbosity=0).fit(
            train_data,
            presets="chronos2",
            time_limit=int(os.environ.get("POWER_DFO_CHRONOS_TIME_LIMIT", "120")),
        )
        prediction = predictor.predict(train_data).reset_index()
        values = [float(value) for value in prediction["mean"].tail(len(horizon_periods)).tolist()]
        return values, "chronos2_autogluon"
    except Exception as exc:
        return None, f"chronos2_failed_{type(exc).__name__}"


def fallback_forecast(
    model_input: list[dict[str, object]],
    weather_rows: list[dict[str, object]],
    dfo_factor: float,
) -> tuple[list[dict[str, object]], str]:
    actual_rows = [row for row in model_input if float(row["mida_ne_oil_generation_mwh"]) > 0]
    if not actual_rows:
        raise RuntimeError("No hourly oil generation history available")
    latest_actual = parse_eia_hour(str(actual_rows[-1]["period"]))
    next_current_hour = utc_now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    horizon_start = max(latest_actual + timedelta(hours=1), next_current_hour)
    horizon = [horizon_start + timedelta(hours=index) for index in range(FORECAST_HOURS)]
    horizon_periods = [format_hour(hour) for hour in horizon]
    chronos_values, model_name = forecast_with_chronos2(model_input, horizon_periods)

    ratios_by_hour: dict[int, list[float]] = defaultdict(list)
    oil_by_hour: dict[int, list[float]] = defaultdict(list)
    recent_oil = [float(row["mida_ne_oil_generation_mwh"]) for row in actual_rows[-RECENT_DEFAULT_HOURS:]]
    recent_default = median(recent_oil, default=0.0)
    recent_demand_values: list[float] = []
    for row in actual_rows[-PROFILE_HISTORY_HOURS:]:
        oil = float(row["mida_ne_oil_generation_mwh"])
        demand = float(row["mida_ne_actual_demand_mwh"]) or float(row["mida_ne_dayahead_demand_forecast_mwh"])
        hour = int(row["hour_utc"])
        oil_by_hour[hour].append(oil)
        if demand > 0:
            recent_demand_values.append(demand)
            ratios_by_hour[hour].append(oil / demand)
    demand_reference = percentile(recent_demand_values, 0.70, default=0.0)

    forecast_demand_by_period = {
        str(row["period"]): float(row["mida_ne_dayahead_demand_forecast_mwh"])
        for row in model_input
        if float(row["mida_ne_dayahead_demand_forecast_mwh"]) > 0
    }
    weather_by_period = {str(row["period"]): row for row in weather_rows}
    weather_periods = sorted(weather_by_period)

    def weather_for(period_key: str) -> dict[str, object]:
        direct = weather_by_period.get(period_key)
        if direct is not None:
            return direct
        if not weather_periods:
            return {}
        target = parse_eia_hour(period_key)
        nearest_key = min(weather_periods, key=lambda key: abs((parse_eia_hour(key) - target).total_seconds()))
        nearest = dict(weather_by_period[nearest_key])
        nearest["source"] = f"nearest_{nearest.get('source', 'weather')}"
        return nearest

    out: list[dict[str, object]] = []
    for index, hour_dt in enumerate(horizon):
        period = format_hour(hour_dt)
        weather = weather_for(period)
        hdd = float(weather.get("hdd_65", 0.0) or 0.0)
        cdd = float(weather.get("cdd_65", 0.0) or 0.0)
        demand_forecast = forecast_demand_by_period.get(period, 0.0)
        hour_of_day = hour_dt.hour
        base_oil = median(oil_by_hour.get(hour_of_day, []), default=recent_default)
        hour_ratios = ratios_by_hour.get(hour_of_day, [])
        median_ratio = median(hour_ratios, default=0.0)
        high_ratio = percentile(hour_ratios, 0.80, default=median_ratio)
        demand_stress = 0.0
        if demand_reference and demand_forecast:
            demand_stress = max(0.0, min(1.0, (demand_forecast / demand_reference) - 1.0))
        demand_ratio = median_ratio * (1.0 - demand_stress) + high_ratio * demand_stress
        demand_oil = demand_forecast * demand_ratio if demand_forecast and demand_ratio else base_oil
        weather_multiplier = 1.0 + max(0.0, hdd - 10.0) * 0.015 + max(0.0, cdd - 12.0) * 0.010
        fallback_oil = max(0.0, (0.60 * demand_oil + 0.40 * base_oil) * weather_multiplier)
        oil_generation = max(0.0, chronos_values[index]) if chronos_values is not None else fallback_oil
        out.append(
            {
                "period": period,
                "forecast_hour": index + 1,
                "model": model_name if chronos_values is not None else "fallback_hourly_load_weather_profile",
                "mida_ne_dayahead_demand_forecast_mwh": f"{demand_forecast:.6f}",
                "avg_temperature_f": weather.get("avg_temperature_f", ""),
                "hdd_65": weather.get("hdd_65", ""),
                "cdd_65": weather.get("cdd_65", ""),
                "forecast_oil_generation_mwh": f"{oil_generation:.6f}",
                "dfo_consumption_per_oil_mwh": f"{dfo_factor:.12f}",
                "forecast_dfo_generation": f"{oil_generation * dfo_factor:.6f}",
                "weather_source": weather.get("source", ""),
            }
        )
    return out, model_name if chronos_values is not None else "fallback_hourly_load_weather_profile"


def write_forecast_chart(rows: list[dict[str, object]]) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(OUT_DIR / ".matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    times = [parse_eia_hour(str(row["period"])) for row in rows]
    values = [float(row["forecast_dfo_generation"]) for row in rows]
    fig, ax = plt.subplots(figsize=(11, 5.8), dpi=150)
    ax.plot(times, values, color="#b42318", linewidth=2.2)
    ax.scatter(times, values, color="#b42318", s=18)
    ax.set_title("Next 24 Hours Forecast DFO Generation", fontsize=15, fontweight="bold", loc="left")
    ax.text(0, 1.02, "MIDA + NE hourly oil generation forecast converted with current top-20 correlation DFO factor.", transform=ax.transAxes, fontsize=9)
    ax.set_ylabel("Forecast DFO generation")
    ax.grid(True, color="#e5e7eb", linewidth=0.8)
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.autofmt_xdate(rotation=30)
    fig.savefig(FORECAST_CHART_PATH, format="jpg", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    for path in OBSOLETE_OUTPUTS:
        if path.exists():
            path.unlink()
    dfo_factor, factor_source = load_dfo_factor()
    region_rows, region_sources = fetch_eia_pages(REGION_DATA_URL, region_params(), MAX_REGION_ROWS)
    oil_rows, oil_sources = fetch_eia_pages(FUEL_TYPE_URL, oil_params(), MAX_OIL_ROWS)
    weather_rows, weather_sources = fetch_weather_hourly()
    model_input = build_model_input(region_rows, oil_rows, dfo_factor)
    forecast_rows, model_name = fallback_forecast(model_input, weather_rows, dfo_factor)

    write_raw(HOURLY_REGION_RAW_PATH, region_rows)
    write_raw(HOURLY_OIL_RAW_PATH, oil_rows)
    write_dicts(
        HOURLY_MODEL_INPUT_PATH,
        model_input,
        [
            "period",
            "hour_utc",
            "weekday_utc",
            "mida_ne_actual_demand_mwh",
            "mida_ne_dayahead_demand_forecast_mwh",
            "mida_ne_oil_generation_mwh",
            "estimated_dfo_generation",
        ],
    )
    write_dicts(
        WEATHER_14D_PATH,
        weather_rows,
        [
            "period",
            "avg_temperature_f",
            "hdd_65",
            "cdd_65",
            "source",
            *[f"{city_key}_temperature_f" for city_key in WEATHER_POINTS],
        ],
    )
    write_dicts(
        FORECAST_24H_PATH,
        forecast_rows,
        [
            "period",
            "forecast_hour",
            "model",
            "mida_ne_dayahead_demand_forecast_mwh",
            "avg_temperature_f",
            "hdd_65",
            "cdd_65",
            "forecast_oil_generation_mwh",
            "dfo_consumption_per_oil_mwh",
            "forecast_dfo_generation",
            "weather_source",
        ],
    )
    write_forecast_chart(forecast_rows)

    manifest = {
        "pipeline_name": "power_generation_dfo_hourly_forecast",
        "generated_at": utc_now().isoformat(),
        "forecast_hours": FORECAST_HOURS,
        "weather_days_requested": WEATHER_DAYS,
        "dfo_factor": dfo_factor,
        "dfo_factor_source": factor_source,
        "model": model_name,
        "chronos2_note": "Uses AutoGluon Chronos-2 when autogluon.timeseries is installed; otherwise falls back to a load/weather/hour-profile model.",
        "fallback_model_note": "Fallback uses a larger recent hourly history window and blends toward higher historical oil-to-load ratios when forecast demand is elevated.",
        "weather_locations": [
            {"state": state, "city": city, "city_key": city_key, "latitude": lat, "longitude": lon}
            for city_key, (state, city, lat, lon) in WEATHER_POINTS.items()
        ],
        "history_windows": {
            "profile_history_hours": PROFILE_HISTORY_HOURS,
            "recent_default_hours": RECENT_DEFAULT_HOURS,
            "max_region_rows": MAX_REGION_ROWS,
            "max_oil_rows": MAX_OIL_ROWS,
        },
        "row_counts": {
            "region_raw": len(region_rows),
            "oil_raw": len(oil_rows),
            "model_input": len(model_input),
            "weather_rows": len(weather_rows),
            "forecast_rows": len(forecast_rows),
        },
        "outputs": {
            "hourly_region_raw": str(HOURLY_REGION_RAW_PATH),
            "hourly_oil_raw": str(HOURLY_OIL_RAW_PATH),
            "hourly_model_input": str(HOURLY_MODEL_INPUT_PATH),
            "weather_14d": str(WEATHER_14D_PATH),
            "forecast_24h": str(FORECAST_24H_PATH),
            "forecast_chart": str(FORECAST_CHART_PATH),
        },
        "sources": [*region_sources, *oil_sources, *weather_sources],
    }
    FORECAST_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    total_dfo = sum(float(row["forecast_dfo_generation"]) for row in forecast_rows)
    print(f"hourly_dfo_forecast model={model_name} rows={len(forecast_rows)} next_24h_dfo={total_dfo:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
