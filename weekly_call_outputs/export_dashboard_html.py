#!/usr/bin/env python3
"""Build a portable, single-file Diesel or Jet balance dashboard.

The generated HTML contains the normal dashboard shell, all runtime data chunks,
and the exact portable dashboard state captured by the Export dashboard HTML
button.  It can therefore be opened directly from disk without the local runner
or the rest of the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent
DEFAULT_OUTPUT_ROOT = PACKAGE_DIR / "outputs"
PRODUCT_FOLDERS = {"diesel": "Diesel_Balance", "jet": "Jet_Balance"}
RUNTIME_SUFFIXES = ("base", "weekly", "crude_weekly", "power_dfo", "reference")


class ExportError(RuntimeError):
    """Raised when the standalone dashboard contract cannot be satisfied."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExportError(f"Required file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExportError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExportError(f"Expected a JSON object in {path}.")
    return value


def validate_dashboard_state(value: dict[str, Any], product: str) -> dict[str, Any]:
    if value.get("schema") != "us-balances.dashboard-state" or value.get("schemaVersion") != 1:
        raise ExportError("Dashboard state uses an unsupported schema.")
    if value.get("product") != product:
        raise ExportError(
            f"Dashboard state product {value.get('product')!r} does not match {product!r}."
        )
    if not isinstance(value.get("settings"), dict):
        raise ExportError("Dashboard state settings are missing.")
    view = value.get("view")
    if not isinstance(view, dict) or not isinstance(view.get("state"), dict):
        raise ExportError("Dashboard state view is missing.")
    materialized = value.get("materialized")
    regional = materialized.get("regionalBalance") if isinstance(materialized, dict) else None
    if not isinstance(regional, dict) or not isinstance(regional.get("weekly"), list):
        raise ExportError("Dashboard state adjusted weekly rows are missing.")
    if not isinstance(regional.get("monthly"), list):
        raise ExportError("Dashboard state adjusted monthly rows are missing.")
    return value


def actual_week_ending(snapshot: dict[str, Any]) -> str:
    provenance = snapshot.get("provenance")
    candidate = provenance.get("latestWeekly") if isinstance(provenance, dict) else None
    if isinstance(candidate, str):
        try:
            return date.fromisoformat(candidate[:10]).isoformat()
        except ValueError:
            pass
    materialized = snapshot.get("materialized", {})
    regional = materialized.get("regionalBalance", {}) if isinstance(materialized, dict) else {}
    weeks = regional.get("weekly", []) if isinstance(regional, dict) else []
    actuals = sorted(
        {
            str(row.get("period", ""))[:10]
            for row in weeks
            if isinstance(row, dict) and row.get("status") == "actual"
        }
    )
    if actuals:
        try:
            return date.fromisoformat(actuals[-1]).isoformat()
        except ValueError:
            pass
    raise ExportError("Unable to determine the latest actual week from dashboard state.")


def inline_script(source: str) -> str:
    return re.sub(r"</script", r"<\\/script", source, flags=re.IGNORECASE)


def inline_json(value: Any) -> str:
    # Escaping '<' prevents a note or title containing '</script>' from ending
    # the surrounding script element.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_standalone_html(
    product_root: Path,
    product: str,
    snapshot: dict[str, Any],
) -> str:
    index_path = product_root / "index.html"
    try:
        html = index_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ExportError(f"Dashboard HTML not found: {index_path}") from exc

    runtime_sources: dict[str, str] = {}
    for suffix in RUNTIME_SUFFIXES:
        path = product_root / "data" / f"{product}_balance_runtime_{suffix}.js"
        try:
            runtime_sources[suffix] = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ExportError(f"Dashboard runtime file not found: {path}") from exc

    base_pattern = re.compile(
        rf'<script\s+src=["\']data/{re.escape(product)}_balance_runtime_base\.js(?:\?[^"\']*)?["\']\s*></script>'
    )
    if len(base_pattern.findall(html)) != 1:
        raise ExportError("Expected exactly one dashboard base runtime script tag.")

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    embedded = [
        '<meta name="us-balances-standalone" content="1">',
        f'<meta name="us-balances-standalone-generated-at" content="{generated_at}">',
        "<script>\n" + inline_script(runtime_sources["base"]) + "\n</script>",
    ]
    for suffix in RUNTIME_SUFFIXES[1:]:
        embedded.append("<script>\n" + inline_script(runtime_sources[suffix]) + "\n</script>")
    embedded.append(
        "<script>\n"
        "window.__BALANCE_STANDALONE__=true;\n"
        f"window.__BALANCE_STANDALONE_STATE__={inline_json(snapshot)};\n"
        "</script>"
    )
    html = base_pattern.sub("\n".join(embedded), html, count=1)
    html = html.replace(
        "</title>",
        " — Portable Export</title>",
        1,
    )
    if re.search(r'<script\s+src=["\']data/', html):
        raise ExportError("Standalone HTML still contains a dashboard data script reference.")
    return html


