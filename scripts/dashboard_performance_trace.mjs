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
const PRODUCT_ARG = argValue("product") || process.env.DASHBOARD_TRACE_PRODUCT || "diesel";
const OUT_DIR = resolve(argValue("out-dir") || process.env.DASHBOARD_TRACE_OUT_DIR || join(tmpdir(), "balance-dashboard-traces"));
const HEADLESS = !hasArg("headed") && process.env.DASHBOARD_TRACE_HEADED !== "1";
const KEEP_BROWSER = hasArg("keep-browser") || process.env.DASHBOARD_TRACE_KEEP_BROWSER === "1";
const CHROME_PATH = argValue("chrome") || process.env.CHROME_PATH || findChrome();
const TIMEOUT_MS = Number(argValue("timeout-ms") || process.env.DASHBOARD_TRACE_TIMEOUT_MS || 45000);
const BASELINE_PATH = argValue("baseline") || process.env.DASHBOARD_TRACE_BASELINE || "";
const BASELINE_OUT_PATH = argValue("baseline-out") || process.env.DASHBOARD_TRACE_BASELINE_OUT || "";
const WRITE_BASELINE = hasArg("write-baseline") || process.env.DASHBOARD_TRACE_WRITE_BASELINE === "1";
const FAIL_ON_BUDGET = hasArg("fail-on-budget") || process.env.DASHBOARD_TRACE_FAIL_ON_BUDGET === "1";
const REGRESSION_TOLERANCE = boundedNumber(argValue("regression-tolerance") || process.env.DASHBOARD_TRACE_REGRESSION_TOLERANCE, 0.2, 0.05, 2);
const BUDGET_MULTIPLIER = boundedNumber(argValue("budget-multiplier") || process.env.DASHBOARD_TRACE_BUDGET_MULTIPLIER, 1, 0.25, 5);

const DEFAULT_PHASE_BUDGETS = {
  "initial-load": {
    wallMs: 3200,
    taskDurationMs: 900,
    scriptDurationMs: 650,
    layoutDurationMs: 180,
    jsHeapUsedBytes: 160_000_000,
    nodes: 18000,
  },
  "weekly-lazy-chunk": {
    wallMs: 1800,
    clickToRenderMs: 950,
    taskDurationMs: 700,
    scriptDurationMs: 450,
    layoutDurationMs: 160,
    jsHeapUsedBytes: 180_000_000,
    nodes: 19000,
  },
  "chart-sheet-render": {
    wallMs: 2600,
    clickToRenderMs: 1500,
    taskDurationMs: 1100,
    scriptDurationMs: 800,
    layoutDurationMs: 260,
    jsHeapUsedBytes: 220_000_000,
    nodes: 26000,
  },
  "crude-runs-render": {
    wallMs: 2400,
    clickToRenderMs: 1400,
    taskDurationMs: 950,
    scriptDurationMs: 650,
    layoutDurationMs: 260,
    jsHeapUsedBytes: 230_000_000,
    nodes: 28000,
  },
  "reference-diagnostics-render": {
    wallMs: 2200,
    clickToRenderMs: 1200,
    taskDurationMs: 800,
    scriptDurationMs: 520,
    layoutDurationMs: 180,
    jsHeapUsedBytes: 220_000_000,
    nodes: 26000,
  },
};

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
    this.listeners = new Map();
    ws.addEventListener("message", (event) => this.handleMessage(event));
    ws.addEventListener("close", () => {
      for (const { reject } of this.pending.values()) reject(new Error("CDP websocket closed"));
      this.pending.clear();
    });
  }

  on(method, listener) {
    const rows = this.listeners.get(method) || [];
    rows.push(listener);
    this.listeners.set(method, rows);
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
    const params = message.params || {};
    const listeners = this.listeners.get(message.method) || [];
    listeners.forEach((listener) => {
      try {
        listener(params);
      } catch {
        // Keep diagnostics best-effort so trace collection never fails because of logging.
      }
    });
    const rows = this.waiters.get(message.method) || [];
    if (!rows.length) return;
    const [row, ...rest] = rows;
    this.waiters.set(message.method, rest);
    row.resolve(params);
  }

  close() {
    this.ws.close();
  }
}

if (!["diesel", "jet", "all"].includes(PRODUCT_ARG)) {
  throw new Error("--product must be diesel, jet, or all");
}

