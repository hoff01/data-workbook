import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { sha256 } from "./common.js";

type ProductKey = "diesel" | "jet";

type DashboardBundle = {
  product: {
    key: ProductKey;
  };
  generatedAt: string;
  freshness: {
    latestMonthly: string;
    latestWeekly: string;
    monthlyRows?: number;
    weeklyRows?: number;
  };
  checksums: Record<string, string>;
  sourceFiles: Array<{
    role: string;
    path: string;
    checksum?: string;
  }>;
  sourceHub?: {
    sources?: Array<{
      key: string;
      latest?: string;
    }>;
  };
  regionalBalance?: {
    weekly?: unknown[];
  };
  crudeRuns?: {
    weekly?: unknown[];
  };
};

type RuntimeBase = {
  product?: {
    key?: string;
  };
  generatedAt?: string;
  freshness?: DashboardBundle["freshness"];
  regionalBalance?: {
    movementFlows?: RegionalMovementFlow[];
  };
  optimization?: {
    runtimePlan?: {
      baseRows?: number;
      lazyRows?: number;
      lazyRowSharePct?: number;
    };
    lazyChunks?: unknown[];
    recommendations?: unknown[];
  };
};

type RuntimeWeekly = {
  regionalBalance?: {
    weekly?: unknown[];
  };
};

type RegionalMovementFlow = {
  id?: string;
  fromRegionKey?: string;
  toRegionKey?: string;
};

type RuntimeCrudeWeekly = {
  crudeRuns?: {
    weekly?: unknown[];
  };
};

type RuntimeReference = {
  sourceHub?: DashboardBundle["sourceHub"];
  sourceFiles?: DashboardBundle["sourceFiles"];
  checksums?: DashboardBundle["checksums"];
};

type BalanceManifest = {
  generatedAt: string;
  latestMonthly: string;
  latestWeekly: string;
};

type ProductConfig = {
  key: ProductKey;
  folder: string;
  monthlyCsv: string;
  weeklyCsv: string;
  manifestPath: string;
  indexPath: string;
  runtimeBasePath: string;
  runtimeWeeklyPath: string;
  runtimeCrudeWeeklyPath: string;
  runtimeReferencePath: string;
};

const PRODUCTS: ProductConfig[] = [
  {
    key: "diesel",
    folder: "Diesel_Balance",
    monthlyCsv: "eia_monthly/diesel.csv",
    weeklyCsv: "eia_weekly/diesel.csv",
    manifestPath: "Diesel_Balance/manifest.json",
    indexPath: "Diesel_Balance/index.html",
    runtimeBasePath: "Diesel_Balance/data/diesel_balance_runtime_base.js",
    runtimeWeeklyPath: "Diesel_Balance/data/diesel_balance_runtime_weekly.js",
    runtimeCrudeWeeklyPath: "Diesel_Balance/data/diesel_balance_runtime_crude_weekly.js",
    runtimeReferencePath: "Diesel_Balance/data/diesel_balance_runtime_reference.js",
  },
  {
    key: "jet",
    folder: "Jet_Balance",
    monthlyCsv: "eia_monthly/jet.csv",
    weeklyCsv: "eia_weekly/jet.csv",
    manifestPath: "Jet_Balance/manifest.json",
    indexPath: "Jet_Balance/index.html",
    runtimeBasePath: "Jet_Balance/data/jet_balance_runtime_base.js",
    runtimeWeeklyPath: "Jet_Balance/data/jet_balance_runtime_weekly.js",
    runtimeCrudeWeeklyPath: "Jet_Balance/data/jet_balance_runtime_crude_weekly.js",
    runtimeReferencePath: "Jet_Balance/data/jet_balance_runtime_reference.js",
  },
];

async function readJson<T>(path: string): Promise<T> {
  return JSON.parse(await readFile(path, "utf8")) as T;
}

async function latestCsvDate(path: string): Promise<string> {
  const text = await readFile(path, "utf8");
  const latest = text
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.split(",", 1)[0]?.trim() ?? "")
    .filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date))
    .sort()
    .at(-1);
  if (!latest) throw new Error(`${path} contains no dated rows`);
  return latest;
}

async function checksum(path: string): Promise<string> {
  return sha256(await readFile(path));
}

