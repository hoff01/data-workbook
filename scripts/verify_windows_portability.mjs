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
  requireText(launcher, 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_Balance_Runner.ps1"', "quoted one-click launcher");
}

requireText("Start_Balance_Runner.ps1", 'Join-Path $env:USERPROFILE "US_Balances"', "user-local Windows runtime");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_SHARED_ROOT = $SharedRoot", "shared-root handoff");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_TSX_CLI", "Node CLI handoff avoids direct .cmd spawn");
requireText("Start_Balance_Runner.ps1", "$env:US_BALANCES_NODE_COMMAND", "Node executable handoff");
requireText("Start_Balance_Runner.ps1", 'Kpler\\config\\local.env.ps1', "optional Kpler PowerShell environment loading");
requireText("src/open_dashboard.ts", "function dashboardServerInvocation()", "portable dashboard server invocation");
requireText("src/dashboard_update_server.ts", "const tsxCli = process.env.US_BALANCES_TSX_CLI;", "portable update-job invocation");
requireText("Kpler/run.ps1", 'Assert-NativeSuccess "Kpler preflight"', "Kpler preflight failure propagation");
requireText("Kpler/run.ps1", 'Assert-NativeSuccess "Kpler pull"', "Kpler pull failure propagation");
requireText(".github/workflows/windows-production.yml", "runs-on: windows-latest", "native Windows CI runner");
requireText(".github/workflows/windows-production.yml", "actions/checkout@v6", "Node 24 checkout action");
requireText(".github/workflows/windows-production.yml", "actions/setup-node@v6", "Node 24 setup-node action");
requireText(".github/workflows/windows-production.yml", "actions/setup-python@v6", "Node 24 setup-python action");
requireText(".github/workflows/windows-production.yml", "Start_Balance_Runner.ps1 -Route diesel -NoOpen", "native Windows launcher smoke test");
requireText(".github/workflows/windows-production.yml", "Kpler\\run.ps1 -Preflight", "native Windows Kpler preflight");
requireText("docs/operating-guide.md", "https://github.com/hoff01/data-workbook.git", "canonical Windows clone URL");
rejectText("docs/operating-guide.md", "https://github.com/hoff01/balances_us.git", "stale Windows clone URL");
requireText(".gitattributes", "*.bat text eol=crlf", "Windows batch line endings");
requireText(".gitattributes", "*.ps1 text eol=crlf", "Windows PowerShell line endings");
requireText(".gitignore", "Kpler/config/local.env", "Kpler secret exclusion");
requireText(".gitignore", "Kpler/config/local.env.ps1", "Kpler PowerShell secret exclusion");

if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log("windows portability contracts ok");
}
