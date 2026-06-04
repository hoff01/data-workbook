from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import os
from pathlib import Path
from typing import Any

import yaml


BASE_DIR = Path("Kpler")
CONFIG_DIR = BASE_DIR / "config"
RAW_DIR = BASE_DIR / "raw" / "daily"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
ARCHIVE_DIR = BASE_DIR / "archive"


@dataclass(frozen=True)
class RuntimeConfig:
    start_date: date
    end_date: date
    snapshot_date: date | None
    only_realized: bool
    with_forecast: bool
    with_intra_region: bool
    with_freight_view: bool
    with_product_estimation: bool
    unit: str
    granularity: str
    concurrency: int
    retry_count: int
    retry_backoff_seconds: float
    verify_tls: bool


@dataclass(frozen=True)
class PullSpec:
    name: str
    family: str
    geography: str
    commodity: str
    kpler_product: str
    flow_direction: str
    split: list[str]
    from_zones: list[str] | None
    to_zones: list[str] | None
    with_intra_country: bool
    with_intra_region: bool
    with_forecast: bool
    only_realized: bool
    unit: str
    granularity: str
    start_date: date
    end_date: date
    region_detail: str = ""
    route_group: str = ""

    def manifest_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = yaml.safe_load(file)
    return payload or {}


def parse_date(value: str | None, default: date) -> date:
    if not value:
        return default
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def runtime_config() -> RuntimeConfig:
    pull_config = load_yaml(CONFIG_DIR / "pull_sets.yml")
    defaults = pull_config["defaults"]
    today = date.today()
    default_end_date = today + timedelta(days=int(os.environ.get("KPLER_FORWARD_DAYS", "45")))
    return RuntimeConfig(
        start_date=parse_date(os.environ.get("KPLER_START_DATE"), parse_date(defaults["start_date"], date(2018, 1, 1))),
        end_date=parse_date(os.environ.get("KPLER_END_DATE"), default_end_date),
        snapshot_date=parse_date(os.environ.get("KPLER_SNAPSHOT_DATE"), today) if os.environ.get("KPLER_SNAPSHOT_DATE") else None,
        only_realized=parse_bool(os.environ.get("KPLER_ONLY_REALIZED"), bool(defaults["only_realized"])),
        with_forecast=parse_bool(os.environ.get("KPLER_WITH_FORECAST"), bool(defaults["with_forecast"])),
        with_intra_region=parse_bool(os.environ.get("KPLER_WITH_INTRA_REGION"), bool(defaults["with_intra_region"])),
        with_freight_view=parse_bool(os.environ.get("KPLER_WITH_FREIGHT_VIEW"), bool(defaults["with_freight_view"])),
        with_product_estimation=parse_bool(os.environ.get("KPLER_WITH_PRODUCT_ESTIMATION"), bool(defaults["with_product_estimation"])),
        unit=str(defaults["unit"]),
        granularity=str(defaults["granularity"]),
        concurrency=max(1, int(os.environ.get("KPLER_CONCURRENCY", "2"))),
        retry_count=max(1, int(os.environ.get("KPLER_RETRY_COUNT", "3"))),
        retry_backoff_seconds=float(os.environ.get("KPLER_RETRY_BACKOFF_SECONDS", "10")),
        verify_tls=parse_bool(os.environ.get("KPLER_VERIFY_TLS"), True),
    )


