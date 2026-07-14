from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kpler_config import PullSpec, RuntimeConfig, kpler_api_key, kpler_authorization_header  # noqa: E402
from kpler_http import KplerHttpClient  # noqa: E402
from kpler_pull import parse_args, run, spec_to_kpler_params  # noqa: E402
from kpler_transform import kpler_content_to_long  # noqa: E402


def runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 1),
        snapshot_date=None,
        only_realized=False,
        with_forecast=True,
        with_intra_region=True,
        with_freight_view=False,
        with_product_estimation=False,
        unit="kbd",
        granularity="monthly",
        concurrency=1,
        retry_count=1,
        retry_backoff_seconds=0,
        verify_tls=True,
    )


def pull_spec(*, only_realized: bool = False) -> PullSpec:
    return PullSpec(
        name="test_imports",
        family="balance_guides",
        geography="us",
        commodity="diesel",
        kpler_product="Gasoil/Diesel",
        flow_direction="import",
        split=["origin countries"],
        from_zones=None,
        to_zones=["United States"],
        with_intra_country=False,
        with_intra_region=True,
        with_forecast=True,
        only_realized=only_realized,
        unit="kbd",
        granularity="monthly",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 1),
    )


class KplerV2Tests(unittest.TestCase):
    def test_api_key_accepts_raw_or_complete_basic_value(self) -> None:
        with patch.dict(os.environ, {"KPLER_API_KEY": "sample-key", "KPLER_API_V2_BASIC_AUTH": ""}):
            self.assertEqual(kpler_api_key(), "sample-key")
            self.assertEqual(kpler_authorization_header(), "Basic sample-key")
        with patch.dict(os.environ, {"KPLER_API_KEY": "", "KPLER_API_V2_BASIC_AUTH": "Basic sample-key"}):
            self.assertEqual(kpler_api_key(), "sample-key")
            self.assertEqual(kpler_authorization_header(), "Basic sample-key")

    def test_v2_flow_parameters_use_current_contract(self) -> None:
        params = spec_to_kpler_params(pull_spec(only_realized=True))
        self.assertEqual(params["flowDirection"], "Import")
        self.assertEqual(params["split"], "originCountries")
        self.assertEqual(params["tradeStatus"], "delivered")
        self.assertNotIn("onlyRealized", params)
        self.assertNotIn("withFreightView", params)
        self.assertNotIn("snapshotDate", params)

    def test_snapshot_date_fails_instead_of_being_silently_ignored(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not supported"):
            spec_to_kpler_params(pull_spec(), snapshot_date=date(2026, 1, 15))

    def test_v2_semicolon_csv_normalizes_period_quantity_and_split(self) -> None:
        content = b"period;originCountries;quantity;unit\n2026-01-01;Canada;10.5;kbd\n"
        row = kpler_content_to_long(content, pull_spec()).row(0, named=True)
        self.assertEqual(row["date"], "2026-01-01")
        self.assertEqual(row["origin_country"], "Canada")
        self.assertEqual(row["value_kbd"], 10.5)

    def test_v2_plural_trading_region_column_normalizes(self) -> None:
        spec = replace(pull_spec(), split=["destination trading regions"])
        content = b"period;destinationTradingRegions;quantity\n2026-01-01;Asia;7.25\n"
        row = kpler_content_to_long(content, spec).row(0, named=True)
        self.assertEqual(row["destination_trading_region"], "Asia")

    def test_v2_client_uses_basic_header_and_flows_scoped_preflight(self) -> None:
        response = Mock(status_code=200, text="ok")
        with patch.dict(
            os.environ,
            {
                "KPLER_API_V2_BASIC_AUTH": "Basic sample-key",
                "KPLER_API_KEY": "",
                "KPLER_API_BASE_URL": "https://api.kpler.com/v2/cargo/",
            },
        ):
            client = KplerHttpClient(runtime_config())
            client.session.get = Mock(return_value=response)
            client.validate_auth(spec_to_kpler_params(pull_spec()))
        self.assertEqual(client.session.headers["Authorization"], "Basic sample-key")
        self.assertEqual(client.session.get.call_args.args[0], "https://api.kpler.com/v2/cargo/flows")
        params = client.session.get.call_args.kwargs["params"]
        self.assertEqual(params["flowDirection"], "Import")
        self.assertEqual(params["split"], "originCountries")
        self.assertEqual(params["granularity"], "monthly")
        self.assertEqual(params["products"], "Gasoil/Diesel")
        self.assertEqual(params["withForecast"], "false")
        self.assertLess(params["startDate"], params["endDate"])

    def test_auth_check_uses_configured_key_without_running_full_pull(self) -> None:
        client = Mock()
        with (
            patch.dict(os.environ, {"KPLER_API_KEY": "sample-key", "KPLER_API_V2_BASIC_AUTH": ""}),
            patch("kpler_pull.KplerHttpClient", return_value=client),
        ):
            exit_code = run(parse_args(["--check-auth"]))
        self.assertEqual(exit_code, 0)
        client.validate_auth.assert_called_once()


if __name__ == "__main__":
    unittest.main()
