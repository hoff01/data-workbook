from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import os
from typing import Any

import requests

from kpler_config import RuntimeConfig, kpler_authorization_header


DEFAULT_BASE_URL = "https://api.kpler.com/v2/cargo"


def api_base_url() -> str:
    return os.environ.get("KPLER_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@dataclass(frozen=True)
class HttpResponse:
    content: bytes
    status_code: int
    headers: dict[str, str]
    url: str


class KplerHttpClient:
    def __init__(self, config: RuntimeConfig):
        self.base_url = api_base_url()
        self.timeout = (10, 240)
        self.verify = config.verify_tls
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "text/csv",
                "Authorization": kpler_authorization_header(),
                "User-Agent": os.environ.get("KPLER_USER_AGENT", "US-Balances-Kpler-Pull/2.0"),
                "X-Client": "us-balances-kpler-v2",
            }
        )

    def validate_auth(self, flows_params: dict[str, Any] | None = None) -> None:
        source = flows_params or {}
        today = date.today()
        probe_params = {
            key: source[key]
            for key in (
                "flowDirection",
                "split",
                "granularity",
                "fromZones",
                "toZones",
                "products",
                "unit",
                "withIntraCountry",
                "withIntraRegion",
                "withProductEstimation",
            )
            if source.get(key) not in (None, "", [], {})
        }
        probe_params.setdefault("flowDirection", "Import")
        probe_params.setdefault("split", "Total")
        probe_params.setdefault("granularity", "daily")
        probe_params["startDate"] = (today - timedelta(days=7)).isoformat()
        probe_params["endDate"] = today.isoformat()
        probe_params["withForecast"] = "false"
        response = self.session.get(
            f"{self.base_url}/flows",
            params=probe_params,
            verify=self.verify,
            timeout=self.timeout,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(f"Kpler Flows authentication failed: HTTP {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"Kpler Flows access validation failed: HTTP {response.status_code}: {response.text[:500]}")

    def get(self, resource: str, params: dict[str, Any]) -> HttpResponse:
        filtered = {key: value for key, value in params.items() if value not in (None, "", [], {})}
        response = self.session.get(
            f"{self.base_url}/{resource.lstrip('/')}",
            params=filtered,
            stream=True,
            verify=self.verify,
            timeout=self.timeout,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(f"Kpler authentication failed on {resource}: HTTP {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"Kpler {resource} request failed: HTTP {response.status_code}: {response.text[:500]}")
        return HttpResponse(
            content=response.content,
            status_code=response.status_code,
            headers={key: value for key, value in response.headers.items()},
            url=response.url,
        )
