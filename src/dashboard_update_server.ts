import {
  closeSync,
  createReadStream,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
  type Stats,
} from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { dirname, extname, join, normalize, relative, resolve } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createGzip } from "node:zlib";
import { createHash } from "node:crypto";
import { DASHBOARD_SERVER_APP_ID, dashboardServerBuildId } from "./dashboard_server_contract.js";
import { updateDataFingerprint, type UpdateGroup } from "./update_data_fingerprint.js";

type JobStatus = "running" | "succeeded" | "partial" | "failed";
type DashboardJobGroup = UpdateGroup | "weekly-call-outputs";
type UpdateResult = "updated" | "current" | "saved";

type Job = {
  id: string;
  group: DashboardJobGroup;
  status: JobStatus;
  command: string;
  args: string[];
  startedAt: string;
  endedAt: string | null;
  durationMs: number | null;
  exitCode: number | null;
  signal: NodeJS.Signals | null;
  result: UpdateResult | null;
  dataChanged: boolean | null;
  lines: string[];
};

type RunnerLock = {
  fd: number;
  path: string;
};

type BalanceAdjustment = {
  frequency: "monthly" | "weekly";
  period: string;
  regionKey: string;
  lineId: string;
  valueKbd: number;
  note?: string;
  updatedAt?: string;
};

type CrudeOutage = {
  id: string;
  regionKey: string;
  refineryId?: string;
  refineryName?: string;
  unitKey?: string;
  unitLabel?: string;
  refinery: string;
  capacityOfflineKbd: number;
  startDate: string;
  endDate: string;
  type: "Planned" | "Unplanned" | "Other";
  note?: string;
  updatedAt?: string;
};

type RefineryCapacityAdjustment = {
  id: string;
  periodMonth: string;
  scope?: "crude_cell";
  frequency?: "monthly" | "weekly";
  period?: string;
  regionKey?: string;
  refineryId: string;
  refineryName?: string;
  unitKey: string;
  unitLabel?: string;
  capacityKbd: number;
  note?: string;
  updatedAt?: string;
};

type DashboardSettings = {
  forecastEnd: string;
  adjustments: Record<"diesel" | "jet", BalanceAdjustment[]>;
  crudeOutages: CrudeOutage[];
  refineryCapacityAdjustments: RefineryCapacityAdjustment[];
  updatedAt: string;
};

type DashboardSettingsResponse = DashboardSettings & {
  revision: string;
};

const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = process.env.US_BALANCES_SHARED_ROOT ? resolve(process.env.US_BALANCES_SHARED_ROOT) : SOURCE_ROOT;
const HOST = process.env.DASHBOARD_UPDATE_HOST || "127.0.0.1";
const PORT = Number(process.env.DASHBOARD_UPDATE_PORT || 8787);
const SERVER_BUILD_ID = dashboardServerBuildId(ROOT);
const SERVER_STARTED_AT = new Date().toISOString();
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const pythonCommand = process.env.US_BALANCES_PYTHON || (process.platform === "win32" ? "python" : "python3");
const tsxCommand = process.env.US_BALANCES_TSX_COMMAND;
const nodeCommand = process.env.US_BALANCES_NODE_COMMAND || process.execPath;
const tsxCli = process.env.US_BALANCES_TSX_CLI;
const weeklyCallOutputScript = process.env.US_BALANCES_WEEKLY_OUTPUT_SCRIPT
  ? resolve(process.env.US_BALANCES_WEEKLY_OUTPUT_SCRIPT)
  : join(ROOT, "weekly_call_ouputs", "generate_weekly_images.py");
const validGroups = new Set<DashboardJobGroup>([
  "weekly",
  "monthly",
  "other",
  "all",
  "power-dfo",
  "weekly-call-outputs",
]);
const maxLines = 600;
const settingsPath = join(ROOT, "balance_dashboard_settings.json");
const runnerLockPath = join(ROOT, "logs", "update_runner.lock");
const runnerLockStaleMs = 12 * 60 * 60 * 1000;
const refreshReadyFile = String(process.env.US_BALANCES_REFRESH_READY_FILE || "").trim();

