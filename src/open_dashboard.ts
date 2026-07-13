import { openSync, mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";
import { DASHBOARD_SERVER_APP_ID, dashboardServerBuildId } from "./dashboard_server_contract.js";

const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = process.env.US_BALANCES_SHARED_ROOT ? resolve(process.env.US_BALANCES_SHARED_ROOT) : SOURCE_ROOT;
const HOST = process.env.DASHBOARD_UPDATE_HOST || "127.0.0.1";
const DEFAULT_PORT = Number(process.env.DASHBOARD_UPDATE_PORT || 8787);
const PORT_WINDOW = Number(process.env.DASHBOARD_UPDATE_PORT_WINDOW || 10);
const EXPECTED_SERVER_BUILD_ID = dashboardServerBuildId(ROOT);
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const tsxCommand = process.env.US_BALANCES_TSX_COMMAND;
const nodeCommand = process.env.US_BALANCES_NODE_COMMAND || process.execPath;
const tsxCli = process.env.US_BALANCES_TSX_CLI;

function dashboardServerInvocation(): { command: string; args: string[] } {
  const serverScript = join(ROOT, "src", "dashboard_update_server.ts");
  if (tsxCli) return { command: nodeCommand, args: [tsxCli, serverScript] };
  if (tsxCommand && !(process.platform === "win32" && /\.(?:cmd|bat)$/i.test(tsxCommand))) {
    return { command: tsxCommand, args: [serverScript] };
  }
  return { command: npmCommand, args: ["run", "dashboard:server"] };
}

function routeFromArgs(args: string[]): string {
  const requested = args.find((arg) => arg && !arg.startsWith("--")) || "/";
  if (requested === "diesel") return "/Diesel_Balance/index.html";
  if (requested === "jet") return "/Jet_Balance/index.html";
  if (requested === "diesel-reference") return "/Diesel_Balance/index.html?sheet=reference";
  if (requested === "jet-reference") return "/Jet_Balance/index.html?sheet=reference";
  return requested.startsWith("/") ? requested : `/${requested}`;
}

function baseUrl(port: number): string {
  return `http://${HOST}:${port}`;
}

function candidatePorts(): number[] {
  const ports: number[] = [];
  const maxOffset = Math.max(0, PORT_WINDOW);
  for (let offset = 0; offset <= maxOffset; offset += 1) {
    const port = DEFAULT_PORT + offset;
    if (Number.isInteger(port) && port > 0 && port <= 65535) ports.push(port);
  }
  return [...new Set(ports)];
}

async function fetchWithTimeout(url: string, timeoutMs = 1200): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { cache: "no-store", signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function serverHealthy(port: number): Promise<boolean> {
  try {
    const response = await fetchWithTimeout(`${baseUrl(port)}/api/health`);
    if (!response.ok) return false;
    const health = (await response.json()) as { app?: unknown; root?: unknown; buildId?: unknown };
    return health.app === DASHBOARD_SERVER_APP_ID
      && typeof health.root === "string"
      && resolve(health.root) === ROOT
      && health.buildId === EXPECTED_SERVER_BUILD_ID;
  } catch {
    return false;
  }
}

function startServer(port: number): void {
  mkdirSync(join(ROOT, "logs"), { recursive: true });
  const logPath = join(ROOT, "logs", `dashboard_server_${port}.log`);
  const logFd = openSync(logPath, "a");
  const { command, args } = dashboardServerInvocation();
  const child = spawn(command, args, {
    cwd: ROOT,
    detached: true,
    env: { ...process.env, DASHBOARD_UPDATE_PORT: String(port), FORCE_COLOR: "0" },
    stdio: ["ignore", logFd, logFd],
    windowsHide: true,
  });
  child.unref();
}

type BindProbe = {
  ok: boolean;
  code?: string;
  message?: string;
};

async function probeServerPort(port: number): Promise<BindProbe> {
  return await new Promise((resolveProbe) => {
    const server = createServer();
    let settled = false;
    const finish = (result: BindProbe) => {
      if (settled) return;
      settled = true;
      resolveProbe(result);
    };
    server.once("error", (error: NodeJS.ErrnoException) => {
      finish({ ok: false, code: error.code, message: error.message });
    });
    server.listen(port, HOST, () => {
      server.close(() => finish({ ok: true }));
    });
  });
}

async function waitForServer(port: number, startupFailures: Map<number, string>): Promise<boolean> {
  if (await serverHealthy(port)) return true;
  const probe = await probeServerPort(port);
  if (!probe.ok) {
    startupFailures.set(port, `${probe.code || "ERROR"}: ${probe.message || "unable to bind"}`);
    return false;
  }
  startServer(port);
  for (let attempt = 0; attempt < 12; attempt += 1) {
    if (await serverHealthy(port)) return true;
    await sleep(500);
  }
  return false;
}

async function ensureServer(): Promise<{ port: number; url: string }> {
  const startupFailures = new Map<number, string>();
  const [preferredPort, ...fallbackPorts] = candidatePorts();
  if (preferredPort && await serverHealthy(preferredPort)) return { port: preferredPort, url: baseUrl(preferredPort) };
  if (preferredPort && await waitForServer(preferredPort, startupFailures)) return { port: preferredPort, url: baseUrl(preferredPort) };
  for (const port of fallbackPorts) {
    if (await serverHealthy(port)) return { port, url: baseUrl(port) };
  }
  for (const port of fallbackPorts) {
    if (await waitForServer(port, startupFailures)) return { port, url: baseUrl(port) };
  }
  const ports = [preferredPort, ...fallbackPorts].filter((port): port is number => typeof port === "number");
  const details = Array.from(startupFailures, ([port, reason]) => `${port} ${reason}`).join("; ");
  throw new Error(
    `Dashboard server did not become available on ${HOST} ports ${ports.join(", ")}${details ? ` (${details})` : ""}`,
  );
}

function openUrl(url: string): void {
  const command =
    process.platform === "win32" ? "cmd" : process.platform === "darwin" ? "open" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
  const child = spawn(command, args, {
    cwd: ROOT,
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.unref();
}

const cliArgs = process.argv.slice(2);
const route = routeFromArgs(cliArgs);
const shouldOpenBrowser = process.env.DASHBOARD_OPEN_BROWSER !== "0" && !cliArgs.includes("--no-open");
const server = await ensureServer();
const url = new URL(route, server.url).toString();
if (shouldOpenBrowser) openUrl(url);
console.log(`${shouldOpenBrowser ? "Opened" : "Dashboard ready"} ${url}`);
