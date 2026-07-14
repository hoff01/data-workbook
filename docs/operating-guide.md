# US Balances Operating Guide

This guide is the production runbook for opening, refreshing, and maintaining the Diesel and Jet balance dashboards from a shared checkout.

## What To Use

Use the local dashboard runner, not a raw `file://` browser tab, for normal work:

- Windows: double-click `Open_Balance_Dashboards.bat`
- Mac: double-click `Open_Balance_Dashboards.command`
- Direct command: `npm run dashboard:server`, then open `http://127.0.0.1:8787/`

The runner serves the dashboard over plain local HTTP at `http://127.0.0.1:8787`. Do not change the URL to `https://...`. This repo does not create a local TLS certificate, so using HTTPS can produce browser certificate warnings. The intended no-certificate-error path is always local `http://127.0.0.1`.

## Windows First Run

1. Install Git for Windows.
2. Install Node.js LTS. Confirm PowerShell can run:
   ```powershell
   node --version
   npm --version
   ```
3. Python 3.11 or newer is required because a normal launcher click performs a full refresh after opening the dashboard. Confirm:
   ```powershell
   py -3 --version
   ```
4. Clone the canonical GitHub repo, or download and fully extract the ZIP. Do not run the `.bat` from inside Windows' compressed-folder view. For a clone:
   ```powershell
   git clone https://github.com/hoff01/data-workbook.git US_Balances
   cd US_Balances
   ```
5. Double-click `Open_Balance_Dashboards.bat` from the fully extracted repo folder. The launcher prepares Node, starts the current local server, and opens the exact local URL with the Windows default-browser shell. On first run it then creates the Python environment and automatically starts a forced `All` refresh. The page shows setup readiness, live progress, and whether new source data was loaded or the source data was unchanged while the workbooks were still rebuilt.

### Add The Kpler API Key

1. Double-click `Configure_Kpler_Auth.bat` in the repo root.
2. In the `.env.local` file that opens, set `KPLER_API_KEY` to the value after
   `Basic `, then save and close Notepad. The file is ignored by git.
3. Confirm the repo can see the key without an API call:
   ```powershell
   .\Kpler\run.ps1 -Preflight
   ```
   The output must include `auth_configured=true`.
4. Validate the credential with one small Kpler Flows request:
   ```powershell
   .\Kpler\run.ps1 -CheckAuth
   ```

Do not paste a real key into source code, `.env.example`, a commit, or a GitHub
issue. For macOS/Linux, copy `.env.example` to `.env.local`, edit the same key,
then run `./Kpler/run.sh preflight` and `./Kpler/run.sh auth-check`.

Keep Git certificate verification enabled. GitHub uses a publicly trusted
certificate, so a normal Git for Windows installation should push without a
certificate prompt. If a managed Windows computer reports an issuer or
corporate-proxy certificate error, use the Windows certificate store and retry:

```powershell
git config --global http.sslBackend schannel
git config --global --unset http.sslCAInfo
git ls-remote origin
```

Do not work around a certificate error with
`git config --global http.sslVerify false`. That disables identity verification
for every HTTPS Git connection. If `git ls-remote origin` still fails, the
company certificate authority must be installed by IT in the Windows trust
store.

Older checkouts may still point at the repository's previous GitHub name. Update
them once, then verify the canonical remote:

```powershell
git remote set-url origin https://github.com/hoff01/data-workbook.git
git remote -v
git ls-remote origin
```

On first run, `Start_Balance_Runner.ps1` creates local runtime folders under:

```text
%USERPROFILE%\US_Balances\
```

Those local folders hold Node packages, the Python virtual environment, pip/npm caches, Python bytecode, and matplotlib caches. The launcher prepares the required Node runtime, opens the dashboard, finishes the Python refresh environment, and starts the full refresh. The shared repo remains the source/output folder, while user-specific runtime files stay out of the shared drive.

## Certificate Error Avoidance

Use these rules exactly:

- Open `http://127.0.0.1:8787/`
- Do not open `https://127.0.0.1:8787/`
- Do not open `https://localhost:8787/`
- Do not set `DASHBOARD_UPDATE_HOST` to a remote host unless you are intentionally exposing the runner and understand the network/security implications.