let currentProcess: ReturnType<typeof spawn> | null = null;
let currentJob: Job | null = null;
let currentLock: RunnerLock | null = null;

function refreshToolsReady(): boolean {
  return !refreshReadyFile || existsSync(refreshReadyFile);
}

function mimeType(pathname: string): string {
  return {
    ".css": "text/css; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
  }[extname(pathname).toLowerCase()] || "application/octet-stream";
}

function writeJson(response: ServerResponse, statusCode: number, payload: unknown): void {
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
  });
  response.end(JSON.stringify(payload));
}

function settingsRevision(settings: DashboardSettings): string {
  return createHash("sha256").update(JSON.stringify(settings)).digest("hex").slice(0, 16);
}

function publicSettings(settings: DashboardSettings): DashboardSettingsResponse {
  return { ...settings, revision: settingsRevision(settings) };
}

function normalizeForecastEnd(value: unknown): string {
  const raw = String(value || "2026-12-31").trim();
  if (/^\d{4}$/.test(raw)) return `${raw}-12-31`;
  if (/^\d{4}-\d{2}$/.test(raw)) {
    const year = Number(raw.slice(0, 4));
    const month = Number(raw.slice(5, 7));
    const day = new Date(year, month, 0).getDate();
    return `${raw}-${String(day).padStart(2, "0")}`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  return "2026-12-31";
}

function defaultSettings(): DashboardSettings {
  return {
    forecastEnd: "2026-12-31",
    adjustments: { diesel: [], jet: [] },
    crudeOutages: [],
    refineryCapacityAdjustments: [],
    updatedAt: new Date().toISOString(),
  };
}

function roundCapacity(value: unknown): number {
  return Math.round(Math.max(0, Number(value || 0)) * 10) / 10;
}

function normalizeCrudeOutages(rows: CrudeOutage[]): CrudeOutage[] {
  return rows.map((row) => ({
    ...row,
    capacityOfflineKbd: roundCapacity(row.capacityOfflineKbd),
  }));
}

function normalizeRefineryCapacityAdjustments(rows: RefineryCapacityAdjustment[]): RefineryCapacityAdjustment[] {
  return rows.map((row) => ({
    ...row,
    capacityKbd: roundCapacity(row.capacityKbd),
  }));
}

function readSettings(): DashboardSettings {
  const fallback = defaultSettings();
  if (!existsSync(settingsPath)) {
    writeSettings(fallback);
    return fallback;
  }
  try {
    const raw = JSON.parse(readFileSync(settingsPath, "utf8")) as Partial<DashboardSettings>;
    return {
      forecastEnd: normalizeForecastEnd(raw.forecastEnd),
      adjustments: {
        diesel: Array.isArray(raw.adjustments?.diesel) ? raw.adjustments.diesel : [],
        jet: Array.isArray(raw.adjustments?.jet) ? raw.adjustments.jet : [],
      },
      crudeOutages: normalizeCrudeOutages(Array.isArray(raw.crudeOutages) ? raw.crudeOutages : []),
      refineryCapacityAdjustments: normalizeRefineryCapacityAdjustments(
        Array.isArray(raw.refineryCapacityAdjustments) ? raw.refineryCapacityAdjustments : [],
      ),
      updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt : fallback.updatedAt,
    };
  } catch {
    return fallback;
  }
}

function writeSettings(settings: DashboardSettings): void {
  mkdirSync(dirname(settingsPath), { recursive: true });
  const tempPath = join(dirname(settingsPath), `.balance_dashboard_settings.${process.pid}.${Date.now()}.tmp`);
  writeFileSync(tempPath, JSON.stringify(settings, null, 2) + "\n");
  renameSync(tempPath, settingsPath);
}

function landingPage(): string {
  return `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Balance Dashboards</title>
<style>body{margin:0;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#eef2f6;color:#151c2c}.wrap{max-width:940px;margin:48px auto;padding:0 20px}h1{font-size:28px;margin:0 0 10px}h2{font-size:18px;margin:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:20px}.runner{background:#fff;border:1px solid #cfd7e3;border-radius:8px;box-shadow:0 12px 28px rgba(26,39,65,.08);padding:18px;margin-top:20px}.runnerHead{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}.runnerButtons{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.runnerStatus{display:inline-flex;border-radius:999px;background:#eef6ff;color:#294f88;padding:5px 9px;font-size:12px;font-weight:850}.runnerStatus.running,.runnerStatus.partial{background:#fff6df;color:#976100}.runnerStatus.succeeded{background:#eaf8ef;color:#137047}.runnerStatus.failed{background:#fee4e2;color:#981b1b}.log{margin-top:12px;max-height:240px;overflow:auto;background:#101828;color:#e5edf8;border-radius:8px;padding:10px;font-size:11px;line-height:1.45;white-space:pre-wrap}a{display:block;background:#fff;border:1px solid #cfd7e3;border-radius:8px;padding:18px;color:#1d4ed8;text-decoration:none;font-weight:800;box-shadow:0 12px 28px rgba(26,39,65,.08)}button{border:1px solid #cbd5e1;background:#fff;color:#1f2937;border-radius:7px;padding:8px 11px;font-weight:850;cursor:pointer}button.primary{background:#1d4ed8;border-color:#1d4ed8;color:#fff}button:disabled{opacity:.55;cursor:not-allowed}p{color:#667085;line-height:1.5}.note{background:#fff;border:1px solid #cfd7e3;border-radius:8px;padding:14px 16px;margin-top:18px;color:#475467;font-size:13px}@media(max-width:620px){.grid{grid-template-columns:1fr}.runnerHead{display:block}}</style></head>
  <body><main class="wrap"><h1>Balance Dashboards</h1><p>The local update runner is active. Open a workbook, or start a background refresh directly from this page.</p><div class="grid"><a href="/Diesel_Balance/index.html">Diesel Balance</a><a href="/Jet_Balance/index.html">Jet Balance</a><a href="/Diesel_Balance/index.html?sheet=reference">Diesel Reference</a><a href="/Jet_Balance/index.html?sheet=reference">Jet Reference</a></div><section class="runner"><div class="runnerHead"><div><h2>Update Runner</h2><p>Run the existing npm update groups from this checkout. The runner keeps working if the folder is moved because the server resolves the repo root dynamically.</p></div><span class="runnerStatus" id="runnerStatus">Idle</span></div><div class="runnerButtons"><button class="primary" data-run-group="weekly" type="button">Weekly</button><button data-run-group="monthly" type="button">Monthly</button><button data-run-group="other" type="button">Other</button><button data-run-group="power-dfo" type="button">Power DFO</button><button data-run-group="all" type="button">All</button></div><pre class="log" id="runnerLog">No runner job started.</pre></section><div class="note">For one-click launch from the file system, use <strong>Open_Balance_Dashboards.command</strong> on Mac or <strong>Open_Balance_Dashboards.bat</strong> on Windows from the fully extracted repo folder.</div></main><script>
const statusEl = document.getElementById('runnerStatus');
const logEl = document.getElementById('runnerLog');
const buttons = Array.from(document.querySelectorAll('[data-run-group]'));
const updateCompletionStorageKey = 'us-balances:update-complete';
let pollTimer = 0;
let refreshReady = true;
function setStatus(job){
  const state = job?.status || 'idle';
  const result = job?.result;
  statusEl.textContent = state === 'idle' && !refreshReady ? 'Preparing refresh tools…' : state === 'idle' ? 'Ready — waiting to refresh' : state === 'succeeded' && result === 'saved' ? 'Weekly call outputs saved' : state === 'succeeded' && result === 'updated' ? job.group + ' updated — new data loaded' : state === 'succeeded' && result === 'current' ? job.group + ' checked — already current' : state === 'succeeded' ? job.group + ' refresh complete' : state === 'partial' && result === 'updated' ? job.group + ' updated with warnings' : state === 'partial' && result === 'current' ? job.group + ' current with warnings' : state === 'partial' ? job.group + ' complete with warnings' : state === 'failed' ? job.group + ' failed' : job.group === 'weekly-call-outputs' ? 'Saving weekly call outputs' : job.group + ' refresh running';
  statusEl.className = 'runnerStatus ' + (state === 'idle' ? '' : state);
  buttons.forEach(button => button.disabled = state === 'running' || !refreshReady);
  logEl.textContent = job?.lines?.length ? job.lines.join('\\n') : refreshReady ? 'Refresh tools are ready. The one-click launcher starts an All refresh automatically.' : 'First-run setup is installing the local refresh tools. The launcher will start an All refresh automatically when setup finishes.';
}
function publishUpdateCompletion(job){
  if (!job?.id || job.result === 'saved' || !['succeeded','partial'].includes(job.status)) return;
  try { if (localStorage.getItem(updateCompletionStorageKey) !== job.id) localStorage.setItem(updateCompletionStorageKey, job.id); } catch {}
}
async function refreshStatus(){
  try {
    const [statusResponse, healthResponse] = await Promise.all([fetch('/api/update/status', { cache:'no-store' }), fetch('/api/health', { cache:'no-store' })]);
    if (!statusResponse.ok || !healthResponse.ok) throw new Error('runner status unavailable');
    const payload = await statusResponse.json();
    const health = await healthResponse.json();
    refreshReady = health.refreshReady !== false;
    setStatus(payload.job);
    publishUpdateCompletion(payload.job);
    const delay = payload.job?.status === 'running' ? 2000 : !refreshReady || !payload.job ? 1200 : 8000;
    pollTimer = window.setTimeout(refreshStatus, delay);
  } catch (error) {
    statusEl.textContent = 'Unavailable';
    statusEl.className = 'runnerStatus failed';
    logEl.textContent = error instanceof Error ? error.message : String(error);
    pollTimer = window.setTimeout(refreshStatus, 3000);
  }
}
buttons.forEach(button => button.addEventListener('click', async () => {
  window.clearTimeout(pollTimer);
  const group = button.dataset.runGroup;
  setStatus({ group, status:'running', lines:['starting update:' + group] });
  try {
    const response = await fetch('/api/update/start', { method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({ group, force:true }) });
    const payload = await response.json();
    if (!response.ok && response.status !== 409) throw new Error(payload.error || 'refresh failed to start');
    setStatus(payload.job);
    pollTimer = window.setTimeout(refreshStatus, response.status === 409 ? 1000 : 1500);
  } catch (error) {
    statusEl.textContent = 'Refresh not started';
    statusEl.className = 'runnerStatus failed';
    logEl.textContent = error instanceof Error ? error.message : String(error);
    pollTimer = window.setTimeout(refreshStatus, 2000);
  }
}));
refreshStatus();
</script></body>
</html>`;
}

function appendJobLine(job: Job, stream: "stdout" | "stderr", text: string): void {
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    job.lines.push(`[${stream}] ${line}`);
  }
  if (job.lines.length > maxLines) job.lines.splice(0, job.lines.length - maxLines);
}

