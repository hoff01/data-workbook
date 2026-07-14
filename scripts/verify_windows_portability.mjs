#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const read = (path) => readFileSync(resolve(ROOT, path), "utf8");
const failures = [];

function requireText(path, expected, label) {
  const text = read(path);
  if (!text.includes(expected)) failures.push(`${label}: ${path} is missing ${JSON.stringify(expected)}`);
}

function rejectText(path, unexpected, label) {
  const text = read(path);
  if (text.includes(unexpected)) failures.push(`${label}: ${path} still contains ${JSON.stringify(unexpected)}`);
}

for (const launcher of ["Open_Balance_Dashboards.bat", "Open_Diesel_Dashboard.bat", "Open_Jet_Dashboard.bat"]) {
  requireText(launcher, 'call "%~dp0Start_Balance_Runner.bat"', "centralized one-click launcher");
  requireText(launcher, "%*", "forwarded launcher arguments");
  rejectText(launcher, "-SkipPythonSetup %*", "Python setup must follow browser opening unless explicitly skipped");
  requireText(launcher, "Extract the complete repository", "ZIP extraction guidance");
}

requireText("Start_Balance_Runner.bat", "if not exist \"%~dp0package.json\" goto :incomplete_checkout", "complete-checkout guard");
requireText("Start_Balance_Runner.bat", 'set "EXIT_CODE=%ERRORLEVEL%"', "batch exit-code preservation");
requireText("Start_Balance_Runner.bat", 'if /I not "%CI%"=="true" pause', "interactive failure visibility without CI hangs");
requireText("Start_Balance_Runner.ps1", 'Join-Path $env:USERPROFILE "US_Balances"', "user-local Windows runtime");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_SHARED_ROOT = $SharedRoot", "shared-root handoff");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_TSX_CLI", "Node CLI handoff avoids direct .cmd spawn");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_NODE_COMMAND", "Node executable handoff");
requireText("Start_Balance_Runner.ps1", "$startInfo.UseShellExecute = $true", "Windows default-browser shell launch");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_BROWSER_OPEN_PROBE", "testable browser-open path");
rejectText("Start_Balance_Runner.ps1", "US_BALANCES_REFRESH_START_PROBE", "launcher must not start refresh jobs");
requireText("Start_Balance_Runner.ps1", '$openArgs += "--no-open"', "single browser owner on Windows");
requireText("Start_Balance_Runner.ps1", "The dashboard is available. Preparing Python refresh tools", "browser-first Python setup");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_REFRESH_READY_FILE = $RefreshReadyFile", "first-run refresh readiness gate");
rejectText("Start_Balance_Runner.ps1", "Start-DashboardRefresh", "refreshes must be started only by dashboard buttons");
rejectText("Start_Balance_Runner.ps1", "[switch]$NoRefresh", "open-only launcher no longer needs a refresh escape hatch");
requireText("Start_Balance_Runner.ps1", "No data refresh has started; use a dashboard refresh button", "button-only refresh handoff");
requireText("Start_Balance_Runner.ps1", "$cmd = @(Resolve-SystemPython)", "single-command Python resolution remains an array");
requireText("Start_Balance_Runner.ps1", "[System.IO.File]::OpenRead($Path)", "PowerShell-module-independent file hashing");
rejectText("Start_Balance_Runner.ps1", "Get-FileHash", "launcher must not depend on inherited PowerShell module paths");
requireText("Start_Balance_Runner.ps1", 'Kpler\\config\\local.env.ps1', "optional Kpler PowerShell environment loading");
requireText("src/open_dashboard.ts", "function dashboardServerInvocation()", "portable dashboard server invocation");
requireText("src/open_dashboard.ts", "EXPECTED_SERVER_BUILD_ID", "stale local server rejection");
requireText("src/dashboard_update_server.ts", "const tsxCli = process.env.US_BALANCES_TSX_CLI;", "portable update-job invocation");
requireText("src/dashboard_update_server.ts", "source data was unchanged, and the workbooks were rebuilt anyway", "forced refresh rebuilds unchanged source data");
requireText("src/update_pipeline.ts", 'case "bulk:refresh":', "clean-clone update pipeline can download the ignored PET bulk cache");
requireText("src/update_pipeline.ts", 'branch("monthly PET bulk", [scriptStep("monthly PET bulk source refresh", "bulk:refresh")])', "complete refresh downloads PET bulk data before monthly exports");
requireText("src/update_pipeline.ts", 'scriptStep("monthly PET bulk source refresh", "bulk:refresh"),\n    scriptStep("monthly export files", "export:monthly")', "monthly refresh downloads PET bulk data before monthly exports");
requireText("src/verify_weekly_freshness.ts", 'process.env[EIA_WEEKLY_LATEST_SOURCE_ENV]?.trim() || config.latest_source?.trim() || "xls"', "blank weekly source setting falls back to the documented XLS source");
requireText("src/eia_capacity.py", 'os.environ.get("EIA_CAPACITY_END", "").strip() or date.today().strftime("%Y-%m")', "blank capacity end month uses the current month default");
requireText("scripts/test_dashboard_update_server.mjs", "a repeated forced refresh must start a new job", "repeated unchanged refresh contract test");
requireText("scripts/test_dashboard_update_server.mjs", 'const routedGroups = ["weekly", "monthly", "other", "power-dfo"]', "every dashboard refresh group routes to a real update job");
requireText("src/build_balance_dashboards.ts", "document.getElementById('refreshBtn').addEventListener('click', () => { startDashboardUpdate('all'); });", "top dashboard refresh starts the forced full upstream data pull");
requireText("src/build_balance_dashboards.ts", "Connecting to the local runner and starting the forced", "dashboard refresh buttons show immediate progress");
requireText("src/dashboard_update_server.ts", "windowsHide: true", "hidden Windows update subprocesses");
requireText("src/dashboard_update_server.ts", "no update steps were confirmed", "silent no-op refresh failure detection");
requireText("src/dashboard_update_server.ts", "new dashboard source data was loaded", "truthful changed-data result");
requireText("src/update_data_fingerprint.ts", "VOLATILE_CSV_COLUMNS", "volatile metadata is excluded from change detection");
requireText("scripts/test_update_data_fingerprint.ts", "volatile-only refresh must remain current", "truthful current-data regression test");
requireText("src/dashboard_update_server.ts", "refreshReady: refreshToolsReady()", "server readiness reporting");
requireText("src/dashboard_update_server.ts", "Refresh tools are still being prepared", "early-click readiness protection");
rejectText("src/dashboard_update_server.ts", "DASHBOARD_POWER_DFO_STARTUP_REFRESH", "server startup refresh path removed");
requireText("src/dashboard_update_server.ts", 'process.env.US_BALANCES_PYTHON', "weekly call outputs reuse the installed local Python runtime");
requireText("src/dashboard_update_server.ts", '"weekly-call-outputs"', "weekly call output server action");
requireText("weekly_call_ouputs/generate_weekly_images.py", 'env.get("US_BALANCES_NODE_COMMAND"', "weekly output builder reuses the local Node runtime");
requireText("weekly_call_ouputs/generate_weekly_images.py", 'env.get("US_BALANCES_TSX_CLI"', "weekly output builder reuses the local tsx CLI");
requireText("package.json", '"test:dashboard-runner"', "dashboard runner contract test");
requireText("src/main_module.ts", "const entryUrl = pathToFileURL(resolve(entryPath)).href", "platform-safe main-module URL conversion");
requireText("src/main_module.ts", 'process.platform === "win32"', "case-insensitive Windows main-module comparison");
requireText("src/update_pipeline.ts", "const tsxCli = process.env.US_BALANCES_TSX_CLI;", "nested TypeScript jobs reuse the portable tsx CLI");
requireText("src/update_pipeline.ts", "if (isMainModule(import.meta.url))", "Windows-safe update entrypoint detection");
requireText("src/update_pipeline.ts", "windowsHide: true", "hidden Windows pipeline subprocesses");
requireText("src/run_weekly_pipeline.ts", "if (isMainModule(import.meta.url))", "Windows-safe weekly entrypoint detection");
requireText("src/run_weekly_pipeline.ts", "windowsHide: true", "hidden Windows weekly subprocesses");
rejectText("src/update_pipeline.ts", "`file://${process.argv[1]}`", "raw Windows paths are not file URLs");
rejectText("src/run_weekly_pipeline.ts", "`file://${process.argv[1]}`", "raw Windows paths are not file URLs");
requireText(".github/workflows/windows-production.yml", "npm run test:dashboard-runner", "native Windows runner contract test");
requireText("src/dashboard_update_server.ts", 'hasWarnings ? "partial" : "succeeded"', "skipped-step partial status");
rejectText("src/dashboard_update_server.ts", "finished status=", "misleading process completion message");
rejectText("src/dashboard_update_server.ts", "Update completed successfully.", "generic success must not imply source data changed");
rejectText("src/update_pipeline.ts", "continueOnFailure", "source refresh failures must propagate");
rejectText("src/update_pipeline.ts", "optionalStep(", "Kpler failures must propagate");
requireText("Kpler/run.ps1", 'Assert-NativeSuccess "Kpler preflight"', "Kpler preflight failure propagation");
requireText("Kpler/run.ps1", 'Assert-NativeSuccess "Kpler pull"', "Kpler pull failure propagation");
requireText("Kpler/run.ps1", "$cmd = @(Resolve-SystemPython)", "Kpler single-command Python resolution remains an array");
requireText(".github/workflows/windows-production.yml", "runs-on: windows-latest", "native Windows CI runner");
requireText(".github/workflows/windows-production.yml", "actions/checkout@v6", "Node 24 checkout action");
requireText(".github/workflows/windows-production.yml", "actions/setup-node@v6", "Node 24 setup-node action");
requireText(".github/workflows/windows-production.yml", "actions/setup-python@v6", "Node 24 setup-python action");
requireText(".github/workflows/windows-production.yml", "Open_Diesel_Dashboard.bat -Port", "native Windows batch launcher and Python refresh setup smoke test");
requireText(".github/workflows/windows-production.yml", "US_BALANCES_BROWSER_OPEN_PROBE", "native Windows browser-open probe");
rejectText(".github/workflows/windows-production.yml", "US_BALANCES_REFRESH_START_PROBE", "native Windows launcher must remain refresh-idle");
requireText(".github/workflows/windows-production.yml", '$env:DASHBOARD_OPEN_BROWSER = "0"', "inherited browser-disable regression probe");
requireText(".github/workflows/windows-production.yml", "Kpler\\run.ps1 -Preflight", "native Windows Kpler preflight");
requireText("docs/operating-guide.md", "https://github.com/hoff01/data-workbook.git", "canonical Windows clone URL");
rejectText("docs/operating-guide.md", "https://github.com/hoff01/balances_us.git", "stale Windows clone URL");
requireText(".gitattributes", "*.bat text eol=crlf", "Windows batch line endings");
requireText(".gitattributes", "*.ps1 text eol=crlf", "Windows PowerShell line endings");
requireText(".gitignore", "Kpler/config/local.env", "Kpler secret exclusion");
requireText(".gitignore", "Kpler/config/local.env.ps1", "Kpler PowerShell secret exclusion");
requireText(".env.example", "KPLER_API_KEY=", "root Kpler credential template");
requireText("Configure_Kpler_Auth.bat", 'copy /Y "%EXAMPLE%" "%LOCAL_ENV%"', "one-click ignored Kpler credential file setup");

if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log("windows portability contracts ok");
}
