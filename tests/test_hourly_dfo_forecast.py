import json
import urllib.error
from unittest.mock import patch

import pytest

from power_generation_dfo import hourly_dfo_forecast as dfo


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_nws_request_retries_transient_500_then_succeeds():
    attempts = []

    def urlopen(request, timeout):
        attempts.append((request, timeout))
        if len(attempts) < 3:
            raise urllib.error.HTTPError(request.full_url, 500, "Internal Server Error", {}, None)
        return StubResponse({"properties": {"periods": []}})

    with (
        patch.object(dfo.urllib.request, "urlopen", side_effect=urlopen),
        patch.object(dfo, "NWS_RETRY_COUNT", 4),
        patch.object(dfo, "NWS_RETRY_BACKOFF_SECONDS", 0),
        patch.object(dfo, "NWS_RETRY_MAX_BACKOFF_SECONDS", 0),
    ):
        payload = dfo.request_json_url("https://api.weather.gov/example")

    assert payload == {"properties": {"periods": []}}
    assert len(attempts) == 3
    assert attempts[0][0].get_header("User-agent") == dfo.NWS_USER_AGENT
    assert attempts[0][1] == 90


def test_weather_refresh_continues_when_one_city_remains_unavailable(capsys):
    points = {
        "failed_city": ("FC", "Failed City", 1.0, -1.0),
        "working_city": ("WC", "Working City", 2.0, -2.0),
    }

    def forecast_url(lat, _lon):
        return f"https://api.weather.gov/gridpoints/test/{lat:.1f}"

    def request_json_url(url, headers=None):
        if url.endswith("/1.0"):
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)
        return {
            "properties": {
                "periods": [
                    {"startTime": "2026-08-10T00:00:00+00:00", "temperature": 70},
                    {"startTime": "2026-08-10T01:00:00+00:00", "temperature": 68},
                ]
            }
        }

    with (
        patch.object(dfo, "WEATHER_POINTS", points),
        patch.object(dfo, "WEATHER_DAYS", 1),
        patch.object(dfo, "point_forecast_url", side_effect=forecast_url),
        patch.object(dfo, "request_json_url", side_effect=request_json_url),
    ):
        rows, sources = dfo.fetch_weather_hourly()

    assert len(rows) == 24
    assert rows[0]["avg_temperature_f"] == "70.00"
    assert rows[0]["failed_city_temperature_f"] == ""
    assert rows[0]["working_city_temperature_f"] == "70.00"
    assert [source["status"] for source in sources] == ["unavailable", "ok"]
    assert "NWS city unavailable city=failed_city" in capsys.readouterr().err


def test_weather_refresh_fails_when_every_city_is_unavailable():
    points = {"failed_city": ("FC", "Failed City", 1.0, -1.0)}

    with (
        patch.object(dfo, "WEATHER_POINTS", points),
        patch.object(dfo, "point_forecast_url", side_effect=urllib.error.HTTPError("https://api.weather.gov/points/test", 500, "Internal Server Error", {}, None)),
    ):
        with pytest.raises(RuntimeError, match="unavailable for all configured cities after retries"):
            dfo.fetch_weather_hourly()