function publicJob(): Job | null {
  return currentJob ? { ...currentJob, lines: [...currentJob.lines] } : null;
}

function parseGroup(value: unknown): DashboardJobGroup | null {
  return typeof value === "string" && validGroups.has(value as DashboardJobGroup) ? (value as DashboardJobGroup) : null;
}

function acquireRunnerLock(group: DashboardJobGroup): RunnerLock {
  mkdirSync(dirname(runnerLockPath), { recursive: true });
  try {
    const existing = statSync(runnerLockPath);
    if (Date.now() - existing.mtimeMs > runnerLockStaleMs) unlinkSync(runnerLockPath);
  } catch {
    // Missing or inaccessible lock is handled by the exclusive open below.
  }
  try {
    const fd = openSync(runnerLockPath, "wx");
    writeFileSync(
      fd,
      JSON.stringify({ group, pid: process.pid, root: ROOT, startedAt: new Date().toISOString() }, null, 2) + "\n",
    );
    return { fd, path: runnerLockPath };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Another update runner appears to be active. Lock: ${runnerLockPath}. ${message}`);
  }
}

function releaseRunnerLock(lock: RunnerLock | null): void {
  if (!lock) return;
  try {
    closeSync(lock.fd);
  } catch {
    // Best effort cleanup.
  }
  try {
    unlinkSync(lock.path);
  } catch {
    // Best effort cleanup.
  }
  if (currentLock === lock) currentLock = null;
}

function startJob(group: DashboardJobGroup): Job {
  if (currentProcess && currentJob?.status === "running") return currentJob;
  const savesWeeklyCallOutputs = group === "weekly-call-outputs";
  const updateGroup: UpdateGroup | null = group === "weekly-call-outputs" ? null : group;
  const dataFingerprintBefore = updateGroup ? updateDataFingerprint(ROOT, updateGroup) : null;
  const lock = acquireRunnerLock(group);
  const updateScript = join(ROOT, "src", "update_pipeline.ts");
  const invocation = savesWeeklyCallOutputs
    ? { command: pythonCommand, args: [weeklyCallOutputScript] }
    : tsxCli
      ? { command: nodeCommand, args: [tsxCli, updateScript, group] }
      : tsxCommand && !(process.platform === "win32" && /\.(?:cmd|bat)$/i.test(tsxCommand))
        ? { command: tsxCommand, args: [updateScript, group] }
        : { command: npmCommand, args: ["run", `update:${group}`] };
  const { command, args } = invocation;
  const started = Date.now();
  const job: Job = {
    id: `${group}-${started}`,
    group,
    status: "running",
    command,
    args,
    startedAt: new Date(started).toISOString(),
    endedAt: null,
    durationMs: null,
    exitCode: null,
    signal: null,
    result: null,
    dataChanged: null,
    lines: [],
  };
  currentJob = job;
  currentLock = lock;
  const child = spawn(command, args, {
    cwd: ROOT,
    env: { ...process.env, FORCE_COLOR: "0" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  currentProcess = child;
  appendJobLine(job, "stdout", `started ${command} ${args.join(" ")}`);
  child.stdout.on("data", (chunk: Buffer) => appendJobLine(job, "stdout", chunk.toString("utf8")));
  child.stderr.on("data", (chunk: Buffer) => appendJobLine(job, "stderr", chunk.toString("utf8")));
  child.on("error", (error) => {
    job.status = "failed";
    job.endedAt = new Date().toISOString();
    job.durationMs = Date.now() - started;
    appendJobLine(job, "stderr", error.message);
    currentProcess = null;
    releaseRunnerLock(lock);
  });
  child.on("close", (code, signal) => {
    const hasWarnings = !savesWeeklyCallOutputs
      && job.lines.some((line) => /\[update\] step \d+\/\d+ (?:skipped|warning):/.test(line));
    job.status = code === 0 ? (hasWarnings ? "partial" : "succeeded") : "failed";
    job.exitCode = code;
    job.signal = signal;
    job.endedAt = new Date().toISOString();
    job.durationMs = Date.now() - started;
    if (code === 0 && savesWeeklyCallOutputs) {
      job.dataChanged = true;
      job.result = "saved";
    } else if (code === 0 && updateGroup && dataFingerprintBefore !== null) {
      try {
        job.dataChanged = updateDataFingerprint(ROOT, updateGroup) !== dataFingerprintBefore;
        job.result = job.dataChanged ? "updated" : "current";
      } catch (error) {
        job.status = "partial";
        appendJobLine(job, "stderr", `source change comparison unavailable: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    const completionMessage = code === 0
      ? job.result === "saved"
        ? "Weekly call outputs were saved to weekly_call_ouputs/outputs with the latest actual-week archive, individual images, and PowerPoint-ready slide."
        : job.result === null
          ? "Refresh completed and the workbooks were rebuilt, but the source change comparison was unavailable."
          : hasWarnings
            ? `Refresh completed with warnings; dashboard source data is ${job.dataChanged ? "updated" : "already current"}. Review skipped steps.`
            : job.dataChanged
              ? "Refresh completed; new dashboard source data was loaded and the workbooks were rebuilt."
              : "Refresh completed; upstream source data was already current and the workbooks were rebuilt."
      : `Update failed (exit code ${code ?? "n/a"}${signal ? `, signal ${signal}` : ""}).`;
    appendJobLine(job, code === 0 ? "stdout" : "stderr", completionMessage);
    currentProcess = null;
    releaseRunnerLock(lock);
  });
  return job;
}