if (!CHROME_PATH) {
  throw new Error("Chrome was not found. Set CHROME_PATH to a Chrome or Chromium executable.");
}

await mkdir(OUT_DIR, { recursive: true });

const scriptStartedAt = new Date().toISOString();
let server = null;
let chrome = null;
let cdp = null;
const pageDiagnostics = [];
let activeProduct = PRODUCT_ARG === "all" ? "all" : PRODUCT_ARG;

try {
  server = await ensureDashboardServer();
  chrome = await launchChrome();
  cdp = await CdpClient.connect(chrome.pageWsUrl);

  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Network.enable");
  await cdp.send("Performance.enable", { timeDomain: "timeTicks" });
  cdp.on("Runtime.exceptionThrown", (params) => {
    const details = params.exceptionDetails || {};
    pageDiagnostics.push({
      type: "exception",
      text: details.text || "",
      url: details.url || "",
      lineNumber: details.lineNumber,
      columnNumber: details.columnNumber,
      description: details.exception?.description || details.exception?.value || "",
    });
  });
  cdp.on("Runtime.consoleAPICalled", (params) => {
    if (!["error", "warning", "assert"].includes(params.type)) return;
    pageDiagnostics.push({
      type: `console.${params.type}`,
      text: (params.args || []).map((arg) => arg.value ?? arg.description ?? "").filter(Boolean).join(" "),
    });
  });
  cdp.on("Log.entryAdded", (params) => {
    const entry = params.entry || {};
    if (!["error", "warning"].includes(entry.level)) return;
    pageDiagnostics.push({
      type: `log.${entry.level}`,
      text: entry.text || "",
      url: entry.url || "",
      lineNumber: entry.lineNumber,
    });
  });

  const products = PRODUCT_ARG === "all" ? ["diesel", "jet"] : [PRODUCT_ARG];
  const summaries = [];
  for (const product of products) {
    activeProduct = product;
    const summary = await traceProduct(product);
    summaries.push(summary);
    const summaryPath = join(OUT_DIR, `${product}-summary.json`);
    writeFileSync(summaryPath, JSON.stringify(summary, null, 2) + "\n");
    console.log(JSON.stringify(summary, null, 2));
    console.log(`Trace summary written to ${summaryPath}`);
  }
  const baseline = BASELINE_PATH ? readTraceBaseline(BASELINE_PATH) : null;
  const optimizationReport = buildOptimizationReport(summaries, baseline);
  const reportPath = join(OUT_DIR, "optimization-report.json");
  const markdownPath = join(OUT_DIR, "optimization-report.md");
  writeFileSync(reportPath, JSON.stringify(optimizationReport, null, 2) + "\n");
  writeFileSync(markdownPath, optimizationReportMarkdown(optimizationReport));
  console.log(`Optimization report written to ${reportPath}`);
  console.log(optimizationReportConsoleSummary(optimizationReport));
  if (WRITE_BASELINE || BASELINE_OUT_PATH) {
    const baselineOutPath = resolve(BASELINE_OUT_PATH || join(OUT_DIR, "dashboard-performance-baseline.json"));
    writeFileSync(baselineOutPath, JSON.stringify(currentBaselinePayload(summaries), null, 2) + "\n");
    console.log(`Trace baseline written to ${baselineOutPath}`);
  }
  if (PRODUCT_ARG === "all") {
    const allSummaryPath = join(OUT_DIR, "all-summary.json");
    writeFileSync(allSummaryPath, JSON.stringify({ runEndedAt: new Date().toISOString(), outDir: OUT_DIR, products: summaries, optimizationReport }, null, 2) + "\n");
    console.log(`Combined trace summary written to ${allSummaryPath}`);
  }
  if (FAIL_ON_BUDGET && optimizationReport.status !== "ok") {
    process.exitCode = 1;
  }
} catch (error) {
  const failure = {
    runStartedAt: scriptStartedAt,
    runEndedAt: new Date().toISOString(),
    product: activeProduct,
    host: HOST,
    port: PORT,
    chrome: CHROME_PATH ? basename(CHROME_PATH) : null,
    headless: HEADLESS,
    outDir: OUT_DIR,
    status: "failed",
    error: error instanceof Error
      ? { name: error.name, message: error.message, stack: error.stack }
      : { name: "Error", message: String(error) },
    pageDiagnostics: pageDiagnostics.slice(-30),
  };
  const failurePath = join(OUT_DIR, `${activeProduct}-failure-summary.json`);
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

async function traceProduct(product) {
  const productDir = product === "diesel" ? "Diesel_Balance" : "Jet_Balance";
  const startUrl = `http://${HOST}:${PORT}/${productDir}/index.html`;
  const runStartedAt = new Date().toISOString();
  const phases = [];

  phases.push(await tracePhase(cdp, product, "initial-load", OUT_DIR, async () => {
    const loadEvent = cdp.waitFor("Page.loadEventFired", TIMEOUT_MS);
    await cdp.send("Page.navigate", { url: startUrl });
    await loadEvent;
    await waitForPage(cdp, "document.querySelector('h1') && document.querySelectorAll('#balanceTable tbody tr').length > 0");
  }));

  phases.push(await tracePhase(cdp, product, "weekly-lazy-chunk", OUT_DIR, async () => {
    await runInPage(cdp, markAndClickScript("codex-weekly", "[data-frequency='weekly']"));
    await waitForPage(
      cdp,
      "document.querySelector(\"[data-frequency='weekly'].active\") && window.BALANCE_DATA?.regionalBalance?.weekly?.length > 0 && document.querySelectorAll('#balanceTable tbody tr').length > 0",
    );
    await runInPage(cdp, finishMeasureScript("codex-weekly", "codex-weekly-click-to-render"));
  }));

  phases.push(await tracePhase(cdp, product, "chart-sheet-render", OUT_DIR, async () => {
    await runInPage(cdp, markAndApplyViewStateScript("codex-charts", { sheet: "charts" }));
    await waitForPage(
      cdp,
      "!document.querySelector('#chartsSheet')?.hidden && document.querySelectorAll('#chartGrid .chartCard').length > 0 && document.querySelectorAll('#chartGrid svg.seasonChart path').length > 0",
    );
    await runInPage(cdp, finishMeasureScript("codex-charts", "codex-chart-sheet-click-to-render"));
  }));

  phases.push(await tracePhase(cdp, product, "crude-runs-render", OUT_DIR, async () => {
    await runInPage(cdp, markAndApplyViewStateScript("codex-crude", { sheet: "crude", crudeRegion: "padd1" }));
    await waitForPage(
      cdp,
      "!document.querySelector('#crudeRunsSheet')?.hidden && document.querySelectorAll('#crudeRunsTable tr').length > 0 && document.querySelectorAll('#crudeRunsChartGrid .chartCard').length > 0",
    );
    await runInPage(cdp, finishMeasureScript("codex-crude", "codex-crude-runs-click-to-render"));
  }));

  phases.push(await tracePhase(cdp, product, "reference-diagnostics-render", OUT_DIR, async () => {
    await runInPage(cdp, markAndClickScript("codex-reference", "#referenceSheetBtn"));
    await waitForPage(
      cdp,
      "!document.querySelector('#referenceSheet')?.hidden && document.querySelectorAll('#optimizationDiagnostics [data-optimization-card]').length >= 4 && document.querySelectorAll('#sourceGrid .sourceCard').length > 0",
    );
    await runInPage(cdp, finishMeasureScript("codex-reference", "codex-reference-click-to-render"));
  }));

  return {
    runStartedAt,
    runEndedAt: new Date().toISOString(),
    product,
    url: startUrl,
    chrome: basename(CHROME_PATH),
    headless: HEADLESS,
    outDir: OUT_DIR,
    phases,
  };
}

function boundedNumber(raw, fallback, min, max) {
  const value = Number(raw);
  if (!Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, value));
}