async function packagedChecksum(config: ProductConfig, path: string): Promise<string> {
  try {
    return await checksum(path);
  } catch {
    return checksum(join(config.folder, path));
  }
}

function sourceLatest(bundle: Pick<DashboardBundle, "sourceHub">, key: string): string {
  return bundle.sourceHub?.sources?.find((source) => source.key === key)?.latest ?? "";
}

function assertEqual(label: string, actual: string, expected: string): void {
  if (actual !== expected) throw new Error(`${label} mismatch: expected=${expected} actual=${actual}`);
}

function assertIncludes(label: string, text: string, expected: string): void {
  if (!text.includes(expected)) throw new Error(`${label} missing expected text: ${expected}`);
}

function assertNotIncludes(label: string, text: string, unexpected: string): void {
  if (text.includes(unexpected)) throw new Error(`${label} contains unexpected text: ${unexpected}`);
}

function verifyUsMovementCoverage(config: ProductConfig, runtimeBase: RuntimeBase): void {
  const expectedRegions = config.key === "diesel"
    ? ["padd1ab", "padd1c", "padd2", "padd3", "padd4", "padd5"]
    : ["padd1", "padd2", "padd3", "padd4", "padd5"];
  const expected = new Set(expectedRegions);
  const flows = runtimeBase.regionalBalance?.movementFlows ?? [];
  if (flows.length === 0) throw new Error(`${config.key} movement flow coverage is empty`);
  const regions = new Set<string>();
  flows.forEach((flow) => {
    if (!flow.fromRegionKey || !flow.toRegionKey) throw new Error(`${config.key} movement flow has missing endpoint`);
    if (!expected.has(flow.fromRegionKey) || !expected.has(flow.toRegionKey)) {
      throw new Error(`${config.key} movement flow ${flow.id ?? "(unknown)"} is outside the Total U.S. PADD scope`);
    }
    regions.add(flow.fromRegionKey);
    regions.add(flow.toRegionKey);
  });
  const missing = expectedRegions.filter((regionKey) => !regions.has(regionKey));
  if (missing.length) throw new Error(`${config.key} movement flow coverage missing ${missing.join(", ")}`);
}

function verifyUsGrossMovementPresentation(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} Total U.S. gross movement suppression`, indexHtml, "function showGrossInterPaddRows(regionKey){ return regionKey !== 'us'; }");
  assertIncludes(`${config.key} aggregate receipt source coverage`, indexHtml, "const sourceKeys = ['padd1','padd2','padd3','padd4','padd5']");
  assertIncludes(`${config.key} U.S. gross movement total gating`, indexHtml, "...(showGrossMovements ? [{id:'receiptsIn'");
  assertIncludes(`${config.key} U.S. shipment row gating`, indexHtml, "...(showGrossMovements ? [{id:'receiptsOut'");
}

function verifyBalanceSubtotalFormatting(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} Total Supply black subtotal class`, indexHtml, "totalSupplyRow");
  assertIncludes(`${config.key} supply subtotal gray class`, indexHtml, "supplySubtotalBand");
  assertIncludes(`${config.key} demand subtotal light-blue class`, indexHtml, "demandSubtotalBand");
  assertIncludes(`${config.key} Total Demand dark-blue class`, indexHtml, "totalDemandRow");
  assertIncludes(`${config.key} imports subtotal no longer black`, indexHtml, ".importTotalRow td{background:#dde2ea!important");
  assertIncludes(`${config.key} highlighted rows keep PADD inset`, indexHtml, ".highlightRow td:first-child{background:#fff4a8!important;color:#1f2937!important;border-left:8px solid var(--group)}");
  assertIncludes(`${config.key} balance crude runs row uses yield highlight`, indexHtml, "{id:'crudeRunsKbd',label:'Crude Runs',kind:'highlight'}");
  assertIncludes(`${config.key} production row keeps subtotal and highlight`, indexHtml, "{id:'production',label:'Production',kind:'subtotal highlight'}");
  assertIncludes(`${config.key} production row uses yellow highlight override`, indexHtml, ".productionHighlightRow td{background:#fff4a8!important;color:#1f2937!important;");
  assertIncludes(`${config.key} production row applies yellow override class`, indexHtml, "if (line.id === 'production') parts.push('productionHighlightRow');");
  assertIncludes(`${config.key} build draw rows use readable summary band`, indexHtml, ".balanceSummaryRow td{background:#e8eef6!important");
  assertIncludes(`${config.key} build draw per-day row uses grey band`, indexHtml, ".buildDailyRow td{background:#dde2ea!important");
  assertIncludes(`${config.key} build draw guide uses readable guide band`, indexHtml, ".balanceGuideRow td{background:#f5f8fc!important");
  assertIncludes(`${config.key} build draw cells are sign colored`, indexHtml, ".drawRow td.positiveValue{color:#166534!important}");
  assertIncludes(`${config.key} build draw guide cells are sign colored`, indexHtml, ".balanceGuideRow td.positiveValue{color:#166534!important}");
  assertIncludes(`${config.key} ending stocks row uses grey band`, indexHtml, ".stockRow td{background:#dde2ea!important");
  assertIncludes(`${config.key} cover row uses stock context band`, indexHtml, ".coverRow td{background:#f8fbff!important");
  assertIncludes(`${config.key} build draw summary row class`, indexHtml, "{id:'buildDaily',label:'Build/(draw) per day',kind:'balanceSummary draw'}");
  assertIncludes(`${config.key} build draw per-day row class`, indexHtml, "if (line.id === 'buildDaily') parts.push('buildDailyRow');");
  assertIncludes(`${config.key} build draw guide row class`, indexHtml, "kind:lineId === 'buildTotal' ? 'guide balanceGuide' : 'guide'");
}

