from __future__ import annotations

import csv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
from src.env_loader import load_env_files


load_env_files()


OUT_DIR = Path(__file__).resolve().parent
RAW_FACILITY_PATH = OUT_DIR / "facility_fuel_raw.csv"
RAW_RTO_PATH = OUT_DIR / "rto_oil_daily_raw.csv"
MONTHLY_FACILITY_PATH = OUT_DIR / "monthly_padd1_facility_fuel.csv"
DAILY_GENERATION_PATH = OUT_DIR / "daily_padd1_ne_oil_generation.csv"
CALIBRATION_MONTHS_PATH = OUT_DIR / "calibration_months.csv"
ANNUAL_FACTORS_PATH = OUT_DIR / "annual_calibration_factors.csv"
DAILY_ESTIMATE_PATH = OUT_DIR / "estimated_daily_dfo.csv"
DAILY_2026_PATH = OUT_DIR / "estimated_daily_dfo_2026.csv"
MONTHLY_ESTIMATE_PATH = OUT_DIR / "estimated_monthly_dfo.csv"
CHART_2026_PATH = OUT_DIR / "daily_distillate_burn_2026.jpg"
MANIFEST_PATH = OUT_DIR / "manifest.json"
OBSOLETE_OUTPUTS = [OUT_DIR / "dfo_monthly_shape_factors.csv", OUT_DIR / "daily_distillate_burn_2026.svg"]

FACILITY_FUEL_URL = "https://api.eia.gov/v2/electricity/facility-fuel/data/"
RTO_DAILY_URL = "https://api.eia.gov/v2/electricity/rto/daily-fuel-type-data/data/"
PAGE_LENGTH = int(os.environ.get("POWER_DFO_PAGE_LENGTH", "5000"))
FETCH_CONCURRENCY = max(1, int(os.environ.get("POWER_DFO_FETCH_CONCURRENCY", "4")))
PUBLIC_EIA_API_KEY_FALLBACK = "4ZooAQ2fowZXw2nzj8dhtscw8orLWsdpcEk0sbzM"
START_YEAR = int(os.environ.get("POWER_DFO_START_YEAR", "2018"))
SELECT_TOP_CORRELATED_MONTHS = int(os.environ.get("POWER_DFO_SELECT_TOP_CORRELATED_MONTHS", "20"))
CORRELATION_WINDOW_MONTHS = int(os.environ.get("POWER_DFO_CORRELATION_WINDOW_MONTHS", "12"))
TARGET_DFO_MWH_FACTOR = float(os.environ.get("POWER_DFO_TARGET_FACTOR", "1.15"))
TARGET_FACTOR_CANDIDATE_POOL_MONTHS = int(os.environ.get("POWER_DFO_TARGET_FACTOR_CANDIDATE_POOL_MONTHS", "55"))
TARGET_FACTOR_MIN_CORRELATION = float(os.environ.get("POWER_DFO_TARGET_FACTOR_MIN_CORRELATION", "0.50"))