function readTraceBaseline(path) {
  const payload = JSON.parse(readFileSync(resolve(path), "utf8"));
  return normalizeBaselinePayload(payload);
}

function normalizeBaselinePayload(payload) {
  const products = Array.isArray(payload?.products) ? payload.products : Array.isArray(payload) ? payload : [];
  const index = new Map();
  for (const product of products) {
    if (!product?.product || !Array.isArray(product.phases)) continue;
    index.set(product.product, new Map(product.phases.map((phase) => [phase.phase, phase])));
  }
  return { products: index, sourceRunEndedAt: payload?.runEndedAt || payload?.generatedAt || "" };
}

function currentBaselinePayload(summaries) {
  return {
    generatedAt: new Date().toISOString(),
    products: summaries.map((summary) => ({
      product: summary.product,
      phases: summary.phases.map((phase) => ({
        phase: phase.phase,
        wallMs: phase.wallMs,
        clickToRenderMs: phase.clickToRenderMs,
        chromeMetrics: {
          taskDurationMs: phase.chromeMetrics?.taskDurationMs ?? null,
          scriptDurationMs: phase.chromeMetrics?.scriptDurationMs ?? null,
          layoutDurationMs: phase.chromeMetrics?.layoutDurationMs ?? null,
          jsHeapUsedBytes: phase.chromeMetrics?.jsHeapUsedBytes ?? null,
          nodes: phase.chromeMetrics?.nodes ?? null,
        },
      })),
    })),
  };
}

