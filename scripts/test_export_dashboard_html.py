#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "weekly_call_outputs" / "export_dashboard_html.py"
SPEC = importlib.util.spec_from_file_location("export_dashboard_html", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def dashboard_state_fixture(product: str) -> dict[str, object]:
    latest_weekly = "2026-07-10"
    return {
        "schema": "us-balances.dashboard-state",
        "schemaVersion": 1,
        "id": f"{product}-standalone-export-test",
        "product": product,
        "savedAt": "2026-07-15T12:00:00Z",
        "fingerprint": f"{product}-standalone-export-fingerprint",
        "provenance": {"latestWeekly": latest_weekly},
        "settings": {},
        "view": {
            "state": {
                "sheet": "charts",
                "frequency": "monthly",
            }
        },
        "materialized": {
            "regionalBalance": {
                "monthly": [],
                "weekly": [
                    {
                        "period": latest_weekly,
                        "status": "actual",
                        "regionKey": "us",
                    }
                ],
            }
        },
    }


for product in ("diesel", "jet"):
    with TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        state_path = temporary_root / f"{product}_balance.json"
        snapshot = dashboard_state_fixture(product)
        state_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        output_root = temporary_root / "outputs"
        archive_path, latest_path, manifest_path = exporter.write_export(
            product,
            state_path,
            ROOT,
            output_root,
        )
        assert archive_path.is_file()
        assert latest_path.is_file()
        assert manifest_path.is_file()
        html = archive_path.read_text(encoding="utf-8")
        assert html == latest_path.read_text(encoding="utf-8")
        assert '<meta name="us-balances-standalone" content="1">' in html
        assert "window.__BALANCE_STANDALONE__=true" in html
        assert "window.__BALANCE_STANDALONE_STATE__=" in html
        assert "applyStandaloneDashboardState(STANDALONE_DASHBOARD_STATE)" in html
        assert '<script src="data/' not in html
        assert "window.BALANCE_DATA" in html
        for chunk in ("weekly", "crudeWeekly", "powerDfo", "reference"):
            assert f").{chunk} = " in html
        assert len(html.encode("utf-8")) > 4_000_000
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["product"] == product
        assert manifest["standalone"] is True
        assert manifest["dashboard_state_fingerprint"] == snapshot["fingerprint"]
        assert manifest["view"] == snapshot["view"]["state"]
        assert manifest["size_bytes"] == len(html.encode("utf-8"))
        catalog = json.loads((output_root / "index.json").read_text(encoding="utf-8"))
        portable = catalog["portable_dashboards"][product]
        assert portable["latest_html"] == f"{product}_export_dashboard.html"
        assert portable["archive_html"] == f"{archive_path.parent.name}/{archive_path.name}"
        assert portable["dashboard_state_fingerprint"] == snapshot["fingerprint"]

print("standalone dashboard HTML contract ok")