def ensure_directories() -> None:
    for path in [
        CONFIG_DIR,
        RAW_DIR / "external",
        RAW_DIR / "domestic_padd",
        OUTPUT_DIR / "daily",
        OUTPUT_DIR / "weekly",
        OUTPUT_DIR / "monthly",
        LOG_DIR,
        ARCHIVE_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def build_pull_specs(config: RuntimeConfig) -> list[PullSpec]:
    products = load_yaml(CONFIG_DIR / "products.yml")["products"]
    regions = load_yaml(CONFIG_DIR / "regions.yml")
    pull_sets = load_yaml(CONFIG_DIR / "pull_sets.yml")
    external = pull_sets["external"]
    domestic = pull_sets["domestic_padd"]

    specs: list[PullSpec] = []
    for commodity, product in products.items():
        kpler_product = product["kpler_product"]
        specs.append(
            PullSpec(
                name=f"us_{commodity}_imports",
                family="external",
                geography="us",
                commodity=commodity,
                kpler_product=kpler_product,
                flow_direction="import",
                split=list(external["us_import_splits"]),
                from_zones=None,
                to_zones=[external["us_zone"]],
                with_intra_country=bool(external["with_intra_country"]),
                with_intra_region=config.with_intra_region,
                with_forecast=config.with_forecast,
                only_realized=config.only_realized,
                unit=config.unit,
                granularity=config.granularity,
                start_date=config.start_date,
                end_date=config.end_date,
            )
        )
        specs.append(
            PullSpec(
                name=f"us_{commodity}_exports",
                family="external",
                geography="us",
                commodity=commodity,
                kpler_product=kpler_product,
                flow_direction="export",
                split=list(external["us_export_splits"]),
                from_zones=[external["us_zone"]],
                to_zones=None,
                with_intra_country=bool(external["with_intra_country"]),
                with_intra_region=config.with_intra_region,
                with_forecast=config.with_forecast,
                only_realized=config.only_realized,
                unit=config.unit,
                granularity=config.granularity,
                start_date=config.start_date,
                end_date=config.end_date,
            )
        )

        for region_key, region in regions["europe_regions"].items():
            countries = list(region["countries"])
            specs.append(
                PullSpec(
                    name=f"europe_{region_key}_{commodity}_imports",
                    family="external",
                    geography="europe",
                    commodity=commodity,
                    kpler_product=kpler_product,
                    flow_direction="import",
                    split=list(external["europe_import_splits"]),
                    from_zones=None,
                    to_zones=countries,
                    with_intra_country=bool(external["with_intra_country"]),
                    with_intra_region=config.with_intra_region,
                    with_forecast=config.with_forecast,
                    only_realized=config.only_realized,
                    unit=config.unit,
                    granularity=config.granularity,
                    start_date=config.start_date,
                    end_date=config.end_date,
                    region_detail=region_key,
                )
            )
            specs.append(
                PullSpec(
                    name=f"europe_{region_key}_{commodity}_exports",
                    family="external",
                    geography="europe",
                    commodity=commodity,
                    kpler_product=kpler_product,
                    flow_direction="export",
                    split=list(external["europe_export_splits"]),
                    from_zones=countries,
                    to_zones=None,
                    with_intra_country=bool(external["with_intra_country"]),
                    with_intra_region=config.with_intra_region,
                    with_forecast=config.with_forecast,
                    only_realized=config.only_realized,
                    unit=config.unit,
                    granularity=config.granularity,
                    start_date=config.start_date,
                    end_date=config.end_date,
                    region_detail=region_key,
                )
            )

        specs.append(
            PullSpec(
                name=f"domestic_padd_{commodity}",
                family="domestic_padd",
                geography="us",
                commodity=commodity,
                kpler_product=kpler_product,
                flow_direction=str(domestic["flow_direction"]),
                split=list(domestic["splits"]),
                from_zones=list(domestic["from_zones"]),
                to_zones=list(domestic["to_zones"]),
                with_intra_country=bool(domestic["with_intra_country"]),
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


def credential_pair() -> tuple[str, str]:
    email = os.environ.get("KPLER_EMAIL") or os.environ.get("KPLER_USERNAME") or ""
    password = os.environ.get("KPLER_PASSWORD") or ""
    if not email or not password:
        raise RuntimeError("Missing Kpler credentials. Set KPLER_EMAIL and KPLER_PASSWORD.")
    return email, password
