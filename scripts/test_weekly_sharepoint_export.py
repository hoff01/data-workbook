#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "weekly_call_outputs" / "generate_weekly_images.py"
SPEC = importlib.util.spec_from_file_location("weekly_images_sharepoint", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
weekly_images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(weekly_images)


with TemporaryDirectory() as temporary_directory:
    temporary = Path(temporary_directory)
    output_dir = temporary / "local" / "2026-08-21"
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True)
    payload_path = output_dir / "diesel_weekly_stats.json"
    payload_path.write_text(
        json.dumps({"periods": [{"week_ending": "2026-08-21"}]}) + "\n",
        encoding="utf-8",
    )
    state_path = output_dir / "diesel_dashboard_state.json"
    state_path.write_text('{"schema":"us-balances.dashboard-state"}\n', encoding="utf-8")
    manifest_path = output_dir / "diesel_manifest.json"
    manifest_path.write_text('{"product":"diesel"}\n', encoding="utf-8")
    dashboard_html_path = output_dir / "diesel_export_dashboard.html"
    dashboard_html_path.write_text("<html>portable diesel</html>\n", encoding="utf-8")
    dashboard_html_manifest_path = output_dir / "diesel_export_dashboard.manifest.json"
    dashboard_html_manifest_path.write_text('{"standalone":true}\n', encoding="utf-8")
    table_path = output_dir / "diesel_weekly_balance_table.png"
    table_path.write_bytes(b"table-image")
    chart_paths = [charts_dir / "diesel_eia_actuals.png"] + [
        charts_dir / f"diesel_forecast_week_{index}.png" for index in range(1, 6)
    ]
    for index, chart_path in enumerate(chart_paths):
        chart_path.write_bytes(f"chart-{index}".encode("utf-8"))
    sharepoint_root = temporary / "sharepoint"
    config_path = temporary / "sharepoint-config.json"
    config_path.write_text(
        json.dumps(
            {
                "root_path": str(sharepoint_root),
                "product_folders": {"diesel": "Diesel", "jet": "Jet"},
                "charts_folder": "charts",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stale_product_dir = sharepoint_root / "Diesel"
    (stale_product_dir / "charts").mkdir(parents=True)
    (stale_product_dir / table_path.name).write_bytes(b"stale-table")
    (stale_product_dir / dashboard_html_path.name).write_text("stale html\n", encoding="utf-8")
    (stale_product_dir / "charts" / chart_paths[0].name).write_bytes(b"stale-chart")
    published = weekly_images.publish_sharepoint_export(
        config_path,
        "diesel",
        payload_path,
        manifest_path,
        [table_path, *chart_paths],
    )
    assert published == sharepoint_root / "Diesel"
    assert (sharepoint_root / "Diesel").is_dir()
    assert (sharepoint_root / "Jet").is_dir(), "both product folders must be created"
    assert (published / table_path.name).read_bytes() == b"table-image"
    assert (published / payload_path.name).is_file()
    assert (published / state_path.name).is_file()
    assert (published / manifest_path.name).is_file()
    assert (published / dashboard_html_path.name).read_text(encoding="utf-8") == dashboard_html_path.read_text(encoding="utf-8")
    assert (published / dashboard_html_manifest_path.name).is_file()
    for source in chart_paths:
        assert (published / "charts" / source.name).read_bytes() == source.read_bytes()
    latest = json.loads((published / "latest_weekly_export.json").read_text(encoding="utf-8"))
    assert latest["actual_week_ending"] == "2026-08-21"
    assert latest["dashboard_html"] == dashboard_html_path.name
    assert latest["inventory_charts"] == [path.name for path in chart_paths]

print("weekly SharePoint export contract ok")