function verifyBalanceSupplySpacing(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} production/import spacer row`, indexHtml, "const productionImportSpacer = productionLines.length ? [{id:'productionImportSpacer',label:'',kind:'divider supplySpacer'}] : [];");
  assertIncludes(`${config.key} spacer is before weekly imports block`, indexHtml, "...productionLines,...productionImportSpacer,...importBlockLines");
  assertIncludes(`${config.key} weekly imports row precedes override and split Kpler lines`, indexHtml, "const importBlockLines = state.frequency === 'weekly' ? [importsTotalLine,...importLines,...importTotalGuideLines,...importGuideLines] : [...importLines,importsTotalLine,...importTotalGuideLines,...importGuideLines];");
  assertIncludes(`${config.key} weekly imports adjustment uses override label`, indexHtml, "label:'Imports Override',kind:'item muted adjustment importOverride'");
  assertIncludes(`${config.key} adjustment rows render generic adjustment label`, indexHtml, "function balanceLineDisplayLabel(line){ return isBalanceAdjustmentLine(line.id) ? 'Adjustment' : line.label; }");
  assertIncludes(`${config.key} Lower Atlantic monthly imports get override`, indexHtml, "const monthlyLowerAtlanticImportGuide = state.frequency === 'monthly' && D.product?.key === 'diesel' && regionKey === 'padd1c';");
  assertIncludes(`${config.key} Northeast Kpler import total is only grey import guide`, indexHtml, "function isKplerTotalImportGuideLine(lineId){ return isKplerGuideLine(lineId) && kplerGuideTargetLineId(lineId) === 'padd1abImports'; }");
  assertIncludes(`${config.key} Northeast Kpler export total is grey`, indexHtml, "function isKplerTotalExportGuideLine(lineId){ return isKplerGuideLine(lineId) && kplerGuideTargetLineId(lineId) === 'padd1abExportsTotal'; }");
  assertIncludes(`${config.key} Kpler total imports use grey guide class`, indexHtml, "kplerImportTotalGuideRow");
  assertIncludes(`${config.key} Northeast Kpler export total uses grey guide class`, indexHtml, "kplerExportTotalGuideRow");
  assertIncludes(`${config.key} Northeast Kpler export total sums split guide rows`, indexHtml, "if (flow === 'padd1abExportsTotal')");
}

function verifyBalanceSmartWindowScroll(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} balance frequency switch clears stale viewport restore`, indexHtml, "if (state.sheet === 'balance') { clearPendingTableViewportRestore('balanceTable'); pendingBalanceScrollPeriod = ''; forceBalancePeriodScroll = true; }");
  assertIncludes(`${config.key} balance force scroll bypasses viewport restore`, indexHtml, "else if (forceScroll) { clearPendingTableViewportRestore('balanceTable'); scrollTableToPeriod('balanceTable', targetPeriod, signature, true); }");
  assertIncludes(`${config.key} balance table scroll gets delayed layout retries`, indexHtml, "const retryDelays = wrap.id === 'crudeRunsTableWrap' ? [120,360] : [40,120,360];");
}