async function readBody(request: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf8");
}

async function handleApi(request: IncomingMessage, response: ServerResponse, pathname: string): Promise<void> {
  if (request.method === "OPTIONS") {
    writeJson(response, 204, {});
    return;
  }
  if (pathname === "/api/settings" && request.method === "GET") {
    writeJson(response, 200, { settings: publicSettings(readSettings()) });
    return;
  }
  if (pathname === "/api/health" && request.method === "GET") {
    writeJson(response, 200, {
      ok: true,
      app: DASHBOARD_SERVER_APP_ID,
      buildId: SERVER_BUILD_ID,
      root: ROOT,
      host: HOST,
      port: PORT,
      pid: process.pid,
      startedAt: SERVER_STARTED_AT,
      refreshReady: refreshToolsReady(),
      currentJob: publicJob(),
    });
    return;
  }
  if (pathname === "/api/settings" && request.method === "POST") {
    try {
      const body = JSON.parse(await readBody(request) || "{}") as {
        forecastEnd?: unknown;
        product?: unknown;
        adjustments?: unknown;
        crudeOutages?: unknown;
        refineryCapacityAdjustments?: unknown;
        baseRevision?: unknown;
      };
      const settings = readSettings();
      const currentRevision = settingsRevision(settings);
      const baseRevision = typeof body.baseRevision === "string" ? body.baseRevision.trim() : "";
      if (baseRevision && baseRevision !== currentRevision) {
        writeJson(response, 409, {
          error: "shared settings changed; refresh and retry",
          settings: publicSettings(settings),
        });
        return;
      }
      if (body.forecastEnd !== undefined) settings.forecastEnd = normalizeForecastEnd(body.forecastEnd);
      if (body.product === "diesel" || body.product === "jet") {
        settings.adjustments[body.product] = Array.isArray(body.adjustments) ? (body.adjustments as BalanceAdjustment[]) : settings.adjustments[body.product];
      }
      if (Array.isArray(body.crudeOutages)) settings.crudeOutages = normalizeCrudeOutages(body.crudeOutages as CrudeOutage[]);
      if (Array.isArray(body.refineryCapacityAdjustments)) {
        settings.refineryCapacityAdjustments = normalizeRefineryCapacityAdjustments(
          body.refineryCapacityAdjustments as RefineryCapacityAdjustment[],
        );
      }
      settings.updatedAt = new Date().toISOString();
      writeSettings(settings);
      writeJson(response, 200, { settings: publicSettings(readSettings()) });
    } catch (error) {
      writeJson(response, 400, { error: error instanceof Error ? error.message : "invalid settings payload" });
    }
    return;
  }
  if (pathname === "/api/update/status" && request.method === "GET") {
    writeJson(response, 200, { job: publicJob() });
    return;
  }
  if (pathname === "/api/update/start" && request.method === "POST") {
    if (!refreshToolsReady()) {
      writeJson(response, 503, {
        error: "First-run refresh setup is still finishing. The launcher will start the refresh automatically when it is ready.",
        job: publicJob(),
      });
      return;
    }
    let group: DashboardJobGroup | null = null;
    try {
      const body = await readBody(request);
      group = parseGroup(JSON.parse(body || "{}").group);
    } catch {
      group = null;
    }
    if (!group) {
      writeJson(response, 400, {
        error: "group must be weekly, monthly, other, all, power-dfo, or weekly-call-outputs",
      });
      return;
    }
    const alreadyRunning = currentJob?.status === "running";
    try {
      const job = startJob(group);
      writeJson(response, alreadyRunning ? 409 : 202, { job: publicJob() ?? job });
    } catch (error) {
      writeJson(response, 409, { error: error instanceof Error ? error.message : String(error), job: publicJob() });
    }
    return;
  }
  writeJson(response, 404, { error: "not found" });
}

