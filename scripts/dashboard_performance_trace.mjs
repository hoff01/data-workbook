#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const HOST = process.env.DASHBOARD_UPDATE_HOST || "127.0.0.1";
const PORT = Number(process.env.DASHBOARD_UPDATE_PORT || 8787);
const PRODUCT = argValue("product") || process.env.DASHBOARD_TRACE_PRODUCT || "diesel";
const OUT_DIR = resolve(argValue("out-dir") || process.env.DASHBOARD_TRACE_OUT_DIR || join(tmpdir(), "balance-dashboard-traces"));
const HEADLESS = !hasArg("headed") && process.env.DASHBOARD_TRACE_HEADED !== "1";
const KEEP_BROWSER = hasArg("keep-browser") || process.env.DASHBOARD_TRACE_KEEP_BROWSER === "1";
const CHROME_PATH = argValue("chrome") || process.env.CHROME_PATH || findChrome();
const TIMEOUT_MS = Number(argValue("timeout-ms") || process.env.DASHBOARD_TRACE_TIMEOUT_MS || 45000);

class CdpClient {
  static async connect(url) {
    const ws = new WebSocket(url);
    const client = new CdpClient(ws);
    await new Promise((resolveOpen, rejectOpen) => {
      ws.addEventListener("open", resolveOpen, { once: true });
      ws.addEventListener("error", rejectOpen, { once: true });
    });
    return client;
  }

  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.waiters = new Map();
    ws.addEventListener("message", (event) => this.handleMessage(event));
    ws.addEventListener("close", () => {
      for (const { reject } of this.pending.values()) reject(new Error("CDP websocket closed"));
      this.pending.clear();
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    this.ws.send(payload);
    return new Promise((resolveSend, rejectSend) => {
      this.pending.set(id, { resolve: resolveSend, reject: rejectSend, method });
    });
  }

  waitFor(method, timeoutMs) {
    return new Promise((resolveWait, rejectWait) => {
      const timer = setTimeout(() => {
        const rows = this.waiters.get(method) || [];
        this.waiters.set(method, rows.filter((row) => row.resolve !== resolveWait));
        rejectWait(new Error(`Timed out waiting for ${method}`));
      }, timeoutMs);
      const rows = this.waiters.get(method) || [];
      rows.push({
        resolve: (params) => {
          clearTimeout(timer);
          resolveWait(params);
        },
        reject: rejectWait,
      });
      this.waiters.set(method, rows);
    });
  }

  handleMessage(event) {
    const message = JSON.parse(String(event.data));
    if (message.id) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
      else pending.resolve(message.result || {});
      return;
    }
    const rows = this.waiters.get(message.method) || [];
    if (!rows.length) return;
    const [row, ...rest] = rows;
    this.waiters.set(message.method, rest);
    row.resolve(message.params || {});
  }

  close() {
    this.ws.close();
  }
}

if (!["diesel", "jet"].includes(PRODUCT)) {
  throw new Error("--product must be diesel or jet");
}

if (!CHROME_PATH) {
  throw new Error("Chrome was not found. Set CHROME_PATH to a Chrome or Chromium executable.");
}

await mkdir(OUT_DIR, { recursive: true });

const scriptStartedAt = new Date().toISOString();
let server = null;
let chrome = null;
let cdp = null;