function buildOptimizationReport(summaries, baseline) {
  const findings = [];
  for (const summary of summaries) {
    for (const phase of summary.phases) {
      const budgets = DEFAULT_PHASE_BUDGETS[phase.phase] || {};
      for (const [metric, rawLimit] of Object.entries(budgets)) {
        const value = phaseMetricValue(phase, metric);
        const limit = rawLimit * BUDGET_MULTIPLIER;
        if (!Number.isFinite(value) || value <= limit) continue;
        findings.push({
          type: "budget",
          status: "watch",
          product: summary.product,
          phase: phase.phase,
          metric,
          value,
          limit,
          deltaPct: percentOver(value, limit),
          message: `${summary.product} ${phase.phase} ${metric} exceeded budget by ${percentOver(value, limit)}%.`,
        });
      }
      const baselinePhase = baseline?.products.get(summary.product)?.get(phase.phase);
      if (baselinePhase) {
        for (const metric of budgetedMetricNames()) {
          const currentValue = phaseMetricValue(phase, metric);
          const baselineValue = phaseMetricValue(baselinePhase, metric);
          if (!Number.isFinite(currentValue) || !Number.isFinite(baselineValue) || baselineValue <= 0) continue;
          const delta = currentValue - baselineValue;
          if (delta <= minimumRegressionDelta(metric)) continue;
          const ratio = delta / baselineValue;
          if (ratio <= REGRESSION_TOLERANCE) continue;
          findings.push({
            type: "baseline",
            status: "regressed",
            product: summary.product,
            phase: phase.phase,
            metric,
            value: currentValue,
            baseline: baselineValue,
            deltaPct: roundNumber(ratio * 100, 1),
            message: `${summary.product} ${phase.phase} ${metric} regressed ${roundNumber(ratio * 100, 1)}% from baseline.`,
          });
        }
      }
    }
  }
  const crossProductFindings = crossProductComparisons(summaries);
  const status = findings.some((finding) => finding.status === "regressed")
    ? "regressed"
    : findings.length || crossProductFindings.length
      ? "watch"
      : "ok";
  return {
    generatedAt: new Date().toISOString(),
    status,
    outDir: OUT_DIR,
    productMode: PRODUCT_ARG,
    budgetMultiplier: BUDGET_MULTIPLIER,
    regressionTolerancePct: roundNumber(REGRESSION_TOLERANCE * 100, 1),
    baseline: BASELINE_PATH ? { path: resolve(BASELINE_PATH), runEndedAt: baseline?.sourceRunEndedAt || "" } : null,
    findings,
    crossProductFindings,
    recommendations: optimizationRecommendations(findings, crossProductFindings, Boolean(baseline)),
  };
}

function budgetedMetricNames() {
  return Array.from(new Set(Object.values(DEFAULT_PHASE_BUDGETS).flatMap((budget) => Object.keys(budget))));
}

function phaseMetricValue(phase, metric) {
  const direct = Number(phase?.[metric]);
  if (Number.isFinite(direct)) return direct;
  const chrome = Number(phase?.chromeMetrics?.[metric]);
  return Number.isFinite(chrome) ? chrome : NaN;
}

function minimumRegressionDelta(metric) {
  if (metric === "jsHeapUsedBytes") return 5_000_000;
  if (metric === "nodes") return 500;
  return 75;
}