def write_export(
    product: str,
    dashboard_state_path: Path,
    dashboard_root: Path,
    output_root: Path,
) -> tuple[Path, Path, Path]:
    snapshot = validate_dashboard_state(load_json(dashboard_state_path), product)
    product_root = dashboard_root / PRODUCT_FOLDERS[product]
    html = build_standalone_html(product_root, product, snapshot)
    week = actual_week_ending(snapshot)
    filename = f"{product}_export_dashboard.html"
    archive_path = output_root / week / filename
    latest_path = output_root / filename
    atomic_write(archive_path, html)
    atomic_write(latest_path, html)
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": 1,
        "product": product,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "actual_week_ending": week,
        "dashboard_state": str(dashboard_state_path),
        "dashboard_state_fingerprint": snapshot.get("fingerprint"),
        "view": snapshot.get("view", {}).get("state", {}),
        "archive_html": archive_path.name,
        "latest_html": latest_path.name,
        "size_bytes": len(html.encode("utf-8")),
        "sha256": digest,
        "standalone": True,
    }
    manifest_path = archive_path.with_suffix(".manifest.json")
    atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")
    update_output_catalog(output_root, product, week, archive_path, latest_path, manifest_path, manifest)
    return archive_path, latest_path, manifest_path


def update_output_catalog(
    output_root: Path,
    product: str,
    week: str,
    archive_path: Path,
    latest_path: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    catalog_path = output_root / "index.json"
    if catalog_path.is_file():
        catalog = load_json(catalog_path)
    else:
        catalog = {"schema_version": 4, "updated_at": manifest["generated_at"], "weeks": []}
    portable = catalog.get("portable_dashboards")
    if not isinstance(portable, dict):
        portable = {}
    portable[product] = {
        "actual_week_ending": week,
        "latest_html": latest_path.name,
        "archive_html": f"{week}/{archive_path.name}",
        "manifest": f"{week}/{manifest_path.name}",
        "dashboard_state_fingerprint": manifest.get("dashboard_state_fingerprint"),
        "generated_at": manifest["generated_at"],
    }
    catalog["portable_dashboards"] = portable
    catalog["updated_at"] = manifest["generated_at"]
    weeks = catalog.get("weeks")
    if isinstance(weeks, list):
        for entry in weeks:
            if not isinstance(entry, dict):
                continue
            if entry.get("product") == product and entry.get("folder") == week:
                entry["dashboard_html"] = archive_path.name
                entry["dashboard_html_manifest"] = manifest_path.name
    atomic_write(catalog_path, json.dumps(catalog, indent=2) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the exact saved Diesel or Jet dashboard view as one standalone HTML file."
    )
    parser.add_argument("--product", choices=sorted(PRODUCT_FOLDERS), required=True)
    parser.add_argument("--dashboard-state", type=Path, required=True)
    parser.add_argument("--dashboard-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_path, latest_path, manifest_path = write_export(
        args.product,
        args.dashboard_state.resolve(),
        args.dashboard_root.resolve(),
        args.output_dir.resolve(),
    )
    print(f"Created standalone dashboard: {archive_path}")
    print(f"Updated latest standalone dashboard: {latest_path}")
    print(f"Created standalone manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExportError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(2) from exc