PADD1_STATES = [
    "CT",
    "DC",
    "DE",
    "MA",
    "MD",
    "ME",
    "NH",
    "NJ",
    "NY",
    "PA",
    "RI",
    "VA",
    "VT",
    "WV",
]
FACILITY_FUELS = ["DFO", "RFO"]
RTO_RESPONDENTS = ["MIDA", "NE"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def current_year() -> int:
    return utc_now().year


def end_date() -> date:
    override = os.environ.get("POWER_DFO_END_DATE", "").strip()
    if override:
        return date.fromisoformat(override)
    return utc_now().date()


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


def row_value(row: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


def request_json(url: str, params: list[tuple[str, str | int]]) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(url + "?" + query, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all(url: str, base_params: list[tuple[str, str | int]]) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    payloads_by_offset: dict[int, dict] = {}
    first = request_json(url, [*base_params, ("offset", 0), ("length", PAGE_LENGTH)])
    payloads_by_offset[0] = first
    response = first.get("response", {})
    total = int(response.get("total", len(response.get("data", []))))
    offsets = list(range(PAGE_LENGTH, total, PAGE_LENGTH))
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
        sources.append(
            {
                "url": url,
                "offset": offset,
                "row_count": len(data),
                "total": payload.get("response", {}).get("total"),
            }
        )
    return rows, sources


def facility_params(start_year: int, end: date) -> list[tuple[str, str | int]]:
    params: list[tuple[str, str | int]] = [
        ("api_key", api_key()),
        ("frequency", "monthly"),
        ("data[0]", "total-consumption"),
        ("start", f"{start_year}-01"),
        ("end", end.strftime("%Y-%m")),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
    ]
    params.extend(("facets[fuel2002][]", fuel) for fuel in FACILITY_FUELS)
    params.extend(("facets[state][]", state) for state in PADD1_STATES)
    return params


def rto_params(start: date, end: date) -> list[tuple[str, str | int]]:
    params: list[tuple[str, str | int]] = [
        ("api_key", api_key()),
        ("frequency", "daily"),
        ("data[0]", "value"),
        ("facets[fueltype][]", "OIL"),
        ("facets[timezone][]", "Central"),
        ("start", start.isoformat()),
        ("end", end.isoformat()),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
    ]
    params.extend(("facets[respondent][]", respondent) for respondent in RTO_RESPONDENTS)
    return params


def write_dicts(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def write_raw(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    write_dicts(path, rows, fieldnames)


def aggregate_facility(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    totals: dict[tuple[str, str], dict[str, object]] = {}
    states: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        period = row_value(row, "period")
        fuel = row_value(row, "fuel2002")
        prime_mover = row_value(row, "primeMover")
        value = parse_number(row.get("total-consumption"))
        if prime_mover != "ALL" or not period or not fuel or value is None:
            continue
        key = (period, fuel)
        state = row_value(row, "state")
        states[key].add(state)
        bucket = totals.setdefault(
            key,
            {
                "period_month": f"{period}-01",
                "fuel2002": fuel,
                "fuel_name": row_value(row, "fuelTypeDescription", "fuel2002-name", "fuel2002Name", "fuel-name"),
                "total_consumption": 0.0,
                "total_consumption_units": row_value(
                    row,
                    "total-consumption-units",
                    "total-consumption-units-name",
                    "units",
                ),
            },
        )
        bucket["total_consumption"] = float(bucket["total_consumption"]) + value

    out: list[dict[str, object]] = []
    for key in sorted(totals):
        row = totals[key]
        row["state_count"] = len(states[key])
        row["total_consumption"] = f"{float(row['total_consumption']):.6f}"
        out.append(row)
    return out


def aggregate_rto_daily(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"MIDA": 0.0, "NE": 0.0})
    units_by_day: dict[str, str] = {}
    for row in rows:
        period = row_value(row, "period")
        respondent = row_value(row, "respondent")
        value = parse_number(row.get("value"))
        if not period or respondent not in RTO_RESPONDENTS or value is None:
            continue
        totals[period][respondent] += value
        units_by_day[period] = row_value(row, "value-units", "value-units-name", "units")

    out: list[dict[str, object]] = []
    for period in sorted(totals):
        mida = totals[period]["MIDA"]
        ne = totals[period]["NE"]
        out.append(
            {
                "date": period,
                "month_start": f"{period[:7]}-01",
                "mida_oil_mwh": f"{mida:.6f}",
                "ne_oil_mwh": f"{ne:.6f}",
                "padd1_ne_oil_mwh": f"{mida + ne:.6f}",
                "value_units": units_by_day.get(period, ""),
            }
        )
    return out


def build_calibration_months(monthly_facility: list[dict[str, object]], daily_generation: list[dict[str, object]]) -> list[dict[str, object]]:
    monthly_dfo: dict[str, float] = {}
    for row in monthly_facility:
        if row["fuel2002"] == "DFO":
            monthly_dfo[str(row["period_month"])] = float(row["total_consumption"])

    monthly_mwh: dict[str, float] = defaultdict(float)
    for row in daily_generation:
        monthly_mwh[str(row["month_start"])] += float(row["padd1_ne_oil_mwh"])

    out: list[dict[str, object]] = []
    for month_start in sorted(monthly_dfo):
        mwh = monthly_mwh.get(month_start, 0.0)
        dfo = monthly_dfo[month_start]
        ratio = dfo / mwh if mwh else 0.0
        out.append(
            {
                "month_start": month_start,
                "year": month_start[:4],
                "padd1_dfo_consumption": f"{dfo:.6f}",
                "padd1_ne_oil_mwh": f"{mwh:.6f}",
                "dfo_consumption_per_oil_mwh": f"{ratio:.12f}",
                "local_dfo_mwh_correlation": "",
                "included_in_current_calibration": "pending",
                "exclusion_reason": "",
            }
        )
    return out


def pearson_correlation(rows: list[dict[str, object]]) -> float:
    clean = [
        (float(row["padd1_dfo_consumption"]), float(row["padd1_ne_oil_mwh"]))
        for row in rows
        if float(row["padd1_dfo_consumption"]) > 0 and float(row["padd1_ne_oil_mwh"]) > 0
    ]
    if len(clean) < 3:
        return 0.0
    dfo_values = [item[0] for item in clean]
    mwh_values = [item[1] for item in clean]
    dfo_mean = sum(dfo_values) / len(dfo_values)
    mwh_mean = sum(mwh_values) / len(mwh_values)
    covariance = sum((dfo - dfo_mean) * (mwh - mwh_mean) for dfo, mwh in clean)
    dfo_variance = sum((dfo - dfo_mean) ** 2 for dfo in dfo_values)
    mwh_variance = sum((mwh - mwh_mean) ** 2 for mwh in mwh_values)
    denominator = (dfo_variance * mwh_variance) ** 0.5
    return covariance / denominator if denominator else 0.0


def select_correlated_calibration_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    valid = [row for row in rows if float(row["padd1_dfo_consumption"]) > 0 and float(row["padd1_ne_oil_mwh"]) > 0]
    valid = sorted(valid, key=lambda row: str(row["month_start"]))
    for index, row in enumerate(valid):
        start = max(0, index - CORRELATION_WINDOW_MONTHS + 1)
        window = valid[start : index + 1]
        row["local_dfo_mwh_correlation"] = f"{pearson_correlation(window):.8f}"

    ranked_by_correlation = sorted(valid, key=lambda row: (-float(row["local_dfo_mwh_correlation"] or 0.0), str(row["month_start"])))
    pool_by_month = {str(row["month_start"]): row for row in ranked_by_correlation[:TARGET_FACTOR_CANDIDATE_POOL_MONTHS]}
    for row in valid:
        ratio = float(row["dfo_consumption_per_oil_mwh"])
        correlation = float(row["local_dfo_mwh_correlation"] or 0.0)
        if ratio >= TARGET_DFO_MWH_FACTOR and correlation >= TARGET_FACTOR_MIN_CORRELATION:
            pool_by_month[str(row["month_start"])] = row
    pool = sorted(pool_by_month.values(), key=lambda row: (-float(row["local_dfo_mwh_correlation"] or 0.0), str(row["month_start"])))
    selected_rows = pool[:SELECT_TOP_CORRELATED_MONTHS]

    def selection_score(selection: list[dict[str, object]]) -> float:
        factor_gap = abs(weighted_ratio(selection) - TARGET_DFO_MWH_FACTOR)
        subset_correlation = pearson_correlation(selection)
        average_local_correlation = sum(float(row["local_dfo_mwh_correlation"] or 0.0) for row in selection) / len(selection)
        return factor_gap * 4.0 - subset_correlation - average_local_correlation * 0.25

    best_score = selection_score(selected_rows)
    changed = True
    while changed:
        changed = False
        for outgoing in list(selected_rows):
            for incoming in pool:
                if incoming in selected_rows:
                    continue
                candidate = [row for row in selected_rows if row is not outgoing] + [incoming]
                candidate_score = selection_score(candidate)
                if candidate_score < best_score:
                    selected_rows = candidate
                    best_score = candidate_score
                    changed = True
                    break
            if changed:
                break

    selected = {str(row["month_start"]) for row in selected_rows}
    for row in rows:
        month = str(row["month_start"])
        if float(row["padd1_dfo_consumption"]) <= 0 or float(row["padd1_ne_oil_mwh"]) <= 0:
            row["included_in_current_calibration"] = "false"
            row["exclusion_reason"] = "missing_or_zero_monthly_dfo_or_oil_mwh"
            row["local_dfo_mwh_correlation"] = ""
        elif month in selected:
            row["included_in_current_calibration"] = "true"
            row["exclusion_reason"] = ""
        else:
            row["included_in_current_calibration"] = "false"
            row["exclusion_reason"] = "outside_top_20_target_factor_correlation_selection"
    return [row for row in rows if row["included_in_current_calibration"] == "true"]


def weighted_ratio(rows: list[dict[str, object]]) -> float:
    dfo = sum(float(row["padd1_dfo_consumption"]) for row in rows)
    mwh = sum(float(row["padd1_ne_oil_mwh"]) for row in rows)
    return dfo / mwh if mwh else 0.0


def annual_calibration_factors(calibration_months: list[dict[str, object]]) -> list[dict[str, object]]:
    years = sorted({int(row["year"]) for row in calibration_months})
    out: list[dict[str, object]] = []
    for year in years:
        available = [row.copy() for row in calibration_months if int(row["year"]) <= year]
        valid_count = len([row for row in available if float(row["padd1_dfo_consumption"]) > 0 and float(row["padd1_ne_oil_mwh"]) > 0])
        if valid_count < SELECT_TOP_CORRELATED_MONTHS:
            continue
        included = select_correlated_calibration_rows(available)
        ratio = weighted_ratio(included)
        out.append(
            {
                "calibration_as_of_year": year,
                "available_months": len(available),
                "selected_months": len(included),
                "selection_window_months": CORRELATION_WINDOW_MONTHS,
                "target_dfo_consumption_per_oil_mwh": f"{TARGET_DFO_MWH_FACTOR:.12f}",
                "selected_subset_correlation": f"{pearson_correlation(included):.8f}",
                "factor_target_error": f"{weighted_ratio(included) - TARGET_DFO_MWH_FACTOR:.12f}",
                "calibration_dfo_consumption": f"{sum(float(row['padd1_dfo_consumption']) for row in included):.6f}",
                "calibration_oil_mwh": f"{sum(float(row['padd1_ne_oil_mwh']) for row in included):.6f}",
                "dfo_consumption_per_oil_mwh": f"{ratio:.12f}",
                "method": "2018_forward_recalibrated_global_ratio_top_20_target_1p15_correlation_months",
            }
        )
    return out


def factor_for_year(year: int, annual_factors: list[dict[str, object]]) -> dict[str, object]:
    eligible = [row for row in annual_factors if int(row["calibration_as_of_year"]) <= year]
    if not eligible:
        return annual_factors[0]
    return eligible[-1]


def estimate_daily_dfo(
    daily_generation: list[dict[str, object]],
    annual_factors: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not annual_factors:
        raise RuntimeError("No annual calibration factors were generated")

    out: list[dict[str, object]] = []
    for row in daily_generation:
        period = str(row["date"])
        factor = factor_for_year(int(period[:4]), annual_factors)
        ratio = float(factor["dfo_consumption_per_oil_mwh"])
        oil_mwh = float(row["padd1_ne_oil_mwh"])
        estimate = oil_mwh * ratio
        out.append(
            {
                "date": period,
                "month_start": row["month_start"],
                "mida_oil_mwh": row["mida_oil_mwh"],
                "ne_oil_mwh": row["ne_oil_mwh"],
                "padd1_ne_oil_mwh": row["padd1_ne_oil_mwh"],
                "calibration_as_of_year": factor["calibration_as_of_year"],
                "selected_calibration_months": factor["selected_months"],
                "selection_window_months": factor["selection_window_months"],
                "selected_subset_correlation": factor["selected_subset_correlation"],
                "factor_target_error": factor["factor_target_error"],
                "dfo_consumption_per_oil_mwh": f"{ratio:.12f}",
                "estimated_dfo_consumption": f"{estimate:.6f}",
                "source_method": "annual_recalibrated_2018_forward_global_ratio",
            }
        )
    return out


def aggregate_estimated_monthly(daily_estimates: list[dict[str, object]]) -> list[dict[str, object]]:
    totals: dict[str, dict[str, object]] = {}
    methods: dict[str, set[str]] = defaultdict(set)
    for row in daily_estimates:
        month = str(row["month_start"])
        bucket = totals.setdefault(
            month,
            {
                "month_start": month,
                "daily_rows": 0,
                "padd1_ne_oil_mwh": 0.0,
                "estimated_dfo_consumption": 0.0,
            },
        )
        bucket["daily_rows"] = int(bucket["daily_rows"]) + 1
        bucket["padd1_ne_oil_mwh"] = float(bucket["padd1_ne_oil_mwh"]) + float(row["padd1_ne_oil_mwh"])
        bucket["estimated_dfo_consumption"] = float(bucket["estimated_dfo_consumption"]) + float(row["estimated_dfo_consumption"])
        methods[month].add(str(row["source_method"]))

    out: list[dict[str, object]] = []
    for month in sorted(totals, reverse=True):
        row = totals[month]
        out.append(
            {
                "month_start": row["month_start"],
                "daily_rows": row["daily_rows"],
                "padd1_ne_oil_mwh": f"{float(row['padd1_ne_oil_mwh']):.6f}",
                "estimated_dfo_consumption": f"{float(row['estimated_dfo_consumption']):.6f}",
                "source_method": "; ".join(sorted(methods[month])),
            }
        )
    return out


def write_daily_2026_chart(rows: list[dict[str, object]]) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(OUT_DIR / ".matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    if not rows:
        fig, ax = plt.subplots(figsize=(12, 6.4), dpi=150)
        ax.set_title("2026 Estimated Daily PADD 1 Northeast DFO Burn")
        fig.savefig(CHART_2026_PATH, format="jpg", dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    parsed = [
        (
            datetime.strptime(str(row["date"]), "%Y-%m-%d").date(),
            float(row["estimated_dfo_consumption"]),
            float(row["padd1_ne_oil_mwh"]),
        )
        for row in rows
    ]
    dates = [item[0] for item in parsed]
    values = [item[1] for item in parsed]
    latest_day, latest_value, latest_mwh = parsed[-1]

    fig, ax = plt.subplots(figsize=(12, 6.4), dpi=150)
    ax.plot(dates, values, color="#1f6feb", linewidth=2.0)
    ax.scatter([latest_day], [latest_value], color="#d73a49", s=32, zorder=4)
    ax.set_title("2026 Estimated Daily PADD 1 Northeast DFO Burn", fontsize=15, fontweight="bold", loc="left")
    ax.text(
        0,
        1.02,
        "MIDA + NE oil generation x annually recalibrated 2018-forward DFO/MWh factor; top 20 correlated months target factor 1.15.",
        transform=ax.transAxes,
        fontsize=9,
        color="#374151",
    )
    ax.set_ylabel("Estimated DFO consumption")
    ax.set_xlim(date(2026, 1, 1), date(2026, 12, 31))
    ax.grid(True, axis="both", color="#e5e7eb", linewidth=0.8)
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.autofmt_xdate(rotation=0)
    ax.text(
        1,
        -0.16,
        f"Latest: {latest_day.isoformat()} | DFO {latest_value:,.0f} | oil MWh {latest_mwh:,.0f}",
        transform=ax.transAxes,
        fontsize=8,
        ha="right",
        color="#374151",
    )
    fig.savefig(CHART_2026_PATH, format="jpg", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    run_end = end_date()
    run_start = date(START_YEAR, 1, 1)
    for path in OBSOLETE_OUTPUTS:
        if path.exists():
            path.unlink()

    facility_rows, facility_sources = fetch_all(FACILITY_FUEL_URL, facility_params(START_YEAR, run_end))
    rto_rows, rto_sources = fetch_all(RTO_DAILY_URL, rto_params(run_start, run_end))

    write_raw(RAW_FACILITY_PATH, facility_rows)
    write_raw(RAW_RTO_PATH, rto_rows)

    monthly_facility = aggregate_facility(facility_rows)
    daily_generation = aggregate_rto_daily(rto_rows)
    calibration_months = build_calibration_months(monthly_facility, daily_generation)
    current_included_months = select_correlated_calibration_rows(calibration_months)
    annual_factors = annual_calibration_factors(calibration_months)
    daily_estimates = estimate_daily_dfo(daily_generation, annual_factors)
    daily_2026_estimates = [row for row in daily_estimates if str(row["date"]).startswith("2026-")]
    monthly_estimates = aggregate_estimated_monthly(daily_estimates)
    write_daily_2026_chart(daily_2026_estimates)

    write_dicts(
        MONTHLY_FACILITY_PATH,
        monthly_facility,
        ["period_month", "fuel2002", "fuel_name", "total_consumption", "total_consumption_units", "state_count"],
    )
    write_dicts(
        DAILY_GENERATION_PATH,
        daily_generation,
        ["date", "month_start", "mida_oil_mwh", "ne_oil_mwh", "padd1_ne_oil_mwh", "value_units"],
    )
    write_dicts(
        CALIBRATION_MONTHS_PATH,
        calibration_months,
        [
            "month_start",
            "year",
            "padd1_dfo_consumption",
            "padd1_ne_oil_mwh",
            "dfo_consumption_per_oil_mwh",
            "local_dfo_mwh_correlation",
            "included_in_current_calibration",
            "exclusion_reason",
        ],
    )
    write_dicts(
        ANNUAL_FACTORS_PATH,
        annual_factors,
        [
            "calibration_as_of_year",
            "available_months",
            "selected_months",
            "selection_window_months",
            "target_dfo_consumption_per_oil_mwh",
            "selected_subset_correlation",
            "factor_target_error",
            "calibration_dfo_consumption",
            "calibration_oil_mwh",
            "dfo_consumption_per_oil_mwh",
            "method",
        ],
    )
    write_dicts(
        DAILY_ESTIMATE_PATH,
        daily_estimates,
        [
            "date",
            "month_start",
            "mida_oil_mwh",
            "ne_oil_mwh",
            "padd1_ne_oil_mwh",
            "calibration_as_of_year",
            "selected_calibration_months",
            "selection_window_months",
            "selected_subset_correlation",
            "factor_target_error",
            "dfo_consumption_per_oil_mwh",
            "estimated_dfo_consumption",
            "source_method",
        ],
    )
    write_dicts(
        DAILY_2026_PATH,
        daily_2026_estimates,
        [
            "date",
            "month_start",
            "mida_oil_mwh",
            "ne_oil_mwh",
            "padd1_ne_oil_mwh",
            "calibration_as_of_year",
            "selected_calibration_months",
            "selection_window_months",
            "selected_subset_correlation",
            "factor_target_error",
            "dfo_consumption_per_oil_mwh",
            "estimated_dfo_consumption",
            "source_method",
        ],
    )
    write_dicts(
        MONTHLY_ESTIMATE_PATH,
        monthly_estimates,
        ["month_start", "daily_rows", "padd1_ne_oil_mwh", "estimated_dfo_consumption", "source_method"],
    )

    manifest = {
        "pipeline_name": "power_generation_dfo",
        "generated_at": utc_now().isoformat(),
        "start_year": START_YEAR,
        "run_start": run_start.isoformat(),
        "run_end": run_end.isoformat(),
        "method": "Monthly PADD 1 DFO facility-fuel consumption is pulled from 2018 forward. Daily MIDA+NE oil generation is used as the proportional indicator. Calibration is recalculated by year using all available months through that year, ignoring calendar month, and selecting 20 high-correlation months whose weighted DFO/MWh factor is closest to the configured target.",
        "aggregation_note": "Facility-fuel raw rows include primeMover=ALL and individual prime movers. Monthly fuel consumption uses primeMover=ALL only to avoid double counting.",
        "calibration": {
            "selected_top_correlated_months": SELECT_TOP_CORRELATED_MONTHS,
            "correlation_window_months": CORRELATION_WINDOW_MONTHS,
            "target_dfo_consumption_per_oil_mwh": TARGET_DFO_MWH_FACTOR,
            "target_factor_candidate_pool_months": TARGET_FACTOR_CANDIDATE_POOL_MONTHS,
            "target_factor_min_correlation": TARGET_FACTOR_MIN_CORRELATION,
            "selection_basis": "local rolling Pearson correlation between monthly PADD 1 DFO consumption and same-month MIDA+NE oil MWh, optimized toward target DFO/MWh factor",
            "current_available_months": len(calibration_months),
            "current_selected_months": len(current_included_months),
            "current_selected_subset_correlation": f"{pearson_correlation(current_included_months):.8f}",
            "current_factor_target_error": f"{weighted_ratio(current_included_months) - TARGET_DFO_MWH_FACTOR:.12f}",
            "current_dfo_consumption_per_oil_mwh": f"{weighted_ratio(current_included_months):.12f}",
            "latest_factor_year": annual_factors[-1]["calibration_as_of_year"] if annual_factors else "",
        },
        "inputs": {
            "facility_fuel_url": FACILITY_FUEL_URL,
            "rto_daily_url": RTO_DAILY_URL,
            "padd1_states": PADD1_STATES,
            "facility_fuels": FACILITY_FUELS,
            "rto_respondents": RTO_RESPONDENTS,
            "timezone": "Central",
        },
        "row_counts": {
            "facility_raw": len(facility_rows),
            "rto_raw": len(rto_rows),
            "monthly_facility": len(monthly_facility),
            "daily_generation": len(daily_generation),
            "calibration_months": len(calibration_months),
            "annual_factors": len(annual_factors),
            "daily_estimates": len(daily_estimates),
            "daily_2026_estimates": len(daily_2026_estimates),
            "monthly_estimates": len(monthly_estimates),
        },
        "outputs": {
            "facility_raw": str(RAW_FACILITY_PATH),
            "rto_raw": str(RAW_RTO_PATH),
            "monthly_facility": str(MONTHLY_FACILITY_PATH),
            "daily_generation": str(DAILY_GENERATION_PATH),
            "calibration_months": str(CALIBRATION_MONTHS_PATH),
            "annual_calibration_factors": str(ANNUAL_FACTORS_PATH),
            "daily_estimates": str(DAILY_ESTIMATE_PATH),
            "daily_2026_estimates": str(DAILY_2026_PATH),
            "monthly_estimates": str(MONTHLY_ESTIMATE_PATH),
            "daily_2026_chart": str(CHART_2026_PATH),
        },
        "sources": [*facility_sources, *rto_sources],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    latest_month = monthly_estimates[0] if monthly_estimates else {}
    print(
        "power_generation_dfo "
        f"start_year={START_YEAR} daily_rows={len(daily_estimates)} "
        f"daily_2026_rows={len(daily_2026_estimates)} "
        f"latest_month={latest_month.get('month_start', '')} "
        f"latest_month_estimated_dfo={latest_month.get('estimated_dfo_consumption', '')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
