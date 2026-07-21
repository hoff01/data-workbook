# Transfer the U.S. Balances dashboards

## Recommended: transfer from GitHub

1. Clone or download the repository from GitHub.
2. Keep the complete folder structure together. Do not copy only
   `Diesel_Balance/index.html` or `Jet_Balance/index.html`.
3. On macOS, open `Open_Diesel_Dashboard.command` or
   `Open_Jet_Dashboard.command`.
4. On Windows, open `Open_Diesel_Dashboard.bat` or
   `Open_Jet_Dashboard.bat`.

The launcher prepares its user-local runtime and opens the write-capable local
dashboard. The committed `balance_dashboard_settings.json` contains the shared
forecast horizon and saved Diesel/Jet adjustments, including the July 17, 2026
weekly overrides.

## Transfer one exact dashboard state

`Save dashboard` creates and downloads a portable balance snapshot plus the
shared outage snapshot. It also saves both files locally when the dashboard is
opened through its launcher.

- Diesel: `Diesel_Balance/diesel_balance.json`
- Jet: `Jet_Balance/jet_balance.json`
- Shared Diesel/Jet outages: `outages.json`

Send the product balance JSON and `outages.json` together. The recipient opens
the matching dashboard through its launcher, clicks
`Import dashboard, view, or outage JSON`, and imports the product balance file.
The balance file already embeds that outage schedule for an exact one-file
dashboard transfer. The recipient can also import `outages.json` by itself from
either dashboard to update the shared Diesel/Jet outage schedule once. A Diesel
state intentionally cannot be loaded into Jet, or vice versa.

`Save view` downloads one selected view as JSON and persists all named views in
the product folder's `saved_views.json`. `Save as default` does the same and
marks that view as the startup default. Send the individual view JSON for a
single view, or copy `saved_views.json` with the product folder to transfer the
complete named-view collection and its default.

The latest weekly-call archive also contains the exact state used to render its
JSON and images:

- `weekly_call_outputs/outputs/2026-07-10/diesel_dashboard_state.json`
- `weekly_call_outputs/outputs/2026-07-10/jet_dashboard_state.json`

## Avoid stale or duplicate edits

The authoritative dashboard source is `src/build_balance_dashboards.ts`.
`Diesel_Balance/index.html`, `Jet_Balance/index.html`, and their `data/*.js`
files are generated outputs and should not be edited directly.

The authoritative local server is `src/dashboard_update_server.ts`, and the
weekly image/JSON formatter is
`weekly_call_outputs/generate_weekly_images.py`. The Kpler implementation is
the repository-root `src/kpler_pull.py`; there is no second `Kpler/src` source
tree.

The Diesel and Jet crude-weekly runtime chunks are intentionally identical
because both products use the same shared crude-run source. They are generated
copies, not competing implementations.
