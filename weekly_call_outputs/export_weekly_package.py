#!/usr/bin/env python3
"""Export one complete weekly workbook package from the saved dashboard state."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export weekly JSON, table, charts, and portable dashboard HTML."
    )
    parser.add_argument("--product", choices=["diesel", "jet"], required=True)
    parser.add_argument("--dashboard-state", type=Path, required=True)
    parser.add_argument("--dashboard-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_DIR / "outputs")
    parser.add_argument(
        "--sharepoint-config",
        type=Path,
        default=ROOT / "config" / "sharepoint_weekly_export.json",
    )
    return parser.parse_args()


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        raise RuntimeError(
            f"Weekly package step failed with exit code {completed.returncode}: {' '.join(command)}"
        )


def main() -> int:
    args = parse_args()
    product = args.product
    dashboard_state = args.dashboard_state.resolve()
    dashboard_root = args.dashboard_root.resolve()
    output_dir = args.output_dir.resolve()
    sharepoint_config = args.sharepoint_config.resolve()
    run(
        [
            sys.executable,
            str(PACKAGE_DIR / "export_dashboard_html.py"),
            "--product",
            product,
            "--dashboard-state",
            str(dashboard_state),
            "--dashboard-root",
            str(dashboard_root),
            "--output-dir",
            str(output_dir),
        ]
    )
    run(
        [
            sys.executable,
            str(PACKAGE_DIR / "generate_weekly_images.py"),
            "--product",
            product,
            "--dashboard-state",
            str(dashboard_state),
            "--balance-root",
            str(dashboard_root),
            "--output-dir",
            str(output_dir),
            "--sharepoint-config",
            str(sharepoint_config),
        ]
    )
    print(
        f"{product.title()} weekly forecast package and portable dashboard were saved."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