function shouldGzip(request: IncomingMessage, path: string, fileStat: Stats): boolean {
  if (fileStat.size < 1024) return false;
  const acceptsGzip = String(request.headers["accept-encoding"] || "").split(",").some(value => value.trim().toLowerCase().startsWith("gzip"));
  if (!acceptsGzip) return false;
  return /\.(?:css|csv|html|js|json|map|svg|txt|xml)$/i.test(path);
}

function staticHeaders(path: string, fileStat: Stats, encoding: "identity" | "gzip" = "identity"): Record<string, string> {
  const etag = `W/"${fileStat.size}-${Math.round(fileStat.mtimeMs)}${encoding === "gzip" ? "-gzip" : ""}"`;
  const isHtml = extname(path).toLowerCase() === ".html";
  const headers: Record<string, string> = {
    "content-type": mimeType(path),
    "last-modified": fileStat.mtime.toUTCString(),
    "etag": etag,
    "cache-control": isHtml ? "no-cache" : "public, max-age=0, must-revalidate",
    "vary": "Accept-Encoding",
  };
  if (encoding === "gzip") headers["content-encoding"] = "gzip";
  else headers["content-length"] = String(fileStat.size);
  return headers;
}

function serveStatic(request: IncomingMessage, response: ServerResponse, pathname: string): void {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { "content-type": "text/plain; charset=utf-8" });
    response.end("Method not allowed");
    return;
  }
  if (pathname === "/favicon.ico") {
    response.writeHead(204);
    response.end();
    return;
  }
  if (pathname === "/") {
    const body = landingPage();
    response.writeHead(200, { "content-type": "text/html; charset=utf-8", "content-length": String(Buffer.byteLength(body)), "cache-control": "no-cache" });
    response.end(request.method === "HEAD" ? undefined : body);
    return;
  }
  const decoded = decodeURIComponent(pathname.split("?")[0] || "/");
  const candidate = resolve(ROOT, `.${normalize(decoded)}`);
  const rel = relative(ROOT, candidate);
  if (rel.startsWith("..") || rel === "" || rel.includes("..")) {
    response.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
    response.end("Forbidden");
    return;
  }
  const path = existsSync(candidate) && statSync(candidate).isDirectory() ? join(candidate, "index.html") : candidate;
  if (!existsSync(path) || !statSync(path).isFile()) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Not found");
    return;
  }
  const stat = statSync(path);
  const gzip = shouldGzip(request, path, stat);
  const headers = staticHeaders(path, stat, gzip ? "gzip" : "identity");
  const ifNoneMatch = request.headers["if-none-match"];
  const ifModifiedSince = request.headers["if-modified-since"];
  const matchesEtag = typeof ifNoneMatch === "string" && ifNoneMatch.split(",").map(value => value.trim()).includes(headers.etag);
  const modifiedSince = typeof ifModifiedSince === "string" ? Date.parse(ifModifiedSince) : NaN;
  const notModified = matchesEtag || (Number.isFinite(modifiedSince) && modifiedSince >= Math.floor(stat.mtimeMs / 1000) * 1000);
  if (notModified) {
    response.writeHead(304, headers);
    response.end();
    return;
  }
  response.writeHead(200, headers);
  if (request.method === "HEAD") {
    response.end();
    return;
  }
  const stream = createReadStream(path);
  if (gzip) stream.pipe(createGzip()).pipe(response);
  else stream.pipe(response);
}

const server = createServer((request, response) => {
  const url = new URL(request.url || "/", `http://${HOST}:${PORT}`);
  if (url.pathname.startsWith("/api/")) {
    handleApi(request, response, url.pathname).catch((error: unknown) => {
      writeJson(response, 500, { error: error instanceof Error ? error.message : String(error) });
    });
    return;
  }
  serveStatic(request, response, url.pathname);
});

server.on("error", (error: NodeJS.ErrnoException) => {
  const code = error.code ? `${error.code}: ` : "";
  console.error(`Balance dashboard update server failed to start on http://${HOST}:${PORT}/ (${code}${error.message})`);
  process.exitCode = 1;
});

server.listen(PORT, HOST, () => {
  console.log(`Balance dashboard update server: http://${HOST}:${PORT}/`);
  if (process.env.DASHBOARD_POWER_DFO_STARTUP_REFRESH !== "1") {
    console.log("Power DFO startup refresh disabled; set DASHBOARD_POWER_DFO_STARTUP_REFRESH=1 to enable it.");
    return;
  }
  setTimeout(() => {
    const job = startJob("power-dfo");
    appendJobLine(job, "stdout", "background startup refresh requested for power DFO daily/hourly data and dashboard rebuild");
  }, 250);
});