function verifyBalanceCrudeContextLoading(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} balance sheets declare shared crude context`, indexHtml, "const needsBalanceContext = sheet === 'balance' || sheet === 'charts';");
  assertIncludes(`${config.key} weekly balance loads weekly crude runs`, indexHtml, "if (frequency === 'weekly' && (needsBalanceContext || sheet === 'crude')) await ensureCrudeWeeklyData();");
  assertIncludes(`${config.key} balance loads reference context before rendering crude-derived rows`, indexHtml, "if (needsBalanceContext || sheet === 'reference' || sheet === 'outages' || sheet === 'crude') await ensureReferenceData();");
  assertIncludes(`${config.key} frequency switches use shared data loader`, indexHtml, "try { await ensureDataForState({...state,frequency:nextFrequency}); }");
  assertIncludes(`${config.key} refresh button reloads dashboard data before rerender`, indexHtml, "document.getElementById('refreshBtn').addEventListener('click', () => { refreshDashboardData('Dashboard refreshed'); });");
  assertIncludes(`${config.key} F9 is routed through safe dashboard refresh`, indexHtml, "const isF9 = e.key === 'F9' || e.keyCode === 120;");
  assertIncludes(`${config.key} F9 recalculation loads dependencies first`, indexHtml, "refreshDashboardData('Dashboard recalculated');");
  assertIncludes(`${config.key} balance bootstrap refreshes server settings after data load`, indexHtml, "else if (state.sheet === 'balance' || state.sheet === 'charts' || state.sheet === 'outages' || state.sheet === 'crude') { refreshWorkbookSettings(); }");
}

function verifyChartTabExpansion(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} chart history minimum`, indexHtml, "const MIN_CHART_HISTORY_YEAR = 2017;");
  assertIncludes(`${config.key} chart band years exclude pre-2017`, indexHtml, "context.years.filter(year => year >= MIN_CHART_HISTORY_YEAR && year < context.currentYear)");
  assertIncludes(`${config.key} chart row filter excludes pre-2017`, indexHtml, "chartRowPeriodYear(row) >= MIN_CHART_HISTORY_YEAR");
  assertIncludes(`${config.key} requested derived chart metrics`, indexHtml, "'periodBuildDrawKb','netLengthKbd'");
  assertIncludes(`${config.key} requested receipts chart metric`, indexHtml, "'receiptsKbd'");
  assertIncludes(`${config.key} requested PADD3 shipment chart metric`, indexHtml, "'padd3ShipmentsToPadd1Kbd'");
  assertIncludes(`${config.key} Kpler chart metrics registered`, indexHtml, "const KPLER_CHART_METRICS = new Set(['kplerImportsKbd'");
  assertIncludes(`${config.key} secondary unit utilization chart metrics registered`, indexHtml, "const SECONDARY_UNIT_UTILIZATION_METRICS = new Set(['catalyticCrackingUtilizationPct','cokingUtilizationPct','hydrocrackingUtilizationPct']);");
  assertIncludes(`${config.key} secondary unit chart labels`, indexHtml, "label:'Catalytic Cracking Utilization'");
  assertIncludes(`${config.key} coking utilization chart label`, indexHtml, "label:'Coking Utilization'");
  assertIncludes(`${config.key} hydrocracking utilization chart label`, indexHtml, "label:'Hydrocracking Utilization'");
  assertIncludes(`${config.key} Kpler periods are completed only`, indexHtml, "function completedKplerPeriod(period, frequency=state.frequency)");
  assertIncludes(`${config.key} actual-only chart metric registry`, indexHtml, "function chartMetricActualOnly(metricKey){ return KPLER_CHART_METRICS.has(metricKey) || SECONDARY_UNIT_UTILIZATION_METRICS.has(metricKey); }");
  assertIncludes(`${config.key} secondary unit charts are monthly-only`, indexHtml, "if (chartMetricMonthlyOnly(metricKey) && frequency !== 'monthly') return [];");
  assertIncludes(`${config.key} Kpler charts disable forecast path`, indexHtml, "const nextYearPath = !actualOnly && state.showNextYearForecast && state.showForecast");
  assertIncludes(`${config.key} Kpler legend disables forecast`, indexHtml, "const nextLegend = !actualOnly && state.showNextYearForecast");
  assertIncludes(`${config.key} optional all-zero charts are suppressed`, indexHtml, "if (OPTIONAL_NONZERO_CHART_METRICS.has(metricKey)) return values.some(value => Math.abs(value) > .0001);");
  assertIncludes(`${config.key} PADD3 shipment chart is PADD3-only`, indexHtml, "if (metricKey === 'padd3ShipmentsToPadd1Kbd' && regionKey !== 'padd3') return false;");
  assertIncludes(`${config.key} chart metric availability is region-specific`, indexHtml, "function orderedChartMetrics(regionKey=state.chartRegion){ return CHART_METRICS.filter(metricKey => chartMetricHasVisibleData(regionKey, metricKey, state.frequency)); }");
  assertIncludes(`${config.key} chart shell signature includes metric availability`, indexHtml, "chartMetricsSignature(chartRegions), localDateText()");
  assertIncludes(`${config.key} chart hydration uses derived metric rows`, indexHtml, "const rows = chartRowsForMetric(regionKey, metricKey, state.frequency, baseRows);");
  assertIncludes(`${config.key} chart export uses derived metric rows`, indexHtml, "return chartRowsForMetric(regionKey, metricKey, state.frequency).map(row =>");
  assertIncludes(`${config.key} chart zoom modal container`, indexHtml, "id=\"chartZoomModal\"");
  assertIncludes(`${config.key} chart zoom opens balance modal`, indexHtml, "function openBalanceChartZoom(card, zoomKey)");
  assertIncludes(`${config.key} chart zoom opens crude modal`, indexHtml, "function openCrudeChartZoom(card, metricKey)");
  assertIncludes(`${config.key} chart zoom closes with X`, indexHtml, "data-close-chart-zoom");
  assertIncludes(`${config.key} chart zoom close leaves grid state alone`, indexHtml, "function closeChartZoomModal(){ const modal = chartZoomModal(); if (!modal) return; modal.hidden = true; modal.innerHTML = ''; }");
}