If a browser shows a certificate warning, the URL is wrong for this local runner. Close that tab and relaunch with `Open_Balance_Dashboards.bat`; the opened URL should start with `http://127.0.0.1:`.

## Daily Operating Flow

1. Pull the latest code and outputs:
   ```powershell
   git pull origin main
   ```
2. Open the dashboard and start the forced full refresh:
   ```powershell
   .\Open_Balance_Dashboards.bat
   ```
3. Watch the landing page or any open workbook for live refresh status. Use the buttons only when an additional targeted refresh is needed:
   - `Weekly` for weekly EIA updates
   - `Monthly` for monthly EIA updates
   - `Power DFO` for Northeast diesel power-generation context
   - `Other` for supporting exports/context
   - `All` for another full pipeline run
4. To create the weekly table images, open each workbook's `Reference` tab and
   select its product-specific save button. Wait for `Saved — Diesel weekly
   table image ready` and `Saved — Jet weekly table image ready`; both dated
   product packages are written under
   `weekly_call_ouputs\outputs` without overwriting each other.
5. Review `Diesel Balance` and `Jet Balance`.
6. Commit and push refreshed outputs when the checks pass:
   ```powershell
   git status --short
   git add .
   git commit -m "Refresh balance dashboards"
   git push origin main
   ```

Do not commit local credentials, `.env.local`, `node_modules`, logs, cache folders, or Python virtual environments.

## Command-Line Refreshes

From the repo root:

```bash
npm run update:weekly
npm run update:monthly
npm run update:power-dfo
npm run update:other
npm run build:balances
```

Useful verification commands:

```bash
npm run typecheck
npm run verify:dashboard
npm run verify:weekly
npm run verify:monthly
npm run trace:dashboard:optimize
```

`npm run update:all` attempts the live Kpler pull. If Kpler credentials are unavailable, use:

```powershell
$env:US_BALANCES_SKIP_KPLER_REFRESH = "1"
npm run update:all
```

That keeps the latest local Kpler files and still rebuilds the dashboards.

## Shared Edits And Collaboration

Shared dashboard edits use `balance_dashboard_settings.json` through the local dashboard server.

- Edits are durable only when the dashboard is opened from `http://127.0.0.1:8787/`.
- A raw `file://` tab can display the dashboard, but browser-only saves are local to that machine and are not a shared edit channel.
- The settings API returns a revision token. If another user saved first, stale writes return HTTP `409`, reload the latest settings, and ask the user to re-enter the edit.
- Only one update job should run at a time. The server uses `logs/update_runner.lock`; concurrent update attempts return HTTP `409`.

## GitHub Release Flow

Before pushing:

```bash
git status --short --branch
npm run typecheck
npm run verify:dashboard
npm run verify:weekly
npm run verify:monthly
npm run trace:dashboard:optimize
```

Then:

```bash
git add .
git commit -m "Describe the dashboard change"
git push origin main
git status --short --branch
```

The final status should show `## main...origin/main` and no modified or untracked files, except ignored local runtime/cache files.

## Troubleshooting

### Double-Click Does Not Open a Browser

1. Confirm the GitHub ZIP was fully extracted. The launcher cannot run from inside the compressed-folder view.
2. Confirm `package.json`, `Start_Balance_Runner.bat`, `Start_Balance_Runner.ps1`, and the `src` folder are beside `Open_Balance_Dashboards.bat`.
3. Double-click `Open_Balance_Dashboards.bat` again. On failure, the window now remains open with the exact prerequisite or startup error instead of silently closing.
4. If the window reports that Node is missing, install Node.js LTS and retry. Python is not needed just to open the dashboard.
5. If the server starts but the browser association is unavailable, copy the printed `http://127.0.0.1:<port>/` URL into Edge or Chrome.

The launcher deliberately bypasses any inherited `DASHBOARD_OPEN_BROWSER=0` value and delegates the final URL to Windows ShellExecute, which uses the configured default browser.

