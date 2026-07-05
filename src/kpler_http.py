from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from kpler_config import RuntimeConfig, credential_pair


BASE_URL = "https://api.kpler.com/v1"


@dataclass(frozen=True)
class HttpResponse:
    content: bytes
    status_code: int
    headers: dict[str, str]
    url: str


class KplerHttpClient:
    def __init__(self, config: RuntimeConfig):
        email, password = credential_pair()
        self.auth = HTTPBasicAuth(email, password)
        self.timeout = (10, 240)
        self.verify = config.verify_tls
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
                "User-Agent": os.environ.get("KPLER_USER_AGENT", "US-Balances-Kpler-Pull/1.0"),
                "X-Client": "python-pulls-kpler-direct",
            }
        )

    def validate_auth(self) -> None:
        response = self.session.get(
            f"{BASE_URL}/trades/columns",
            auth=self.auth,
            verify=self.verify,
            timeout=self.timeout,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(f"Kpler authentication failed: HTTP {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"Kpler auth validation failed: HTTP {response.status_code}: {response.text[:500]}")

    def get(self, resource: str, params: dict[str, Any]) -> HttpResponse:
        filtered = {key: value for key, value in params.items() if value not in (None, "", [], {})}
        response = self.session.get(
            f"{BASE_URL}/{resource}",
            params=filtered,
            auth=self.auth,
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
