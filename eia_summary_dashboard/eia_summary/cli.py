from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .data_load import load_raw, scan_weeks
from .emailer import (
    build_email,
    create_apple_mail_draft,
    create_outlook_draft,
    crop_header_strip,
    read_recipients,
    send_apple_mail,
    try_send,
    write_email_html,
    write_eml,
)
from .metrics import build_rows, dependency_source_columns
from .paths import ROOT, ensure_dirs, inside_root
from .render_pdf import render_pdf
from .refresh_weekly import refresh_weekly_data, refresh_wpsr_latest_data
from .series_map import ensure_series_map, write_inventory
from .validate import render_png, sha256, validate_boxes, validate_pdf


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build self-contained EIA weekly dashboard PDF.")
    p.add_argument("--week", default="latest", help="latest or YYYY-MM-DD")
    p.add_argument("--all-weeks", action="store_true")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--write-series-inventory", action="store_true")
    p.add_argument("--raw-archive", default="raw.csv.tar.xz")
    p.add_argument("--reference-pdf", default="reference/dashboard.pdf")
    p.add_argument("--refresh-from-weekly")
    p.add_argument("--refresh-eia-weekly", action="store_true", help="Use cached EIA history, overlay WPSR CSV, and regenerate local raw.csv.tar.xz and series.csv; add --force to redownload historical workbooks")
    p.add_argument("--refresh-eia-latest", "--refresh-eia-json", dest="refresh_eia_latest", action="store_true", help="Overlay the latest two WPSR CSV weeks onto the existing local raw archive")
    p.add_argument("--skip-email", action="store_true", help="Do not write the email-ready .eml file")
    p.add_argument("--send-email", action="store_true", help="Send email after building; requires configured SMTP or sendmail")
    p.add_argument("--draft-email", action="store_true", help="Open an email draft after building; tries Outlook then Apple Mail by default")
    p.add_argument("--email-recipients", default="email_recipients.txt")
    p.add_argument("--email-mode", action="append", choices=["smtp", "sendmail", "mail"], help="Email send fallback mode; can be repeated")
    p.add_argument("--draft-mode", action="append", choices=["outlook", "mail"], help="Email draft fallback mode; can be repeated")
    return p.parse_args()


def _refresh(src_dir: str) -> None:
    src = Path(src_dir).resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    shutil.copy2(src / "raw.csv.tar.xz", inside_root(ROOT / "raw.csv.tar.xz"))
    shutil.copy2(src / "series.csv", inside_root(ROOT / "series.csv"))
    shutil.copy2(src / "dashboard.pdf", inside_root(ROOT / "reference" / "dashboard.pdf"))


def _write_manifest_row(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["week_ending", "release_date", "output_pdf", "raw_archive_sha256", "series_count", "generated_at_utc", "bytes"]
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="") as f:
            existing = [r for r in csv.DictReader(f) if r.get("week_ending") != row["week_ending"]]
    existing.append(row)
    existing.sort(key=lambda r: r["week_ending"])
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing)


def _raw_row_count(raw_archive: Path) -> int:
    meta_path = raw_archive.with_name(raw_archive.name + ".meta.json")
    if meta_path.exists():
        return int(json.loads(meta_path.read_text(encoding="utf-8"))["rows"])
    _weeks, _release_dates, raw_rows = scan_weeks(raw_archive)
    return raw_rows


def _build_week(week, args, definitions, raw_archive: Path, dataset) -> tuple[Path, dict[str, str]]:
    if week not in dataset.weeks:
        raise ValueError(f"week {week} not present in local raw archive")
    rows = build_rows(dataset, definitions, week)
    release_date = dataset.release_dates.get(week, "")
    out = inside_root(ROOT / "archive" / f"EIA_SUMMARY_{week.isoformat()}.pdf")
    boxes = render_pdf(out, rows, week, release_date)
    latest = inside_root(ROOT / "output" / "latest.pdf")
    if week == dataset.weeks[-1]:
        shutil.copy2(out, latest)
    validate_pdf(out)
    clipped, overlaps = validate_boxes(boxes)
    if clipped:
        raise ValueError(f"visual validation failed: clipped text boxes={clipped}")
    # The drawn dashboard is very dense; fail only on large overlaps once renderer has card bounds.
    if overlaps > 25:
        raise ValueError(f"visual validation failed: text overlap count={overlaps}")
    latest_png = inside_root(ROOT / "output" / "latest.png")
    if week == dataset.weeks[-1]:
        render_png(latest, latest_png)
    row = {
        "week_ending": week.isoformat(),
        "release_date": release_date,
        "output_pdf": str(out.relative_to(ROOT)),
        "raw_archive_sha256": sha256(raw_archive),
        "series_count": str(len(definitions)),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "bytes": str(out.stat().st_size),
    }
    return out, row