try {
  server = await ensureDashboardServer();
  chrome = await launchChrome();
  cdp = await CdpClient.connect(chrome.pageWsUrl);

  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Network.enable");
  await cdp.send("Performance.enable", { timeDomain: "timeTicks" });

  const productDir = PRODUCT === "diesel" ? "Diesel_Balance" : "Jet_Balance";
  const startUrl = `http://${HOST}:${PORT}/${productDir}/index.html`;
  const runStartedAt = new Date().toISOString();
  const phases = [];

  phases.push(await tracePhase(cdp, "initial-load", OUT_DIR, async () => {
    const loadEvent = cdp.waitFor("Page.loadEventFired", TIMEOUT_MS);
    await cdp.send("Page.navigate", { url: startUrl });
    await loadEvent;
    await waitForPage(cdp, "document.querySelector('h1') && document.querySelectorAll('#balanceTable tbody tr').length > 0");
  }));

  phases.push(await tracePhase(cdp, "weekly-lazy-chunk", OUT_DIR, async () => {
    await runInPage(cdp, markAndClickScript("codex-weekly", "[data-frequency='weekly']"));
    await waitForPage(
      cdp,
      "document.querySelector(\"[data-frequency='weekly'].active\") && window.BALANCE_DATA?.regionalBalance?.weekly?.length > 0 && document.querySelectorAll('#balanceTable tbody tr').length > 0",
    );
    await runInPage(cdp, finishMeasureScript("codex-weekly", "codex-weekly-click-to-render"));
  }));

  phases.push(await tracePhase(cdp, "chart-sheet-render", OUT_DIR, async () => {
    await runInPage(cdp, markAndApplyViewStateScript("codex-charts", { sheet: "charts" }));
    await waitForPage(
      cdp,
      "!document.querySelector('#chartsSheet')?.hidden && document.querySelectorAll('#chartGrid .chartCard').length > 0 && document.querySelectorAll('#chartGrid svg.seasonChart path').length > 0",
    );
    await runInPage(cdp, finishMeasureScript("codex-charts", "codex-chart-sheet-click-to-render"));
  }));

  phases.push(await tracePhase(cdp, "crude-runs-render", OUT_DIR, async () => {
    await runInPage(cdp, markAndApplyViewStateScript("codex-crude", { sheet: "crude", crudeRegion: "padd1" }));
    await waitForPage(
      cdp,
      "!document.querySelector('#crudeRunsSheet')?.hidden && document.querySelectorAll('#crudeRunsTable tr').length > 0 && document.querySelectorAll('#crudeRunsChartGrid .chartCard').length > 0",
    );
    await runInPage(cdp, finishMeasureScript("codex-crude", "codex-crude-runs-click-to-render"));
  }));

  const summary = {
    runStartedAt,
    runEndedAt: new Date().toISOString(),
    product: PRODUCT,
    url: startUrl,
    chrome: basename(CHROME_PATH),
    headless: HEADLESS,
    outDir: OUT_DIR,
    phases,
  };
  const summaryPath = join(OUT_DIR, `${PRODUCT}-summary.json`);
  writeFileSync(summaryPath, JSON.stringify(summary, null, 2) + "\n");
  console.log(JSON.stringify(summary, null, 2));
  console.log(`Trace summary written to ${summaryPath}`);
} catch (error) {
  const failure = {
    runStartedAt: scriptStartedAt,
    runEndedAt: new Date().toISOString(),
    product: PRODUCT,
    host: HOST,
    port: PORT,
    chrome: CHROME_PATH ? basename(CHROME_PATH) : null,
    headless: HEADLESS,
    outDir: OUT_DIR,
    status: "failed",
    error: error instanceof Error
      ? { name: error.name, message: error.message, stack: error.stack }
      : { name: "Error", message: String(error) },
  };
  const failurePath = join(OUT_DIR, `${PRODUCT}-failure-summary.json`);
  writeFileSync(failurePath, JSON.stringify(failure, null, 2) + "\n");
  console.error(`Trace failure summary written to ${failurePath}`);
  throw error;
} finally {
  cdp?.close();
  if (chrome && !KEEP_BROWSER) {
    chrome.process.kill("SIGTERM");
    await delay(250);
  }
  if (server?.started) server.process.kill("SIGTERM");
  if (chrome && !KEEP_BROWSER) rmSync(chrome.userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 120 });
}

function hasArg(name) {
  return process.argv.includes(`--${name}`);
}

function argValue(name) {
  const prefix = `--${name}=`;
  const inline = process.argv.find((arg) => arg.startsWith(prefix));
  if (inline) return inline.slice(prefix.length);
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : "";
}

function findChrome() {
  const candidates = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ];
  return candidates.find((candidate) => existsSync(candidate)) || "";
}

