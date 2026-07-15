#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const read = (path) => readFileSync(resolve(ROOT, path), "utf8");
const failures = [];
const packageJson = JSON.parse(read("package.json"));
const packageLock = JSON.parse(read("package-lock.json"));

function requireText(path, expected, label) {
  const text = read(path);
  if (!text.includes(expected)) failures.push(`${label}: ${path} is missing ${JSON.stringify(expected)}`);
}

function rejectText(path, unexpected, label) {
  const text = read(path);
  if (text.includes(unexpected)) failures.push(`${label}: ${path} still contains ${JSON.stringify(unexpected)}`);
}

const pipPolicyFiles = [
  "Start_Balance_Runner.ps1",
  "Start_Balance_Runner.command",
  "Kpler/run.ps1",
  "Kpler/run.sh",
  "weekly_call_outputs/run_weekly_images.bat",
  "docs/operating-guide.md",
];
const directPipCommand = /(?:^|[\s;&|])["']?(?:pip|pip3)(?:\.exe)?["']?\s+(?:--version|install|uninstall|download|wheel|check|list|show|freeze|config|cache|debug|inspect|index|hash)\b/im;
for (const path of pipPolicyFiles) {
  const withoutInterpreterPip = read(path).replace(/-m\s+pip\b/gi, "-m interpreter_pip");
  if (directPipCommand.test(withoutInterpreterPip)) {
    failures.push(`Python package policy: ${path} contains a direct pip command instead of Python -m pip`);
  }
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
requireText("Start_Balance_Runner.bat", "Dashboard launcher setup did not complete", "accurate post-server setup failure message");
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
requireText("Start_Balance_Runner.ps1", '[System.IO.Path]::GetFileName($Path)', "dependency stamps remain stable when the checkout moves");
requireText("Start_Balance_Runner.ps1", '$Host.UI.RawUI.WindowTitle = "US Balances Dashboard"', "npm cannot leave a stale terminal title");
requireText("Start_Balance_Runner.ps1", "Python setup: resolving Python 3", "visible Python detection stage");
requireText("Start_Balance_Runner.ps1", "Python setup: creating the local virtual environment", "visible Python venv stage");
requireText("Start_Balance_Runner.ps1", "Test-PythonPip -PythonPath $PythonPath", "pip health probe uses the selected Python interpreter");
requireText("Start_Balance_Runner.ps1", "-m ensurepip --upgrade", "pip-less Windows environments repair themselves");
requireText("Start_Balance_Runner.ps1", "$pipWasRepaired = Ensure-PythonPip -PythonPath $python -VenvPath $venv -StampPath $PythonStamp", "pip repair runs before dependency stamps are trusted");
requireText("Start_Balance_Runner.ps1", "$venvWasCreated = $true", "new Windows virtual environments cannot trust an old dependency stamp");
requireText("Start_Balance_Runner.ps1", "$ForceSetup -or $venvWasCreated -or $pipWasRepaired -or", "new or repaired environments force dependency revalidation");
requireText("Start_Balance_Runner.ps1", "Remove-Item -Force $PythonStamp -ErrorAction SilentlyContinue", "failed dependency repairs cannot leave a trusted stamp");
requireText("Start_Balance_Runner.ps1", "Remove-Item -Force $StampPath -ErrorAction SilentlyContinue", "pip repair invalidates the dependency stamp before mutation");
requireText("Start_Balance_Runner.ps1", "rebuilding the managed virtual environment", "incomplete pip metadata triggers a managed-environment rebuild");
requireText("Start_Balance_Runner.ps1", "Python setup: upgrading pip", "visible pip upgrade stage");
requireText("Start_Balance_Runner.ps1", "Python setup: installing refresh dependencies", "visible Python dependency stage");
requireText("Start_Balance_Runner.ps1", "Python setup: validating installed dependencies", "visible Python validation stage");
requireText("Start_Balance_Runner.ps1", "Python setup: refresh dependencies installed and validated", "visible Python completion stage");
requireText("Start_Balance_Runner.ps1", '"--timeout", "60", "--retries", "2"', "bounded pip network retries");
requireText("Start_Balance_Runner.ps1", "-m pip check", "installed Python dependency consistency check");
requireText("Start_Balance_Runner.ps1", "import matplotlib, polars, pyarrow, requests, yaml", "Python refresh dependency import smoke");
requireText("Start_Balance_Runner.ps1", "rerun with -ForceSetup", "actionable Python setup retry guidance");
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
requireText("weekly_call_outputs/generate_weekly_images.py", 'env.get("US_BALANCES_NODE_COMMAND"', "weekly output builder reuses the local Node runtime");
requireText("weekly_call_outputs/generate_weekly_images.py", 'env.get("US_BALANCES_TSX_CLI"', "weekly output builder reuses the local tsx CLI");
requireText("package.json", '"test:dashboard-runner"', "dashboard runner contract test");
const lockedEsbuildVersion = packageLock.packages?.["node_modules/esbuild"]?.version;
if (!lockedEsbuildVersion || packageJson.allowScripts?.[`esbuild@${lockedEsbuildVersion}`] !== true) {
  failures.push("reviewed install scripts: package.json must approve the exact package-lock esbuild version");
}
if (packageJson.allowScripts?.esbuild === true || packageJson.allowScripts?.["*"] === true) {
  failures.push("reviewed install scripts: broad or unpinned install-script approval is forbidden");
}
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
requireText("Kpler/run.ps1", "-m ensurepip --upgrade", "Kpler Windows setup repairs missing pip through Python");
requireText("Kpler/run.ps1", '$venvWasCreated = $true', "Kpler environment recreation invalidates the shared dependency stamp");
requireText("Start_Balance_Runner.command", "-m ensurepip --upgrade", "macOS setup repairs missing pip through Python");
requireText("Start_Balance_Runner.command", "VENV_WAS_CREATED", "new macOS virtual environments cannot trust an old dependency stamp");
requireText("Kpler/run.sh", "-m ensurepip --upgrade", "Kpler shell setup repairs missing pip through Python");
requireText("weekly_call_outputs/run_weekly_images.bat", "-m ensurepip --upgrade", "weekly image setup repairs missing pip through Python");
requireText("weekly_call_outputs/run_weekly_images.bat", "US_BALANCES_RUNTIME_ROOT", "weekly image environment honors the shared US Balances runtime root");
requireText("weekly_call_outputs/run_weekly_images.bat", "%USERPROFILE%\\US_Balances", "weekly image environment defaults beside the other user-local US Balances environments");
requireText("weekly_call_outputs/run_weekly_images.bat", 'set "PYTHON_ROOT=%RUNTIME_ROOT%\\weekly_call_outputs"', "weekly image runtime has an explicit managed folder");
requireText("weekly_call_outputs/run_weekly_images.bat", 'set "VENV_DIR=%PYTHON_ROOT%\\.venv"', "weekly image environment stays under its managed runtime folder");
rejectText("weekly_call_outputs/run_weekly_images.bat", "%~dp0.venv", "weekly image environment must not live inside the portable code and output package");
for (const path of ["Start_Balance_Runner.command", "Kpler/run.ps1", "Kpler/run.sh", "weekly_call_outputs/run_weekly_images.bat"]) {
  requireText(path, "rebuilding", "stale pip metadata triggers a managed-environment rebuild");
}
requireText("Kpler/run.ps1", "$cmd = @(Resolve-SystemPython)", "Kpler single-command Python resolution remains an array");
requireText(".github/workflows/windows-production.yml", "runs-on: windows-latest", "native Windows CI runner");
requireText(".github/workflows/windows-production.yml", "actions/checkout@v6", "Node 24 checkout action");
requireText(".github/workflows/windows-production.yml", "actions/setup-node@v6", "Node 24 setup-node action");
requireText(".github/workflows/windows-production.yml", "actions/setup-python@v6", "Node 24 setup-python action");
requireText(".github/workflows/windows-production.yml", "Open_Diesel_Dashboard.bat -Port", "native Windows batch launcher and Python refresh setup smoke test");
requireText(".github/workflows/windows-production.yml", "US_BALANCES_BROWSER_OPEN_PROBE", "native Windows browser-open probe");
requireText(".github/workflows/windows-production.yml", 'import pip; print(pip.__path__[0])', "native Windows missing-pip recovery fixture locates the real module directory");
requireText(".github/workflows/windows-production.yml", 'Remove-Item -LiteralPath $pipPackagePath -Recurse -Force', "native Windows missing-pip recovery fixture preserves stale metadata");
requireText(".github/workflows/windows-production.yml", "Start_Balance_Runner.bat -NoOpen -Port", "native Windows 5.1 damaged-environment recovery rerun");
requireText(".github/workflows/windows-production.yml", "The launcher did not restore pip", "native Windows pip restoration assertion");
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
for (const requirements of ["requirements.txt", "Kpler/requirements.txt", "weekly_call_outputs/requirements.txt"]) {
  requireText(requirements, "pip-system-certs==5.3", "system certificate support in every Python environment");
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log("windows portability contracts ok");
}
