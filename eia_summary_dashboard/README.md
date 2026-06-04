# EIA Weekly Summary Dashboard

Self-contained PDF dashboard generator for the local EIA weekly archive.

## Build Latest Week

```bash
python3 build.py --week latest --validate
```

Outputs:

```text
archive/EIA_SUMMARY_YYYY-MM-DD.pdf
output/latest.pdf
output/latest.png
output/DOE_Summary_WE_YYYY-MM-DD.eml
output/DOE_Summary_WE_YYYY-MM-DD.html
archive/manifest.csv
```

The current local archive builds:

```text
archive/EIA_SUMMARY_2026-05-08.pdf
output/latest.pdf
output/latest.png
output/DOE_Summary_WE_2026-05-08.eml
output/DOE_Summary_WE_2026-05-08.html
```

## Update Local Data

For the normal scheduled update, overlay the latest two WPSR CSV weeks onto the existing historical archive, then build:

```bash
python3 build.py --refresh-eia-latest --week latest --validate
```

To rebuild from the cached historical archive, overlay the latest two weeks from WPSR CSV, regenerate `raw.csv.tar.xz` and `series.csv`, then build:

```bash
python3 build.py --refresh-eia-weekly --week latest --validate
```

The historical caches live under `cache/`: downloaded `.xls` workbooks, a pure historical raw archive, and the last WPSR CSV signature. Historical parsing uses Polars with the calamine/fastexcel engine and keeps data from 2016 onward. Use `--force --refresh-eia-weekly` only when you intentionally want to redownload all EIA dnav workbooks.

Manual replacement is also supported. Replace these files inside this folder:

```text
raw.csv.tar.xz
series.csv
reference/dashboard.pdf
```

Then rerun:

```bash
python3 build.py --week latest --validate
```

The generator does not modify `../eia_weekly` during normal runs.

The refresh uses `https://irtest.eia.gov/wpsr/wpsr.csv` until June 10, 2026. Starting June 10, 2026 it switches to `https://ir.eia.gov/wpsr/wpsr.csv`. When the historical workbooks and CSV contain the same week and source column, the CSV row wins.

## Optional Refresh From Weekly Folder

```bash
python3 build.py --refresh-from-weekly ../eia_weekly
python3 build.py --week latest --validate
```

This copies files into this folder and still does not write back to `../eia_weekly`.

## Series Lookup

```bash
python3 build.py --write-series-inventory
```

Writes:

```text
output/series_inventory.csv
```

Selections live in:

```text
config/series_map.csv
```

The dashboard selects by `source_column`, not by mutable EIA display names.

## Email Output

Recipients are read from `email_recipients.txt`. The default file contains:

```text
alexhoffmann07@gmail.com
```

Add more recipients by putting one email address per line in `email_recipients.txt`.

The default build writes an email-ready `.eml` file and standalone HTML body without sending. Email sends use a short body with the dashboard PDF as the only attachment, avoiding duplicate inline previews. To send through SMTP, Apple Mail, then local sendmail fallback:

```bash
python3 build.py --week latest --send-email
```

Use explicit modes when needed:

```bash
python3 build.py --week latest --send-email --email-mode smtp --email-mode mail
```

To open a draft on macOS using Outlook first, then Apple Mail as fallback:

```bash
python3 build.py --week latest --draft-email
```

## Scheduled Send

The scheduled runner is:

```bash
scripts/run_scheduled_email.sh
```

The LaunchAgent template is:

```text
launchd/com.alexhoffmann.eia-summary-dashboard.plist
```

It runs Wednesdays at 9:30 AM local time, applies the fast WPSR CSV update, and sends the latest dashboard to the addresses in `email_recipients.txt`.

## Windows Export

On Windows, unzip the export package, open PowerShell in the extracted folder, and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1
```

This installs the Python requirements and registers a Windows Task Scheduler task named `EIA Summary Dashboard` for Wednesdays at 9:30 AM. The Windows scheduled send downloads the EIA historical workbooks and WPSR CSV first, rebuilds the local raw archive, sends through Outlook, attaches only the dashboard PDF, and reads recipients from `email_recipients.txt`.

Run once immediately with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_scheduled_email.ps1
```