async function ensureDashboardServer() {
  const healthUrl = `http://${HOST}:${PORT}/api/health`;
  if (await healthOk(healthUrl)) return { started: false, process: null };

  const child = spawn("npm", ["run", "dashboard:server"], {
    cwd: ROOT,
    env: { ...process.env, DASHBOARD_UPDATE_HOST: HOST, DASHBOARD_UPDATE_PORT: String(PORT), FORCE_COLOR: "0" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stdout.on("data", (chunk) => {
    output += chunk.toString("utf8");
  });
  child.stderr.on("data", (chunk) => {
    output += chunk.toString("utf8");
  });

  const startedAt = Date.now();
  while (Date.now() - startedAt < TIMEOUT_MS) {
    if (await healthOk(healthUrl)) return { started: true, process: child };
    if (child.exitCode !== null) break;
    await delay(150);
  }

  child.kill("SIGTERM");
  throw new Error(`Dashboard server did not become available at ${healthUrl}.\n${output.trim()}`);
}

async function healthOk(url) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

async function launchChrome() {
  const userDataDir = mkdtempSync(join(tmpdir(), "balance-dashboard-chrome-"));
  const args = [
    `--user-data-dir=${userDataDir}`,
    "--remote-debugging-port=0",
    "--remote-debugging-address=127.0.0.1",
    "--window-size=1440,1000",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ];
  if (HEADLESS) args.unshift("--headless=new");

  const child = spawn(CHROME_PATH, args, { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk.toString("utf8");
  });

  const devToolsPath = join(userDataDir, "DevToolsActivePort");
  const startedAt = Date.now();
  while (Date.now() - startedAt < TIMEOUT_MS) {
    if (existsSync(devToolsPath)) {
      const [debugPort] = readFileSync(devToolsPath, "utf8").trim().split(/\r?\n/);
      const target = await createTarget(Number(debugPort));
      return { process: child, userDataDir, pageWsUrl: target.webSocketDebuggerUrl };
    }
    if (child.exitCode !== null) break;
    await delay(100);
  }

  child.kill("SIGTERM");
  rmSync(userDataDir, { recursive: true, force: true });
  throw new Error(`Chrome did not expose DevToolsActivePort.\n${stderr.trim()}`);
}

async function createTarget(debugPort) {
  const response = await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" });
  if (!response.ok) throw new Error(`Unable to create Chrome target: HTTP ${response.status}`);
  return response.json();
}

async function tracePhase(cdp, name, outDir, action) {
  await cdp.send("Performance.disable").catch(() => {});
  await cdp.send("Performance.enable", { timeDomain: "timeTicks" });
  await cdp.send("Tracing.start", {
    transferMode: "ReturnAsStream",
    categories: [
      "blink.user_timing",
      "devtools.timeline",
      "disabled-by-default-devtools.timeline",
      "disabled-by-default-v8.cpu_profiler",
      "loading",
      "toplevel",
      "v8",
    ].join(","),
  });
  const started = Date.now();
  await action();
  await settleFrames(cdp);
  const tracingComplete = cdp.waitFor("Tracing.tracingComplete", TIMEOUT_MS);
  await cdp.send("Tracing.end");
  const { stream } = await tracingComplete;
  const traceText = await readStream(cdp, stream);
  const tracePath = join(outDir, `${PRODUCT}-${name}.trace.json`);
  writeFileSync(tracePath, traceText);
  const metrics = await phaseSnapshot(cdp, name, tracePath, Date.now() - started);
  return metrics;
}

async function readStream(cdp, stream) {
  let text = "";
  while (true) {
    const chunk = await cdp.send("IO.read", { handle: stream });
    text += chunk.data || "";
    if (chunk.eof) break;
  }
  await cdp.send("IO.close", { handle: stream }).catch(() => {});
  return text;
}

async function phaseSnapshot(cdp, phase, tracePath, wallMs) {
  const metrics = await cdp.send("Performance.getMetrics");
  const metricMap = Object.fromEntries((metrics.metrics || []).map((metric) => [metric.name, metric.value]));
  const page = await runInPage(cdp, `(() => {
    const measures = Object.fromEntries(performance.getEntriesByType('measure').map(entry => [entry.name, Number(entry.duration.toFixed(2))]));
    const resources = performance.getEntriesByType('resource')
      .filter(entry => /balance_runtime|index\\.html|bundle\\.json/.test(entry.name))
      .map(entry => ({
        name: entry.name.split('/').slice(-2).join('/'),
        durationMs: Number(entry.duration.toFixed(2)),
        transferSize: entry.transferSize || 0,
        decodedBodySize: entry.decodedBodySize || 0,
      }));
    return {
      title: document.title,
      url: location.href,
      h1: document.querySelector('h1')?.textContent || '',
      activeFrequency: document.querySelector('[data-frequency].active')?.dataset.frequency || '',
      activeSheet: ['balance','charts','crude','outages','reference'].find(key => !document.querySelector('#' + (key === 'balance' ? 'balanceSheet' : key === 'charts' ? 'chartsSheet' : key === 'crude' ? 'crudeRunsSheet' : key === 'outages' ? 'outagesSheet' : 'referenceSheet'))?.hidden) || '',
      balanceRows: document.querySelectorAll('#balanceTable tbody tr').length,
      chartCards: document.querySelectorAll('#chartGrid .chartCard').length,
      crudeRows: document.querySelectorAll('#crudeRunsTable tr').length,
      crudeChartCards: document.querySelectorAll('#crudeRunsChartGrid .chartCard').length,
      measures,
      resources,
      paints: performance.getEntriesByType('paint').map(entry => ({name: entry.name, startTimeMs: Number(entry.startTime.toFixed(2))})),
      navigation: performance.getEntriesByType('navigation').map(entry => ({
        domContentLoadedMs: Number(entry.domContentLoadedEventEnd.toFixed(2)),
        loadEventEndMs: Number(entry.loadEventEnd.toFixed(2)),
        durationMs: Number(entry.duration.toFixed(2)),
      }))[0] || null,
    };
  })()`);
  return {
    phase,
    wallMs,
    tracePath,
    clickToRenderMs: Object.values(page.measures || {}).at(-1) || null,
    page,
    chromeMetrics: {
      taskDurationMs: secondsToMs(metricMap.TaskDuration),
      scriptDurationMs: secondsToMs(metricMap.ScriptDuration),
      layoutDurationMs: secondsToMs(metricMap.LayoutDuration),
      recalcStyleDurationMs: secondsToMs(metricMap.RecalcStyleDuration),
      jsHeapUsedBytes: Math.round(metricMap.JSHeapUsedSize || 0),
      nodes: Math.round(metricMap.Nodes || 0),
      documents: Math.round(metricMap.Documents || 0),
    },
  };
}

function secondsToMs(value) {
  return Number.isFinite(value) ? Number((value * 1000).toFixed(2)) : null;
}

function markAndClickScript(mark, selector) {
  const missingMessage = JSON.stringify(`Missing selector ${selector}`);
  return `(() => {
    performance.mark('${mark}-start');
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) throw new Error(${missingMessage});
    element.click();
    return true;
  })()`;
}

function markAndApplyViewStateScript(mark, patch) {
  return `(async () => {
    performance.mark('${mark}-start');
    if (typeof applyViewState !== 'function') throw new Error('Missing applyViewState');
    await applyViewState({ ...state, ...${JSON.stringify(patch)} });
    return true;
  })()`;
}

function finishMeasureScript(mark, measure) {
  return `(async () => {
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
    performance.mark('${mark}-end');
    performance.measure('${measure}', '${mark}-start', '${mark}-end');
    return performance.getEntriesByName('${measure}').at(-1)?.duration || 0;
  })()`;
}

async function settleFrames(cdp) {
  await runInPage(cdp, "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
}

async function waitForPage(cdp, predicate) {
  const timeoutMessage = JSON.stringify(`Timed out waiting for: ${predicate}`);
  const expression = `(async () => {
    const started = performance.now();
    while (performance.now() - started < ${TIMEOUT_MS}) {
      if (${predicate}) return true;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error(${timeoutMessage});
  })()`;
  return runInPage(cdp, expression, TIMEOUT_MS + 5000);
}

async function runInPage(cdp, expression, timeoutMs = TIMEOUT_MS) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
    timeout: timeoutMs,
  });
  if (result.exceptionDetails) {
    const text = result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime.evaluate failed";
    throw new Error(text);
  }
  return result.result?.value;
}