function verifyYieldAdjustmentRowOrder(indexHtml: string, config: ProductConfig): void {
  const yieldRow = "{id:'yieldPct',label:'Yield',kind:'highlight percent'}";
  const adjustmentRow = "{id:'yieldAdjustmentPct',label:'Yield Adjustment',kind:'item muted adjustment percent'}";
  const guideRow = "lines.push(weeklyGuideLine('yieldPct'));";
  const yieldIndex = indexHtml.indexOf(yieldRow);
  const adjustmentIndex = indexHtml.indexOf(adjustmentRow);
  const guideIndex = indexHtml.indexOf(guideRow);
  if (yieldIndex < 0 || adjustmentIndex < 0 || guideIndex < 0) {
    throw new Error(`${config.key} yield adjustment order markers are missing`);
  }
  if (!(yieldIndex < adjustmentIndex && adjustmentIndex < guideIndex)) {
    throw new Error(`${config.key} Yield Adjustment should render between Yield and EIA weekly yield guide`);
  }
}

function verifyYieldWeeklyGuideStopsAtLatestActual(indexHtml: string, config: ProductConfig): void {
  assertIncludes(
    `${config.key} weekly yield guide stops at latest actual week`,
    indexHtml,
    "if (target === 'yieldPct' && series.length && String(period || '') > String(series.at(-1)?.period || '')) return null;",
  );
}