The final result distinguishes `Updated — new data loaded` from `Refreshed — data unchanged`; it never uses a generic success message to imply that a source published a newer observation. Both outcomes rebuild and reload the workbooks. An explicit operator skip is labeled with warnings in amber. Any Kpler or other required-source failure is labeled `Failed`, reports a nonzero exit code, remains visible in red, and does not reload the workbook as though new data were available.

When a launcher or dashboard refresh completes, already-open Diesel and Jet workbook tabs automatically reload the newly built dashboard files. If the source published no newer observation, the result says `Refreshed — data unchanged`, the workbooks are still rebuilt and reloaded, and the displayed latest source date correctly remains unchanged. Every click of the top `Refresh dashboard` button starts the forced `All` pipeline: it repulls all configured upstream sources, including Kpler when its auth key is configured, rebuilds both workbooks even when the returned data is unchanged, and reloads the packaged dashboard only after that run completes. A client-only rerender or page reload is not treated as a refresh.

For an intentional open-only diagnostic run, use `Start_Balance_Runner.ps1 -NoRefresh`. Normal `.bat` clicks do not use this escape hatch.

### Black Node Window Or Zero-Second Refresh

In an older checkout, Windows could open a visible Node child window while the
dashboard claimed a refresh completed without running any pipeline steps. Update
to the current checkout and relaunch with `Open_Balance_Dashboards.bat`. A real
refresh log starts with `[update] group=...` and then shows
`[update] step 1/... start`.

If an older black window has `Select` at the beginning of its title, press
`Esc`. Windows console selection pauses the process. The current runner hides
background update child windows so an accidental selection cannot pause them.

The current server treats a zero-exit process with no pipeline-start message as
`Failed`; it no longer reports that silent no-op as a completed refresh.

### Browser Certificate Warning

Cause: the dashboard was opened with `https://`.

Fix: close the tab and reopen with `Open_Balance_Dashboards.bat`. Confirm the URL is `http://127.0.0.1:8787/`.

### Git Push Certificate Error On Windows

Confirm Git is using the Windows certificate store:

```powershell
git config --global http.sslBackend schannel
git config --global --unset http.sslCAInfo
git ls-remote origin
```

Leave `http.sslVerify` enabled. On a company-managed network, ask IT to install
the corporate root certificate if the remote check still fails.

### Port 8787 Is Busy

Use a nearby port:

```powershell
.\Start_Balance_Runner.ps1 -Port 8788
```

Open the printed `http://127.0.0.1:<port>/` URL.

### Windows PowerShell Policy Warning

Use the `.bat` launcher. It runs PowerShell with `-ExecutionPolicy Bypass` for this script invocation only.

### First Run Fails During npm Install

Check Node and npm:

```powershell
node --version
npm --version
```

Then force setup:

```powershell
.\Start_Balance_Runner.ps1 -ForceSetup
```

### First Run Fails During Python Setup

Check Python:

```powershell
py -3 --version
```

Then force setup:

```powershell
.\Start_Balance_Runner.ps1 -ForceSetup
```

### Shared Save Says Server Offline

The dashboard was probably opened as a file or the local runner is stopped. Relaunch with `Open_Balance_Dashboards.bat` and use the `http://127.0.0.1` URL.

### Update Job Is Already Active

Wait for the current job to finish. If a machine crashed and left a stale lock, inspect:

```text
logs\update_runner.lock
```

The server automatically removes locks older than 12 hours.

## Production Checklist

Use this before tomorrow-morning or shared-drive use:

1. Open via `Open_Balance_Dashboards.bat`.
2. Confirm the URL starts with `http://127.0.0.1`.
3. Open Diesel and Jet dashboards.
4. Switch Balance, Charts, Crude Runs, Outages, and Reference.
5. Toggle Monthly/Weekly.
6. Confirm shared saves do not show the offline/local-only message.
7. In each Reference tab, save the product's weekly table image and confirm the
   product-specific status, current actual-week folder, single untitled table
   PNG, and manifest for both Diesel and Jet.
8. Run:
   ```bash
   npm run typecheck
   npm run verify:dashboard
   npm run verify:weekly
   npm run verify:monthly
   npm run trace:dashboard:optimize
   ```
9. Commit and push to `origin/main`.