function crossProductComparisons(summaries) {
  if (summaries.length < 2) return [];
  const products = summaries.map((summary) => summary.product).join(" vs ");
  const phaseNames = Array.from(new Set(summaries.flatMap((summary) => summary.phases.map((phase) => phase.phase))));
  const findings = [];
  for (const phaseName of phaseNames) {
    const phaseRows = summaries
      .map((summary) => ({ product: summary.product, phase: summary.phases.find((phase) => phase.phase === phaseName) }))
      .filter((row) => row.phase);
    if (phaseRows.length < 2) continue;
    for (const metric of ["wallMs", "clickToRenderMs", "taskDurationMs", "scriptDurationMs", "jsHeapUsedBytes", "nodes"]) {
      const values = phaseRows
        .map((row) => ({ product: row.product, value: phaseMetricValue(row.phase, metric) }))
        .filter((row) => Number.isFinite(row.value));
      if (values.length < 2) continue;
      const sorted = values.slice().sort((a, b) => b.value - a.value);
      const high = sorted[0];
      const low = sorted.at(-1);
      const delta = high.value - low.value;
      const ratio = low.value > 0 ? delta / low.value : 0;
      const phaseBudget = DEFAULT_PHASE_BUDGETS[phaseName]?.[metric];
      if (Number.isFinite(phaseBudget) && high.value < phaseBudget * BUDGET_MULTIPLIER * 0.8) continue;
      if (delta <= minimumCrossProductDelta(metric) || ratio <= 0.35) continue;
      findings.push({
        status: "watch",
        phase: phaseName,
        metric,
        products,
        highProduct: high.product,
        lowProduct: low.product,
        highValue: high.value,
        lowValue: low.value,
        deltaPct: roundNumber(ratio * 100, 1),
        message: `${high.product} ${phaseName} ${metric} is ${roundNumber(ratio * 100, 1)}% above ${low.product}.`,
      });
    }
  }
  return findings;
}

function minimumCrossProductDelta(metric) {
  if (metric === "jsHeapUsedBytes") return 10_000_000;
  if (metric === "nodes") return 1000;
  return 150;
}

function optimizationRecommendations(findings, crossProductFindings, hasBaseline) {
  const recommendations = [];
  const add = (key, priority, detail) => {
    if (recommendations.some((row) => row.key === key)) return;
    recommendations.push({ key, priority, detail });
  };
  if (!hasBaseline) add("capture-baseline", "maintain", "Write a baseline with --write-baseline after a known-good run so later traces can flag regressions automatically.");
  if (PRODUCT_ARG !== "all") add("trace-all", "maintain", "Run with --product=all when checking optimization so Diesel and Jet stay comparable.");
  if (findings.some((finding) => finding.phase === "chart-sheet-render")) add("chart-hydration", "watch", "Review chart card shell rendering and hydration if chart-sheet-render remains above budget.");
  if (findings.some((finding) => finding.phase === "weekly-lazy-chunk")) add("weekly-table", "watch", "Inspect weekly lazy chunk size and balance-table render signatures if weekly switching stays above budget.");
  if (findings.some((finding) => finding.phase === "crude-runs-render")) add("crude-sheet", "watch", "Inspect crude-runs table period windows and chart hydration if crude rendering stays above budget.");
  if (findings.some((finding) => finding.phase === "reference-diagnostics-render")) add("reference-payload", "watch", "Check reference payload growth before adding new source inventories or refinery rows.");
  if (crossProductFindings.length) add("product-asymmetry", "investigate", "Review cross-product findings before treating Diesel/Jet performance differences as acceptable product asymmetry.");
  if (!findings.length && !crossProductFindings.length) add("maintain-current-split", "maintain", "No budget or Diesel/Jet asymmetry findings; keep the current lazy chunk split and repeat traces after material UI changes.");
  return recommendations;
}

function percentOver(value, limit) {
  return roundNumber((value - limit) / Math.max(limit, 1) * 100, 1);
}

function roundNumber(value, digits = 1) {
  const factor = 10 ** digits;
  return Math.round(Number(value || 0) * factor) / factor;
}

function formatMetric(metric, value) {
  if (!Number.isFinite(Number(value))) return "n/a";
  if (metric === "jsHeapUsedBytes") return `${roundNumber(Number(value) / 1024 / 1024, 1)} MB`;
  if (metric === "nodes") return `${Math.round(Number(value)).toLocaleString("en-US")} nodes`;
  return `${roundNumber(Number(value), 1)} ms`;
}

function optimizationReportConsoleSummary(report) {
  const total = report.findings.length + report.crossProductFindings.length;
  const first = report.findings[0]?.message || report.crossProductFindings[0]?.message || "no findings";
  return `Optimization status: ${report.status} (${total} findings); ${first}`;
}