def main() -> None:
    start = time.perf_counter()
    args = _parse_args()
    ensure_dirs()
    if args.refresh_from_weekly:
        _refresh(args.refresh_from_weekly)
    if args.refresh_eia_weekly:
        refreshed_rows, refreshed_series, refreshed_week = refresh_weekly_data(ROOT, force_history=args.force)
        print(f"refreshed_eia_weekly_week={refreshed_week}")
        print(f"refreshed_eia_weekly_rows={refreshed_rows}")
        print(f"refreshed_eia_weekly_series={refreshed_series}")
    if args.refresh_eia_latest:
        refreshed_rows, refreshed_series, refreshed_week = refresh_wpsr_latest_data(ROOT)
        print(f"refreshed_eia_latest_week={refreshed_week}")
        print(f"refreshed_eia_latest_rows={refreshed_rows}")
        print(f"refreshed_eia_latest_series={refreshed_series}")

    raw_archive = inside_root((ROOT / args.raw_archive).resolve() if not Path(args.raw_archive).is_absolute() else Path(args.raw_archive))
    series_path = inside_root(ROOT / "series.csv")
    if args.write_series_inventory:
        write_inventory(series_path, inside_root(ROOT / "output" / "series_inventory.csv"))

    definitions = ensure_series_map(inside_root(ROOT / "config" / "series_map.csv"), series_path)
    selected = dependency_source_columns(definitions)
    dataset = load_raw(raw_archive, selected)
    if not dataset.weeks:
        raise ValueError("no weekly rows in local raw archive")
    raw_rows = _raw_row_count(raw_archive)
    target_weeks = dataset.weeks if args.all_weeks else [dataset.weeks[-1] if args.week == "latest" else datetime.strptime(args.week, "%Y-%m-%d").date()]

    manifest_rows = []
    outputs = []
    for week in target_weeks:
        out, row = _build_week(week, args, definitions, raw_archive, dataset)
        outputs.append(out)
        manifest_rows.append(row)
        _write_manifest_row(inside_root(ROOT / "archive" / "manifest.csv"), row)

    final_pdf = outputs[-1]
    final_week = target_weeks[-1]
    email_eml = None
    email_html = None
    if not args.skip_email:
        email_png = inside_root(ROOT / "output" / f"EIA_SUMMARY_{final_week.isoformat()}.png")
        render_png(final_pdf, email_png)
        header_png = inside_root(ROOT / "output" / f"EIA_SUMMARY_{final_week.isoformat()}_email_header.png")
        crop_header_strip(email_png, header_png)
        recipients = read_recipients(inside_root(ROOT / args.email_recipients))
        email_html = inside_root(ROOT / "output" / f"DOE_Summary_WE_{final_week.isoformat()}.html")
        write_email_html(
            week=final_week.isoformat(),
            header_png_path=header_png,
            full_png_path=email_png,
            output_path=email_html,
        )
        msg = build_email(
            week=final_week.isoformat(),
            recipients=recipients,
            pdf_path=final_pdf,
            full_png_path=email_png,
            header_png_path=header_png,
        )
        email_eml = inside_root(ROOT / "output" / f"DOE_Summary_WE_{final_week.isoformat()}.eml")
        write_eml(msg, email_eml)
        if args.send_email:
            modes = args.email_mode or ["smtp", "mail", "sendmail"]
            sent_mode = None
            send_errors = []
            subject = f"DOE Summary W/E {final_week.isoformat()}"
            for mode in modes:
                try:
                    if mode in {"smtp", "sendmail"}:
                        sent_mode = try_send(msg, recipients, [mode])
                    elif mode == "mail":
                        send_apple_mail(
                            recipients=recipients,
                            subject=subject,
                            week=final_week.isoformat(),
                            pdf_path=final_pdf,
                        )
                        sent_mode = "mail"
                    else:
                        raise RuntimeError(f"unsupported email mode: {mode}")
                    break
                except Exception as exc:  # noqa: BLE001 - keep app fallback available
                    send_errors.append(f"{mode}: {exc}")
            if sent_mode is None:
                raise RuntimeError("; ".join(send_errors))
            print(f"email_sent_mode={sent_mode}")
        if args.draft_email:
            draft_errors = []
            subject = f"DOE Summary W/E {final_week.isoformat()}"
            for mode in args.draft_mode or ["outlook", "mail"]:
                try:
                    if mode == "outlook":
                        create_outlook_draft(recipients=recipients, subject=subject, html_path=email_html, pdf_path=final_pdf)
                    else:
                        create_apple_mail_draft(recipients=recipients, subject=subject, html_path=email_html, pdf_path=final_pdf)
                    print(f"email_draft_mode={mode}")
                    break
                except Exception as exc:  # noqa: BLE001 - collect fallback errors for CLI output
                    draft_errors.append(f"{mode}: {exc}")
            else:
                raise RuntimeError("; ".join(draft_errors))

    if args.validate:
        ref_pdf = inside_root(ROOT / args.reference_pdf)
        validate_pdf(ref_pdf)
        render_png(ref_pdf, inside_root(ROOT / "reference" / "dashboard.png"))
        for out in outputs:
            validate_pdf(out)

    elapsed = int((time.perf_counter() - start) * 1000)
    latest_week = target_weeks[-1]
    print(f"validated_week={latest_week.isoformat()}")
    print(f"raw_rows={raw_rows}")
    print(f"mapped_series={len(definitions)}")
    print(f"pdf={outputs[-1].relative_to(ROOT)}")
    print(f"latest_pdf=output/latest.pdf")
    print(f"latest_png=output/latest.png")
    if email_eml is not None:
        print(f"email_eml={email_eml.relative_to(ROOT)}")
    if email_html is not None:
        print(f"email_html={email_html.relative_to(ROOT)}")
    print(f"elapsed_ms={elapsed}")
