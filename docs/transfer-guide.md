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

## Add the weekly/Kpler/SharePoint feature to an older checkout

The transfer is designed for a simple replace-all workflow. The new project
provides the code and current datasets; the older project provides the saved
projection state, overrides, and default view.

The older project remains the source of truth because it contains the working
forecast horizon, manual balance and refinery-capacity adjustments, outages,
saved scenarios, materialized projections, named views, and weekly forecast
archives. Before copying the feature files, open the older project through its
launcher and use **Save dashboard** for each product with projection work that
must be retained. This materializes the exact state in
`Diesel_Balance/diesel_balance.json` or `Jet_Balance/jet_balance.json` instead
of leaving it only in an open browser tab.

1. Back up the older project.
2. In the older project, click **Save dashboard** and **Save as default** for
   each product whose state must be retained.
3. Copy these files from the older project into the matching paths in the new
   project folder, replacing the new folder's copies when they exist:
   - `balance_dashboard_settings.json`
   - `outages.json`
   - `Diesel_Balance/diesel_balance.json`
   - `Diesel_Balance/saved_views.json`
   - `Jet_Balance/jet_balance.json` and `Jet_Balance/saved_views.json` when Jet
     state also needs to move
   - `.env.local` when the destination should use the same local credentials
4. The new project folder is now prepared with the old projections and
   overrides. Copy that entire folder over the other installation and choose
   replace-all.
5. Open it through the launcher. The default view loads normally; use **Load
   saved dashboard** once when the exact saved scenarios/materialized dashboard
   state also needs to be restored into the live workbook.

Do not copy only `Diesel_Balance/index.html` or only the `Diesel_Balance`
folder. The page will still open, but the older server/generator does not have
the matching weekly package and SharePoint implementation; a later save or
rebuild can overwrite the copied page and reject its dashboard-state checksum.