function verifyCrudeRunsDefaultActivation(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} crude default region constant`, indexHtml, "const DEFAULT_CRUDE_REGION_KEY = 'padd1';");
  assertIncludes(`${config.key} crude expanded default storage reset`, indexHtml, "const CRUDE_EXPANDED_DEFAULT_KEY = STORAGE_KEY + ':crude-expanded-default-v2';");
  assertIncludes(`${config.key} crude default expanded group`, indexHtml, "function defaultExpandedCrudeGroupKeys(){ const key = defaultCrudeRegionKey(); return key ? [key] : []; }");
  assertIncludes(`${config.key} crude default active state`, indexHtml, "crudeRegion:defaultCrudeRegionKey()");
  assertIncludes(`${config.key} crude render activates charts`, indexHtml, "function renderCrudeRunsSheet(){ ensureActiveCrudeRegionExpanded(); renderCrudeRunsTable(); renderCrudeCharts(); }");
  assertIncludes(`${config.key} crude charts hydrate immediately`, indexHtml, "hydrateChartBatch(cards, token, valid, hydrate, () => {");
  assertIncludes(`${config.key} crude reset restores PADD 1`, indexHtml, "expandedCrudeGroups = new Set(defaultExpandedCrudeGroupKeys())");
}

function verifyCrudeRunsSectionCleanup(indexHtml: string, config: ProductConfig): void {
  assertNotIncludes(`${config.key} crude runs divider row removed`, indexHtml, "id:'runsSection'");
}

function verifyCrudeRunsRowFormatting(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} crude runs row uses operating capacity band`, indexHtml, "{id:'crudeRunsKbd',label:'Crude Runs',kind:'subtotal'}");
  assertIncludes(`${config.key} crude runs row keeps operating row class`, indexHtml, "['operatingCapacityKbd','crudeRunsKbd'].includes(line.id) ? ' operatingRow' : ''");
  assertIncludes(`${config.key} historical crude outage estimate starts in 2022`, indexHtml, "function useHistoricalCrudeOutageEstimate(period){ return periodMonthValue(period) >= '2022-01'; }");
  assertIncludes(`${config.key} historical unplanned outage formula`, indexHtml, "function historicalUnplannedMaintenanceKbd(operableCapacityKbd, plannedMaintenanceKbd, crudeRunsKbd){ return Math.max(0, Number(operableCapacityKbd || 0) - Number(plannedMaintenanceKbd || 0) - Number(crudeRunsKbd || 0)); }");
  assertIncludes(`${config.key} pre-2022 planned/unplanned outages stay blank`, indexHtml, "plannedMaintenanceKbd:planned === null ? null : round2(planned),unplannedMaintenanceKbd:unplanned === null ? null : round2(unplanned)");
  assertIncludes(`${config.key} balance PADD split preserves pre-2022 outage blanks`, indexHtml, "const scaleNullable = key => crudePoint[key] === null || crudePoint[key] === undefined ? null : scale(key);");
  assertIncludes(`${config.key} balance aggregate preserves all-null outage blanks`, indexHtml, "const nullableSum = key => parts.every(point => point[key] === null || point[key] === undefined) ? null : round2(sum(key));");
  assertIncludes(`${config.key} crude CSV export preserves blanks`, indexHtml, "out[entry.period] = value === null || value === undefined || !Number.isFinite(numeric) ? '' : round2(numeric);");
}

function assignedJson<T>(text: string, marker: string): T {
  const markerIndex = text.indexOf(marker);
  if (markerIndex < 0) throw new Error(`runtime chunk missing marker ${marker}`);
  const start = text.indexOf("{", markerIndex + marker.length);
  if (start < 0) throw new Error(`runtime chunk missing JSON object after ${marker}`);
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let index = start; index < text.length; index += 1) {
    const char = text[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === "\"") inString = false;
      continue;
    }
    if (char === "\"") inString = true;
    else if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) return JSON.parse(text.slice(start, index + 1)) as T;
    }
  }
  throw new Error(`runtime chunk has unterminated JSON object after ${marker}`);
}

async function readAssignedJson<T>(path: string, marker: string): Promise<T> {
  return assignedJson<T>(await readFile(path, "utf8"), marker);
}