function optimizationReportMarkdown(report) {
  const findingRows = report.findings.length
    ? report.findings.map((finding) => `| ${mdCell(finding.type)} | ${mdCell(finding.product)} | ${mdCell(finding.phase)} | ${mdCell(finding.metric)} | ${mdCell(formatMetric(finding.metric, finding.value))} | ${mdCell(formatMetric(finding.metric, finding.limit ?? finding.baseline))} | ${mdCell(String(finding.deltaPct ?? ""))}% |`).join("\n")
    : "| none |  |  |  |  |  |  |";
  const crossRows = report.crossProductFindings.length
    ? report.crossProductFindings.map((finding) => `| ${mdCell(finding.phase)} | ${mdCell(finding.metric)} | ${mdCell(finding.highProduct)} | ${mdCell(formatMetric(finding.metric, finding.highValue))} | ${mdCell(finding.lowProduct)} | ${mdCell(formatMetric(finding.metric, finding.lowValue))} | ${mdCell(String(finding.deltaPct))}% |`).join("\n")
    : "| none |  |  |  |  |  |  |";
  const recommendations = report.recommendations.map((row) => `- ${row.priority}: ${row.detail}`).join("\n") || "- none";
  return [
    "# Dashboard Optimization Report",
    "",
    `Status: ${report.status}`,
    `Generated: ${report.generatedAt}`,
    `Output: ${report.outDir}`,
    `Budget multiplier: ${report.budgetMultiplier}`,
    `Regression tolerance: ${report.regressionTolerancePct}%`,
    "",
    "## Findings",
    "",
    "| Type | Product | Phase | Metric | Value | Limit/Baseline | Delta |",
    "| --- | --- | --- | --- | ---: | ---: | ---: |",
    findingRows,
    "",
    "## Diesel/Jet Comparisons",
    "",
    "| Phase | Metric | Higher | Higher Value | Lower | Lower Value | Delta |",
    "| --- | --- | --- | ---: | --- | ---: | ---: |",
    crossRows,
    "",
    "## Recommendations",
    "",
    recommendations,
    "",
  ].join("\n");
}

function mdCell(value) {
  return String(value ?? "").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
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

async function tracePhase(cdp, product, name, outDir, action) {
  await cdp.send("Performance.disable").catch(() => {});
  await cdp.send("Performance.enable", { timeDomain: "timeTicks" });
  const beforeMetrics = await cdp.send("Performance.getMetrics").catch(() => ({ metrics: [] }));
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
  const tracePath = join(outDir, `${product}-${name}.trace.json`);
  writeFileSync(tracePath, traceText);
  const metrics = await phaseSnapshot(cdp, name, tracePath, Date.now() - started, beforeMetrics);
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

async function phaseSnapshot(cdp, phase, tracePath, wallMs, beforeMetrics = { metrics: [] }) {
  const metrics = await cdp.send("Performance.getMetrics");
  const metricMap = Object.fromEntries((metrics.metrics || []).map((metric) => [metric.name, metric.value]));
  const beforeMetricMap = Object.fromEntries((beforeMetrics.metrics || []).map((metric) => [metric.name, metric.value]));
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
      taskDurationMs: secondsDeltaToMs(metricMap.TaskDuration, beforeMetricMap.TaskDuration),
      scriptDurationMs: secondsDeltaToMs(metricMap.ScriptDuration, beforeMetricMap.ScriptDuration),
      layoutDurationMs: secondsDeltaToMs(metricMap.LayoutDuration, beforeMetricMap.LayoutDuration),
      recalcStyleDurationMs: secondsDeltaToMs(metricMap.RecalcStyleDuration, beforeMetricMap.RecalcStyleDuration),
      jsHeapUsedBytes: Math.round(metricMap.JSHeapUsedSize || 0),
      nodes: Math.round(metricMap.Nodes || 0),
      documents: Math.round(metricMap.Documents || 0),
    },
  };
}

function secondsToMs(value) {
  return Number.isFinite(value) ? Number((value * 1000).toFixed(2)) : null;
}

function secondsDeltaToMs(value, beforeValue) {
  if (!Number.isFinite(value)) return null;
  const before = Number.isFinite(beforeValue) ? beforeValue : 0;
  return secondsToMs(Math.max(0, value - before));
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