async function verifyProduct(config: ProductConfig): Promise<string> {
  const [manifest, monthlyLatest, weeklyLatest, indexHtml, runtimeBase, runtimeWeekly, runtimeCrudeWeekly, runtimeReference] = await Promise.all([
    readJson<BalanceManifest>(config.manifestPath),
    latestCsvDate(config.monthlyCsv),
    latestCsvDate(config.weeklyCsv),
    readFile(config.indexPath, "utf8"),
    readAssignedJson<RuntimeBase>(config.runtimeBasePath, "window.BALANCE_DATA = "),
    readAssignedJson<RuntimeWeekly>(config.runtimeWeeklyPath, ".weekly = "),
    readAssignedJson<RuntimeCrudeWeekly>(config.runtimeCrudeWeeklyPath, ".crudeWeekly = "),
    readAssignedJson<RuntimeReference>(config.runtimeReferencePath, ".reference = "),
  ]);

  assertEqual(`${config.key} manifest monthly freshness`, manifest.latestMonthly, monthlyLatest);
  assertEqual(`${config.key} manifest weekly freshness`, manifest.latestWeekly, weeklyLatest);
  assertEqual(`${config.key} sourceHub monthly latest`, sourceLatest(runtimeReference, "eia_petroleum_monthly"), monthlyLatest);
  assertEqual(`${config.key} sourceHub weekly latest`, sourceLatest(runtimeReference, "eia_petroleum_weekly"), weeklyLatest);
  assertEqual(`${config.key} runtime base generatedAt`, runtimeBase.generatedAt ?? "", manifest.generatedAt);
  assertEqual(`${config.key} runtime base product`, runtimeBase.product?.key ?? "", config.key);
  assertEqual(`${config.key} runtime base monthly freshness`, runtimeBase.freshness?.latestMonthly ?? "", monthlyLatest);
  assertEqual(`${config.key} runtime base weekly freshness`, runtimeBase.freshness?.latestWeekly ?? "", weeklyLatest);
  if ((runtimeBase.optimization?.runtimePlan?.baseRows ?? 0) <= 0) throw new Error(`${config.key} runtime optimization base rows are missing`);
  if ((runtimeBase.optimization?.runtimePlan?.lazyRows ?? 0) <= 0) throw new Error(`${config.key} runtime optimization lazy rows are missing`);
  if ((runtimeBase.optimization?.lazyChunks?.length ?? 0) < 3) throw new Error(`${config.key} runtime optimization lazy chunk diagnostics are incomplete`);
  if ((runtimeBase.optimization?.recommendations?.length ?? 0) === 0) throw new Error(`${config.key} runtime optimization recommendations are missing`);
  if ((runtimeWeekly.regionalBalance?.weekly?.length ?? 0) === 0) throw new Error(`${config.key} runtime weekly regional rows are empty`);
  if ((runtimeCrudeWeekly.crudeRuns?.weekly?.length ?? 0) === 0) throw new Error(`${config.key} runtime weekly crude rows are empty`);
  if ((runtimeReference.sourceFiles?.length ?? 0) === 0) throw new Error(`${config.key} runtime reference source files are empty`);
  const runtimeScriptPattern = new RegExp(`src="data/${config.key}_balance_runtime_base\\.js(?:\\?v=[^"]+)?"`);
  if (!runtimeScriptPattern.test(indexHtml)) {
    throw new Error(`${config.key} index.html does not reference expected runtime base script`);
  }
  verifyUsGrossMovementPresentation(indexHtml, config);
  verifyBalanceSubtotalFormatting(indexHtml, config);
  verifyBalanceSupplySpacing(indexHtml, config);
  verifyBalanceSmartWindowScroll(indexHtml, config);
  verifyBalanceCrudeContextLoading(indexHtml, config);
  verifyChartTabExpansion(indexHtml, config);
  verifyYieldAdjustmentRowOrder(indexHtml, config);
  verifyYieldWeeklyGuideStopsAtLatestActual(indexHtml, config);
  verifyCrudeRunsDefaultActivation(indexHtml, config);
  verifyCrudeRunsSectionCleanup(indexHtml, config);
  verifyCrudeRunsRowFormatting(indexHtml, config);
  verifyUsMovementCoverage(config, runtimeBase);

  for (const file of runtimeReference.sourceFiles ?? []) {
    const actualChecksum = await packagedChecksum(config, file.path);
    assertEqual(`${config.key} checksum ${file.role}`, runtimeReference.checksums?.[file.role] ?? "", actualChecksum);
    if (file.checksum) assertEqual(`${config.key} sourceFiles checksum ${file.role}`, file.checksum, actualChecksum);
  }

  return `${config.key}:weekly=${weeklyLatest}:monthly=${monthlyLatest}`;
}

const results = await Promise.all(PRODUCTS.map((config) => verifyProduct(config)));
console.log(`dashboard freshness ok ${results.join(" ")}`);
