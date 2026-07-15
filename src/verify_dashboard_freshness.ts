import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { sha256 } from "./common.js";
import { weeklyCallArchiveFreshness } from "./weekly_call_archive_freshness.js";

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

type RuntimePowerDfo = {
  powerDfoCharts?: {
    available?: boolean;
    latestWeatherDate?: string;
    daily?: Array<{ date?: string; estimatedDfoConsumptionKbd?: number }>;
    weatherDaily?: Array<{ date?: string; source?: string; sourceLabel?: string }>;
    weatherBaselineNote?: string;
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

type WeeklyCallCatalogEntry = {
  actual_week_ending: string;
  product: ProductKey;
  folder: string;
  weekly_json: string;
  manifest: string;
  table_image: string;
  bar_chart_images: string[];
  generated_at: string;
};

type WeeklyCallCatalog = {
  schema_version: number;
  weeks: WeeklyCallCatalogEntry[];
};

type WeeklyCallManifest = {
  actual_week_ending: string;
  product: ProductKey;
  weekly_json: string;
  images: Array<{ file: string; width_px: number; height_px: number }>;
};

type WeeklyCallInventoryChart = {
  week_ending: string;
  status: "actual" | "forecast";
  labels: string[];
  region_keys: string[];
  values_mb: number[];
};

type WeeklyCallPayload = {
  schema_version: number;
  product?: { key?: string; stats_title?: string };
  inventory_changes?: {
    unit?: string;
    actual?: WeeklyCallInventoryChart;
    forecasts?: WeeklyCallInventoryChart[];
  };
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
  runtimePowerDfoPath: string;
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
    runtimePowerDfoPath: "Diesel_Balance/data/diesel_balance_runtime_power_dfo.js",
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
    runtimePowerDfoPath: "Jet_Balance/data/jet_balance_runtime_power_dfo.js",
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
  assertIncludes(`${config.key} known production offline planned guide row`, indexHtml, "lines.push({id:'knownProductionOfflinePlannedKbd'");
  assertIncludes(`${config.key} known production offline unplanned guide row`, indexHtml, "lines.push({id:'knownProductionOfflineUnplannedKbd'");
  assertIncludes(`${config.key} total known production offline guide row`, indexHtml, "lines.push({id:'knownProductionOfflineTotalKbd'");
  assertIncludes(`${config.key} production row uses yellow highlight override`, indexHtml, ".productionHighlightRow td{background:#fff4a8!important;color:#1f2937!important;");
  assertIncludes(`${config.key} production row applies yellow override class`, indexHtml, "if (line.id === 'production') parts.push('productionHighlightRow');");
  assertIncludes(`${config.key} known production offline red guide style`, indexHtml, ".offlineProductionGuideRow td{background:#fff7ed!important;color:#9a3412!important");
  assertIncludes(`${config.key} known production offline gray total style`, indexHtml, ".offlineProductionTotalGuideRow td{background:#eef1f5!important;color:#475467!important");
  assertIncludes(`${config.key} known production offline row classes`, indexHtml, "if (line.kind.includes('offlineProductionGuide')) parts.push('offlineProductionGuideRow');");
  assertIncludes(`${config.key} build draw rows use readable summary band`, indexHtml, ".balanceSummaryRow td{background:#e8eef6!important");
  assertIncludes(`${config.key} build draw per-day row uses grey band`, indexHtml, ".buildDailyRow td{background:#dde2ea!important");
  assertIncludes(`${config.key} total period build draw row uses dark grey band`, indexHtml, ".buildTotalRow td{background:#6b7280!important;color:#fff!important");
  assertIncludes(`${config.key} total period build draw row keeps readable sign colors`, indexHtml, ".buildTotalRow.drawRow td.positiveValue{color:#bbf7d0!important}");
  assertIncludes(`${config.key} build draw guide uses readable guide band`, indexHtml, ".balanceGuideRow td{background:#f5f8fc!important");
  assertIncludes(`${config.key} build draw cells are sign colored`, indexHtml, ".drawRow td.positiveValue{color:#166534!important}");
  assertIncludes(`${config.key} build draw guide cells are sign colored`, indexHtml, ".balanceGuideRow td.positiveValue{color:#166534!important}");
  assertIncludes(`${config.key} ending stocks row uses grey band`, indexHtml, ".stockRow td{background:#dde2ea!important");
  assertIncludes(`${config.key} cover row uses stock context band`, indexHtml, ".coverRow td{background:#f8fbff!important");
  assertIncludes(`${config.key} build draw summary row class`, indexHtml, "{id:'buildDaily',label:'Build/(draw) per day',kind:'balanceSummary draw'}");
  assertIncludes(`${config.key} build draw per-day row class`, indexHtml, "if (line.id === 'buildDaily') parts.push('buildDailyRow');");
  assertIncludes(`${config.key} total period build draw row class`, indexHtml, "if (line.id === 'buildTotal') parts.push('buildTotalRow');");
  assertIncludes(`${config.key} build draw guide row class`, indexHtml, "kind:lineId === 'buildTotal' ? 'guide balanceGuide' : 'guide'");
  const productionIndex = indexHtml.indexOf("lines.push({id:'production',label:'Production',kind:'subtotal highlight'});");
  const plannedOfflineIndex = indexHtml.indexOf("lines.push({id:'knownProductionOfflinePlannedKbd'");
  const unplannedOfflineIndex = indexHtml.indexOf("lines.push({id:'knownProductionOfflineUnplannedKbd'");
  const totalOfflineIndex = indexHtml.indexOf("lines.push({id:'knownProductionOfflineTotalKbd'");
  const productionGuideIndex = indexHtml.indexOf("if (state.frequency === 'monthly') lines.push(weeklyGuideLine('production'));");
  if ([productionIndex, plannedOfflineIndex, unplannedOfflineIndex, totalOfflineIndex, productionGuideIndex].some((index) => index < 0)) {
    throw new Error(`${config.key} known production offline row order markers are missing`);
  }
  if (!(productionIndex < plannedOfflineIndex && plannedOfflineIndex < unplannedOfflineIndex && unplannedOfflineIndex < totalOfflineIndex && totalOfflineIndex < productionGuideIndex)) {
    throw new Error(`${config.key} known production offline guide rows should render directly below Production`);
  }
}

function verifyBalanceSupplySpacing(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} production/import spacer row`, indexHtml, "const productionImportSpacer = productionLines.length ? [{id:'productionImportSpacer',label:'',kind:'divider supplySpacer'}] : [];");
  assertIncludes(`${config.key} spacer is before weekly imports block`, indexHtml, "...productionLines,...productionImportSpacer,...importBlockLines");
  assertIncludes(`${config.key} weekly imports row precedes override and split Kpler lines`, indexHtml, "const importBlockLines = state.frequency === 'weekly' ? [importsTotalLine,...importLines,...importTotalGuideLines,...importGuideLines] : [...importLines,importsTotalLine,...importTotalGuideLines,...importGuideLines];");
  assertIncludes(`${config.key} weekly imports adjustment uses override label`, indexHtml, "label:'Imports Override',kind:'item muted adjustment importOverride'");
  assertIncludes(`${config.key} adjustment rows render generic adjustment label`, indexHtml, "function balanceLineDisplayLabel(line){ return isBalanceAdjustmentLine(line.id) ? 'Adjustment' : line.label; }");
  assertIncludes(`${config.key} Lower Atlantic monthly imports get override`, indexHtml, "const monthlyLowerAtlanticImportGuide = state.frequency === 'monthly' && D.product?.key === 'diesel' && regionKey === 'padd1c';");
  assertIncludes(`${config.key} PADD 5 imports get monthly and weekly adjustment`, indexHtml, "const padd5ImportAdjustment = regionKey === 'padd5';");
  assertIncludes(`${config.key} PADD 5 import adjustment shares period-scoped import row`, indexHtml, "state.frequency === 'weekly' || monthlyLowerAtlanticImportGuide || padd5ImportAdjustment ? [importsOverrideLine()] : []");
  assertIncludes(`${config.key} Northeast Kpler import total is only grey import guide`, indexHtml, "function isKplerTotalImportGuideLine(lineId){ return isKplerGuideLine(lineId) && kplerGuideTargetLineId(lineId) === 'padd1abImports'; }");
  assertIncludes(`${config.key} Northeast Kpler export total is grey`, indexHtml, "function isKplerTotalExportGuideLine(lineId){ return isKplerGuideLine(lineId) && kplerGuideTargetLineId(lineId) === 'padd1abExportsTotal'; }");
  assertIncludes(`${config.key} Kpler total imports use grey guide class`, indexHtml, "kplerImportTotalGuideRow");
  assertIncludes(`${config.key} Northeast Kpler export total uses grey guide class`, indexHtml, "kplerExportTotalGuideRow");
  assertIncludes(`${config.key} Northeast Kpler export total sums split guide rows`, indexHtml, "if (flow === 'padd1abExportsTotal')");
}

function verifyBalanceSmartWindowScroll(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} balance default scroll helper clears stale viewport restore`, indexHtml, "function requestDefaultBalancePeriodScroll(period=''){ clearPendingTableViewportRestore('balanceTable'); tableScrollSignatures.balanceTable = ''; pendingBalanceScrollPeriod = period || ''; forceBalancePeriodScroll = true; }");
  assertIncludes(`${config.key} balance frequency switch requests default scroll`, indexHtml, "if (state.sheet === 'balance') requestDefaultBalancePeriodScroll();");
  assertIncludes(`${config.key} balance tab switch requests default scroll`, indexHtml, "state.sheet = 'balance'; requestDefaultBalancePeriodScroll(); queueRender();");
  assertIncludes(`${config.key} balance inactive DOM clears stale scroll signature`, indexHtml, "delete balanceTable.dataset.renderSignature;\n        }\n        tableScrollSignatures.balanceTable = '';");
  assertIncludes(`${config.key} balance force scroll bypasses viewport restore`, indexHtml, "else if (forceScroll) { clearPendingTableViewportRestore('balanceTable'); scrollTableToPeriod('balanceTable', targetPeriod, signature, true); }");
  assertIncludes(`${config.key} balance table scroll gets delayed layout retries`, indexHtml, "const retryDelays = wrap.id === 'crudeRunsTableWrap' ? [120,360] : [40,120,360];");
  assertIncludes(`${config.key} mobile crude table stays inside its scroll container`, indexHtml, "@media(max-width:760px){#crudeRunsTableWrap{display:block;min-width:0;width:100%;max-width:100%;max-height:58vh;overflow:auto}");
  assertIncludes(`${config.key} mobile crude period count wraps inside the viewport`, indexHtml, "#crudeRunsCount{white-space:normal;max-width:100%;line-height:1.35}");
  assertIncludes(`${config.key} mobile workbook disables desktop compositor transforms`, indexHtml, ".topbar,.crudeViewportLock,.chartGrid{will-change:auto;transform:none!important}");
  assertIncludes(`${config.key} desktop crude table stays inside its bordered scroll container`, indexHtml, "#crudeRunsTableWrap{display:block;min-width:0;width:100%;max-width:100%;max-height:72vh;overflow:auto;vertical-align:top}");
  assertIncludes(`${config.key} crude table disables page-wide horizontal scrolling`, indexHtml, "function tableUsesPageWideScroll(){ return false; }");
  assertIncludes(`${config.key} crude sticky header excludes external controls inside its scroll container`, indexHtml, "const controlOffset = tableUsesPageWideScroll(wrap) && controlsSticky ? Math.ceil(controls.getBoundingClientRect().height) : 0;");
  assertIncludes(`${config.key} crude inner scroll suppresses the legacy cloned region header`, indexHtml, "if (state.sheet !== 'crude' || !wrap || !tableUsesPageWideScroll(wrap)) return hideCrudeActiveHeader();");
  assertIncludes(`${config.key} mobile workbook disables page-wide viewport tracking`, indexHtml, "function viewportTrackingActive(){ return (state.sheet === 'charts' || state.sheet === 'crude') && !matchMedia('(max-width: 760px)').matches; }");
  assertIncludes(`${config.key} mobile crude table limits its rasterized period window`, indexHtml, "function crudeTableDisplayPeriods(allPeriods=crudeDisplayPeriods())");
  assertIncludes(`${config.key} crude table distinguishes mobile and desktop windows`, indexHtml, "const actualLookback = mobile ? 12 : 104;");
  assertIncludes(`${config.key} desktop weekly crude window keeps all periods inside the selected display cap`, indexHtml, "return mobile ? allPeriods.slice(start, Math.min(allPeriods.length, start + 64)) : allPeriods.slice(start);");
  assertIncludes(`${config.key} weekly display window defaults to 18 forecast weeks`, indexHtml, "const DEFAULT_WEEKLY_FORECAST_WEEKS = 18;");
  assertIncludes(`${config.key} weekly forecast count is clamped`, indexHtml, "Math.max(0, Math.min(MAX_WEEKLY_FORECAST_WEEKS, parsed))");
  assertIncludes(`${config.key} weekly crude display ends at the shared forecast display end`, indexHtml, "function crudeDisplayPeriods(frequency=state.frequency){ const key = calcCacheKey('crudeDisplayPeriods', frequency, forecastDisplayEnd(frequency));");
  assertIncludes(`${config.key} crude CSV export keeps the full modeled horizon`, indexHtml, "function currentCrudeRowsForExport(){ const periods = crudeAllPeriods();");
  assertIncludes(`${config.key} weekly display input explains exports remain full`, indexHtml, "Display only; the full forecast remains available for exports.");
  assertIncludes(`${config.key} mobile crude window tells users exports keep full history`, indexHtml, "period columns; exports keep full history");
  assertIncludes(`${config.key} crude table retains its visible enclosure`, indexHtml, "border:2px solid #5f6d80;border-radius:9px;box-shadow:inset 0 0 0 1px #dce3ec,0 8px 20px rgba(15,23,42,.12)");
}

function verifyBalanceCrudeContextLoading(indexHtml: string, config: ProductConfig): void {
  assertNotIncludes(`${config.key} row focus header panel removed`, indexHtml, "<div class=\"caption\">Row focus</div>");
  assertNotIncludes(`${config.key} table layout header panel removed`, indexHtml, "<div class=\"caption\">Table layout</div>");
  assertNotIncludes(`${config.key} experimental reconcile header panel removed`, indexHtml, "<span class=\"caption\">Experimental reconcile</span>");
  assertIncludes(`${config.key} row focus state is forced off`, indexHtml, "state.balanceFocus = 'all'; state.balanceSearch = '';");
  assertIncludes(`${config.key} table layout state uses production defaults`, indexHtml, "state.labelWidth = TABLE_LAYOUT_DEFAULTS.labelWidth; state.labelSize = TABLE_LAYOUT_DEFAULTS.labelSize;");
  assertIncludes(`${config.key} balance sheets declare shared crude context`, indexHtml, "const needsBalanceContext = sheet === 'balance' || sheet === 'charts';");
  assertIncludes(`${config.key} weekly balance and charts load balance plus crude context`, indexHtml, "if (frequency === 'weekly' && needsBalanceContext) await Promise.all([ensureWeeklyData(), ensureCrudeWeeklyData()]);");
  assertIncludes(`${config.key} weekly outages load weekly balance scaffold`, indexHtml, "if (frequency === 'weekly' && sheet === 'outages') await ensureWeeklyData();");
  assertIncludes(`${config.key} outages tab uses shared data loader`, indexHtml, "outagesSheetBtn').addEventListener('click', async () => { const changed = state.sheet !== 'outages'; try { await ensureDataForState({...state,sheet:'outages'}); }");
  assertIncludes(`${config.key} crude outage launcher uses shared data loader`, indexHtml, "openOutagesFromCrudeBtn').addEventListener('click', async () => { const nextRegion = validBaseCrudeRegion(state.crudeRegion) ? state.crudeRegion : 'padd1'; try { await ensureDataForState({...state,sheet:'outages',crudeRegion:nextRegion}); }");
  assertIncludes(`${config.key} weekly crude charts load product balance and crude contexts`, indexHtml, "if (frequency === 'weekly' && sheet === 'crude') await Promise.all([ensureWeeklyData(), ensureCrudeWeeklyData()]);");
  assertIncludes(`${config.key} balance loads reference context before rendering crude-derived rows`, indexHtml, "if (needsBalanceContext || sheet === 'reference' || sheet === 'outages' || sheet === 'crude') await ensureReferenceData();");
  assertIncludes(`${config.key} frequency switches use shared data loader`, indexHtml, "try { await ensureDataForState({...state,frequency:nextFrequency}); }");
  assertIncludes(`${config.key} refresh button starts the forced full upstream data pull`, indexHtml, "document.getElementById('refreshBtn').addEventListener('click', () => { startDashboardUpdate('all'); });");
  assertIncludes(`${config.key} refresh controls show an immediate durable starting state`, indexHtml, "Connecting to the local runner and starting the forced '+updateGroupMeta(group).label+' data pull");
  assertIncludes(`${config.key} refresh control failures stay visible in the status panel`, indexHtml, "lastUpdateJob = {...startingJob,status:'failed'");
  assertIncludes(`${config.key} changed-data update status is explicit`, indexHtml, "Updated — new data loaded");
  assertIncludes(`${config.key} unchanged-data refresh status is explicit`, indexHtml, "Refreshed — data unchanged");
  const productLabel = config.key === "jet" ? "Jet" : "Diesel";
  assertIncludes(`${config.key} Reference has product-specific weekly image save button`, indexHtml, `Save ${productLabel} weekly table and bar charts`);
  assertIncludes(`${config.key} weekly call output request sends active workbook product`, indexHtml, "product:D.product?.key");
  assertIncludes(`${config.key} weekly image save status is product-specific`, indexHtml, "Saved — '+productLabel+' weekly table and bar charts ready");
  assertIncludes(`${config.key} weekly call output path is explicit`, indexHtml, "weekly_call_outputs/outputs");
  assertIncludes(`${config.key} weekly call output steps include all bar charts`, indexHtml, "Render latest EIA Actuals and first two Forecast bar charts");
  assertIncludes(`${config.key} weekly image save does not trigger dashboard reload`, indexHtml, "if (lastUpdateJob.result === 'saved') { showToast(workbookProductLabel(lastUpdateJob.product)+' weekly table and bar charts saved in weekly_call_outputs/outputs');");
  assertIncludes(`${config.key} changed-data update log is explicit`, indexHtml, "UPDATED — NEW DATA");
  assertIncludes(`${config.key} unchanged-data refresh log is explicit`, indexHtml, "REFRESHED — DATA UNCHANGED");
  assertIncludes(`${config.key} partial update status is explicit`, indexHtml, "Updated with warnings");
  assertIncludes(`${config.key} partial update log is explicit`, indexHtml, "REFRESH COMPLETE WITH WARNINGS");
  assertIncludes(`${config.key} changed-data update reload toast is explicit`, indexHtml, "New source data loaded; reloading dashboard");
  assertIncludes(`${config.key} failed update does not imply fresh data`, indexHtml, "Refresh failed; dashboard data was not reloaded");
  assertIncludes(`${config.key} update completion is shared across workbook tabs`, indexHtml, "const UPDATE_COMPLETION_STORAGE_KEY = 'us-balances:update-complete';");
  assertIncludes(`${config.key} reload loops are blocked per browser tab`, indexHtml, "const UPDATE_RELOAD_SESSION_KEY = 'us-balances:update-reloaded';");
  assertIncludes(`${config.key} button-started updates are observed across tabs`, indexHtml, "observedRunningUpdateJobId = lastUpdateJob.id");
  assertIncludes(`${config.key} landing-page updates reload open workbook tabs`, indexHtml, "Refresh completed; loading the latest dashboard data");
  assertIncludes(`${config.key} every workbook tab polls for button refresh completion`, indexHtml, "      pollUpdateStatus();");
  assertIncludes(`${config.key} idle refresh message is button-only`, indexHtml, "No refresh is running. Choose a refresh button above to begin; each data refresh rebuilds and verifies both dashboards.");
  assertIncludes(`${config.key} refresh readiness blocks early clicks`, indexHtml, "if (!refreshToolsReady) { showToast('Refresh tools are still being prepared. Try the button again when Ready.'); return; }");
  assertNotIncludes(`${config.key} old launcher auto-refresh message removed`, indexHtml, "A normal launcher click starts a forced Complete refresh");
  assertIncludes(`${config.key} F9 is routed through safe dashboard refresh`, indexHtml, "const isF9 = e.key === 'F9' || e.keyCode === 120;");
  assertIncludes(`${config.key} F9 recalculation loads dependencies first`, indexHtml, "refreshDashboardData('Dashboard recalculated');");
  assertIncludes(`${config.key} balance bootstrap refreshes server settings after data load`, indexHtml, "else if (state.sheet === 'balance' || state.sheet === 'charts' || state.sheet === 'outages' || state.sheet === 'crude') { refreshWorkbookSettings(); }");
  assertIncludes(`${config.key} shared settings save sends base revision`, indexHtml, "baseRevision:workbookSettings.revision || ''");
  assertIncludes(`${config.key} embedded rebuild horizon outranks stale browser storage`, indexHtml, "forecastEnd:normalizeForecastEnd(embedded.forecastEnd || stored.forecastEnd)");
  assertIncludes(`${config.key} forecast save waits for verified rebuild`, indexHtml, "if (!payload.rebuilt) throw new Error('Forecast end was saved without a verified dashboard rebuild.')");
  assertIncludes(`${config.key} forecast save reloads verified packages`, indexHtml, "Forecast end rebuilt through '+nextForecastEnd+'; loading verified dashboards");
  assertIncludes(`${config.key} server adjustment maps preserve the active product`, indexHtml, "Array.isArray(nextSettings.adjustments?.[D.product.key]) ? nextSettings.adjustments[D.product.key]");
  assertIncludes(`${config.key} refresh controls lock during forecast rebuilds`, indexHtml, "if (settingsRebuildRunning) { showToast('Forecast settings are rebuilding. Wait until that verified rebuild finishes.'); return; }");
  assertIncludes(`${config.key} forecast rows are horizon filtered`, indexHtml, "function rowWithinForecastEnd(row, frequency=state.frequency)");
  assertIncludes(`${config.key} year toggle uses the visible forecast window`, indexHtml, "const rows = forecastDisplayRows(rawRowsForFrequency(frequency), frequency);");
  assertNotIncludes(`${config.key} old separate refresh instruction removed`, indexHtml, "Forecast end saved; run a refresh to rebuild through");
  assertIncludes(`${config.key} shared settings conflict is explicit`, indexHtml, "Shared settings changed; latest file loaded. Re-enter the edit and save again.");
  assertIncludes(`${config.key} shared settings offline message is explicit`, indexHtml, "saved in this browser only; shared settings server offline");
}

function verifyChartTabExpansion(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} charts topbar switches in-place`, indexHtml, "<a class=\"btn\" id=\"chartsSheetBtn\" href=\"?sheet=charts\">Charts</a>");
  assertIncludes(`${config.key} charts topbar has in-place click handler`, indexHtml, "document.getElementById('chartsSheetBtn').addEventListener('click', async e => { e.preventDefault();");
  assertIncludes(`${config.key} chart history minimum`, indexHtml, "const MIN_CHART_HISTORY_YEAR = 2017;");
  assertIncludes(`${config.key} chart band years exclude pre-2017`, indexHtml, "context.years.filter(year => year >= MIN_CHART_HISTORY_YEAR && year < context.currentYear)");
  assertIncludes(`${config.key} chart row filter excludes pre-2017`, indexHtml, "chartRowPeriodYear(row) >= MIN_CHART_HISTORY_YEAR");
  assertIncludes(`${config.key} requested derived chart metrics`, indexHtml, "'periodBuildDrawKb','netLengthKbd'");
  assertIncludes(`${config.key} Yield metric is registered as percent`, indexHtml, "{key:'yieldPct',label:'Yield',unit:'%',digits:1}");
  assertIncludes(`${config.key} Yield appears in normal chart metrics`, indexHtml, "'demandKbd','productionKbd','yieldPct'");
  assertIncludes(`${config.key} Yield appears in crude chart metrics`, indexHtml, "...CRUDE_BASE_METRICS,{key:'yieldPct',label:'Yield',unit:'%',digits:1}");
  assertIncludes(`${config.key} crude yield joins product balance rows`, indexHtml, "function crudeChartRowsForRegion(regionKey=state.crudeRegion, frequency=state.frequency)");
  assertIncludes(`${config.key} split PADD 1 Yield combines P1 A/B and P1 C production`, indexHtml, "['padd1ab','padd1c'].forEach(memberKey");
  assertIncludes(`${config.key} requested receipts chart metric`, indexHtml, "'receiptsKbd'");
  assertIncludes(`${config.key} requested PADD3 shipment chart metric`, indexHtml, "'padd3ShipmentsToPadd1Kbd'");
  assertIncludes(`${config.key} Kpler chart metrics registered`, indexHtml, "const KPLER_CHART_METRICS = new Set(['kplerImportsKbd'");
  assertIncludes(`${config.key} secondary unit utilization chart metrics registered`, indexHtml, "const SECONDARY_UNIT_UTILIZATION_METRICS = new Set(['catalyticCrackingUtilizationPct','cokingUtilizationPct','hydrocrackingUtilizationPct']);");
  assertIncludes(`${config.key} secondary unit chart labels`, indexHtml, "label:'Catalytic Cracking Utilization'");
  assertIncludes(`${config.key} coking utilization chart label`, indexHtml, "label:'Coking Utilization'");
  assertIncludes(`${config.key} hydrocracking utilization chart label`, indexHtml, "label:'Hydrocracking Utilization'");
  assertIncludes(`${config.key} chart missing values are not coerced to zero`, indexHtml, "function finiteNumberOrNull(value){ if (value === null || value === undefined || value === '') return null; const n = Number(value); return Number.isFinite(n) ? n : null; }");
  assertIncludes(`${config.key} all percent charts use tight percent scale`, indexHtml, "chartScale(raw, 5, {percent:percentMetric,tight:percentMetric,nonNegative:isOutageSeasonChart})");
  assertIncludes(`${config.key} percent scale preserves real negative observations`, indexHtml, "const hasNegativePercent = Boolean(options.percent && valid.some(value => value < 0));");
  assertIncludes(`${config.key} percent chart axis labels include percent sign`, indexHtml, "const axisValueLabel = value => metric.unit === '%' ? fmt(value, metric.digits) + '%' : fmt(value, outageAxisDigits);");
  assertIncludes(`${config.key} Kpler periods are completed only`, indexHtml, "function completedKplerPeriod(period, frequency=state.frequency)");
  assertIncludes(`${config.key} actual-only chart metric registry excludes forecast-capable outages`, indexHtml, "function chartMetricActualOnly(metricKey){ return KPLER_CHART_METRICS.has(metricKey) || SECONDARY_UNIT_UTILIZATION_METRICS.has(metricKey); }");
  assertIncludes(`${config.key} secondary unit charts are monthly-only`, indexHtml, "if (chartMetricMonthlyOnly(metricKey) && frequency !== 'monthly') return [];");
  assertIncludes(`${config.key} Kpler charts disable forecast path`, indexHtml, "const nextYearPath = !actualOnly && state.showNextYearForecast && state.showForecast");
  assertIncludes(`${config.key} Kpler legend disables forecast`, indexHtml, "if (!actualOnly && state.showNextYearForecast && nextYearForecast && state.showForecast && available.has(nextYearForecast))");
  assertIncludes(`${config.key} chart legends filter unavailable years per card`, indexHtml, "function chartAvailableYearSet(bundle)");
  assertIncludes(`${config.key} chart legend entries use newest-first year order`, indexHtml, "return entries.sort((a,b)=>b.year-a.year || a.order-b.order);");
  assertIncludes(`${config.key} chart history chips use newest-first order`, indexHtml, "chips.sort((a,b)=>b.year-a.year || a.order-b.order).map(chip => chip.html).join('')");
  assertIncludes(`${config.key} chart hydration preserves legend host`, indexHtml, "if (legendHost) legendHost.innerHTML = legendHtml; else { const legacyLegend = card.querySelector('.legend'); if (legacyLegend) legacyLegend.outerHTML = legendHtml; }");
  assertIncludes(`${config.key} optional all-zero charts are suppressed`, indexHtml, "if (OPTIONAL_NONZERO_CHART_METRICS.has(metricKey)) return values.some(value => Math.abs(value) > .0001);");
  assertIncludes(`${config.key} PADD3 shipment chart is PADD3-only`, indexHtml, "if (metricKey === 'padd3ShipmentsToPadd1Kbd' && regionKey !== 'padd3') return false;");
  assertIncludes(`${config.key} chart metric availability is region-specific`, indexHtml, "function orderedChartMetrics(regionKey=state.chartRegion){ return CHART_METRICS.filter(metricKey => chartMetricHasVisibleData(regionKey, metricKey, state.frequency)); }");
  assertIncludes(`${config.key} chart shell signature includes metric and power availability`, indexHtml, "chartMetricsSignature(chartRegions), powerDfoChartsSignature(), localDateText()");
  assertIncludes(`${config.key} chart hydration signature includes active scenario preview`, indexHtml, "chartScenarioOverlaySignature(), chartScenarioCalculationSignature(), chartMetricsSignature(chartRegions)");
  assertIncludes(`${config.key} chart hydration uses derived metric rows`, indexHtml, "const rows = chartRowsForMetric(regionKey, metricKey, state.frequency, baseRows);");
  assertIncludes(`${config.key} chart export uses derived metric rows`, indexHtml, "return chartRowsForMetric(regionKey, metricKey, state.frequency).map(row =>");
  assertIncludes(`${config.key} chart zoom modal container`, indexHtml, "id=\"chartZoomModal\"");
  assertIncludes(`${config.key} chart zoom opens balance modal`, indexHtml, "function openBalanceChartZoom(card, zoomKey)");
  assertIncludes(`${config.key} chart zoom opens crude modal`, indexHtml, "function openCrudeChartZoom(card, metricKey)");
  assertIncludes(`${config.key} chart zoom closes with X`, indexHtml, "data-close-chart-zoom");
  assertIncludes(`${config.key} chart zoom close leaves grid state alone`, indexHtml, "function closeChartZoomModal(){ const modal = chartZoomModal(); if (!modal) return; modal.hidden = true; modal.innerHTML = ''; }");
  assertIncludes(`${config.key} chart zoom custom title control`, indexHtml, "data-zoom-title");
  assertIncludes(`${config.key} chart zoom preset size control`, indexHtml, "data-zoom-size-preset");
  assertIncludes(`${config.key} chart zoom custom width control`, indexHtml, "data-zoom-width");
  assertIncludes(`${config.key} chart zoom custom height control`, indexHtml, "data-zoom-height");
  assertIncludes(`${config.key} chart zoom custom PNG save`, indexHtml, "function saveZoomChartPng(card)");
}

function verifyChartScenarioPropagation(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} scenario From month is editable`, indexHtml, 'id="chartScenarioStart" type="month"');
  assertIncludes(`${config.key} scenario From month keeps forecast lower bound`, indexHtml, 'id="chartScenarioStart" type="month" min="');
  assertIncludes(`${config.key} scenario From month calendar control`, indexHtml, 'id="chartScenarioStartPickerBtn"');
  assertIncludes(`${config.key} scenario From month updates the draft`, indexHtml, "if (target?.id === 'chartScenarioStart')");
  assertIncludes(`${config.key} scenario From month preserves range ordering`, indexHtml, "endPeriod:draft.endPeriod < startPeriod ? startPeriod : draft.endPeriod");
  assertIncludes(`${config.key} reopening a scenario preserves its active preview`, indexHtml, "activePreview?.previewEnabled && activePreview.regionKey === regionKey && activePreview.metricKey === metricKey");
  assertIncludes(`${config.key} switching scenarios repaints after clearing an active preview`, indexHtml, "if (hadActivePreview) queueRender();");
  assertIncludes(`${config.key} bundled scenarios check every affected region`, indexHtml, "function chartScenarioAffectsChartRegion(scenario, regionKey){ return chartScenarioAdjustmentScenarios(scenario).some(adjustment => scenarioAffectsChartRegion(adjustment, regionKey)); }");
  assertIncludes(`${config.key} enabled scenarios are simulated per chart`, indexHtml, "const scenarioBundle = withChartScenarioSimulation([scenario], () => chartSeriesBundle(chartRowsForMetric(regionKey, metricKey, frequency), metricKey, frequency");
  assertIncludes(`${config.key} dependent chart overlays use recalculated differences`, indexHtml, "const series = overlays.filter(scenario => chartScenarioAffectsChartRegion(scenario, regionKey)).map((scenario, index) =>");
  assertIncludes(`${config.key} scenario simulation filters unchanged charts`, indexHtml, "if (!chartScenarioBundleHasVisibleDiff(baseBundle, scenarioBundle, visibleForecastYears)) return null;");
  assertIncludes(`${config.key} demand feeds balance`, indexHtml, "productionKbd + importsKbd + netReceiptsKbd - exportsKbd - demandKbd");
  assertIncludes(`${config.key} balance feeds forecast inventory`, indexHtml, "priorPoint?.stocksKb || rawPoint.stocksKb || 0) + balanceKbd * periodDays(rawPoint.period)");
  assertIncludes(`${config.key} demand and inventory feed forward cover`, indexHtml, "Number(list[index].stocksKb || 0) / avgDemand");
  assertIncludes(`${config.key} demand feeds net length`, indexHtml, "Number(point.productionKbd || 0) - Number(point.demandKbd || 0)");
  assertIncludes(`${config.key} demand feeds total period build draw`, indexHtml, "Number(point.demandKbd || 0) - Number(point.exportsKbd || 0) - shipments");
}

function verifyOutageProductionOffline(indexHtml: string, config: ProductConfig): void {
  assertIncludes(`${config.key} outage chart metric registry`, indexHtml, "const OUTAGE_CHART_METRICS = new Set(['knownProductionOfflinePlannedKbd'");
  assertIncludes(`${config.key} Yield and outage product metrics follow production`, indexHtml, "'productionKbd','yieldPct','knownProductionOfflinePlannedKbd','knownProductionOfflineUnplannedKbd','knownProductionOfflineTotalKbd'");
  assertIncludes(`${config.key} crude runs outage unit is atmospheric distillation only`, indexHtml, "const CRUDE_RUN_OUTAGE_UNIT_KEY = 'atmos_distillation';");
  assertIncludes(`${config.key} crude runs reads only atmospheric distillation outage totals`, indexHtml, "addOutageTotals(totals, byRegion[key]?.units?.[CRUDE_RUN_OUTAGE_UNIT_KEY])");
  assertNotIncludes(`${config.key} crude runs does not read broad all-unit outage totals`, indexHtml, "outageSourceKeys(regionKey).forEach(key => addOutageTotals(totals, byRegion[key]));");
  assertIncludes(`${config.key} concurrent different-unit outages are documented`, indexHtml, "different units may be offline at the same time");
  assertIncludes(`${config.key} outage collisions are scoped to canonical unit`, indexHtml, "outageUnitCollisionKey(outage) === entryUnitKey && outageRangesOverlap");
  assertIncludes(`${config.key} overlapping capacity validation is scoped to canonical unit`, indexHtml, "outageUnitCollisionKey(outage) === entryUnitKey).map(outage");
  assertIncludes(`${config.key} new outages receive generated unique ids`, indexHtml, "const id = sourceId && sourceId !== 'draft-outage' ? sourceId : 'outage-' + Date.now()");
  assertIncludes(`${config.key} outage drafts do not persist a shared placeholder id`, indexHtml, "return normalizeOutage({id:outageEditId || '',regionKey:");
  assertIncludes(`${config.key} legacy placeholder ids are migrated before shared merge`, indexHtml, "const key = sourceId && sourceId !== 'draft-outage' ? sourceId : JSON.stringify(row);");
  assertIncludes(`${config.key} assumption ledger distinguishes crude-run outages`, indexHtml, "unitKey === CRUDE_RUN_OUTAGE_UNIT_KEY ? 'crude-run capacity input' : 'unit outage only'");
  assertIncludes(`${config.key} diesel PADD 1 outage yield vector`, indexHtml, "padd1:{atmos_distillation:.22,fcc:.18,coking:.28,distillate_hydrocracking:.20,gasoil_resid_hydrocracking:.35}");
  assertIncludes(`${config.key} diesel PADD 5 outage yield vector`, indexHtml, "padd5:{atmos_distillation:.10,fcc:.14,coking:.20,distillate_hydrocracking:.15,gasoil_resid_hydrocracking:.29}");
  assertIncludes(`${config.key} jet PADD 3 hydrocracking outage yield vector`, indexHtml, "padd3:{atmos_distillation:.10,distillate_hydrocracking:.22,gasoil_resid_hydrocracking:.22}");
  assertIncludes(`${config.key} product outage yield selector`, indexHtml, "function productOutageYields(){ return D.product?.key === 'jet' ? JET_OUTAGE_YIELDS : DIESEL_OUTAGE_YIELDS; }");
  assertIncludes(`${config.key} outage unit canonicalizer`, indexHtml, "function canonicalOutageUnitKey(unitKey='', unitLabel='')");
  assertIncludes(`${config.key} manual outages drive product offline totals`, indexHtml, "outageEntries.forEach(outage =>");
  assertIncludes(`${config.key} product offline excludes other outages from known total`, indexHtml, "if (bucket !== 'other') target.totalKnown += value;");
  assertIncludes(`${config.key} outage product rows use yielded totals`, indexHtml, "if (spec.kind === 'product') addOutageTotals(totals, daily.productOffline);");
  assertIncludes(`${config.key} outage capacity rows use unit capacity totals`, indexHtml, "else (OUTAGE_UNIT_GROUPS[spec.unitGroup] || []).forEach(unitKey => addOutageTotals(totals, daily.units?.[unitKey]));");
  assertIncludes(`${config.key} weekly outage charts use Friday-ending 7-day window`, indexHtml, "return {start:end - 6 * DAY_MS,end,days:7};");
  assertIncludes(`${config.key} known production offline balance values`, indexHtml, "else if (OUTAGE_CHART_METRICS.has(lineId)) value = outageMetricValue({...point,regionKey}, lineId, state.frequency);");
  assertIncludes(`${config.key} outage balance values retain visible decimal precision`, indexHtml, "target === 'daysForwardCover' || OUTAGE_CHART_METRICS.has(target) ? 1 : 0");
  assertIncludes(`${config.key} outage charts render all outage metrics`, indexHtml, "function orderedOutageChartMetrics(){ return Array.from(OUTAGE_CHART_METRICS); }");
  assertIncludes(`${config.key} outage charts use crude outage regions`, indexHtml, "function renderOutageChartRegionOptions()");
  assertIncludes(`${config.key} outage charts preserve actual history while clipping forecast rows`, indexHtml, "function outageChartSourceRows(frequency=state.frequency){ return rawRowsForFrequency(frequency).filter(row => row?.period && rowWithinForecastEnd(row, frequency)); }");
  assertIncludes(`${config.key} outage charts preserve forecast status for next-year periods`, indexHtml, "index.set(row.period, row.status === 'forecast' ? 'forecast' : 'actual');");
  assertIncludes(`${config.key} outage charts use custom rows`, indexHtml, "function outageChartRowsForMetric(regionKey, metricKey, frequency=state.frequency)");
  assertIncludes(`${config.key} outage charts use selected band years with default fallback`, indexHtml, "function outageBandYears(frequency=state?.frequency || 'monthly'){ const selected = normalizeBandYears(state?.bandYears, frequency, false); return selected.length ? selected : defaultOutageBandYears(frequency); }");
  assertIncludes(`${config.key} outage charts expose shared chart options`, indexHtml, "document.getElementById('chartOptions').hidden = !(state.sheet === 'charts' || state.sheet === 'outages');");
  assertIncludes(`${config.key} outage charts expose forecast control`, indexHtml, "document.getElementById('showForecastChip').hidden = false;");
  assertIncludes(`${config.key} outage charts hide disabled smoothing control`, indexHtml, "document.getElementById('fourWeekAverageChip').hidden = state.sheet === 'outages';");
  assertIncludes(`${config.key} outage chart legends filter unavailable years per card`, indexHtml, "const lineLegend = chartLineLegendEntries(bundle, metricKey, state.frequency).map(entry =>");
  assertIncludes(`${config.key} outage chart cache scope tracks outage settings`, indexHtml, "function outageChartCacheScope(regionKey, metricKey, rows)");
  assertIncludes(`${config.key} outage chart suppresses white current-year markers`, indexHtml, "const actualMarkers = isOutageSeasonChart ? '' : currentActual.map");
  assertIncludes(`${config.key} zero-only outage charts use a clean nonnegative scale`, indexHtml, "const outageZeroScale = isOutageSeasonChart && chartVisiblePointCount(seriesBundle) > 0 && !seriesBundle.values.some((value, index) => seriesBundle.valid[index] && Math.abs(value) >= .0001);");
  assertIncludes(`${config.key} zero-only outage charts do not render negative zero ticks`, indexHtml, "outageZeroScale ? {min:0,max:1,ticks:[0,1],step:1}");
  assertIncludes(`${config.key} nonzero outage charts keep their axis nonnegative`, indexHtml, "if (options.nonNegative) min = Math.max(0, min);");
  assertIncludes(`${config.key} small outage values keep readable decimal ticks`, indexHtml, "const outageAxisDigits = isOutageSeasonChart && scale.step < 1 ? Math.max(metric.digits, 1) : 0;");
  assertIncludes(`${config.key} outage history chips expose next-year forecast toggle`, indexHtml, "if (nextYearForecast) chips.push");
  assertIncludes(`${config.key} outage next-year forecast toggle updates chart state`, indexHtml, "else if (key === 'next') state.showNextYearForecast = lineInput.checked;");
  assertIncludes(`${config.key} outage chart render signature tracks forecast visibility`, indexHtml, "state.showForecast ? 'forecast' : 'actual-only'");
  assertIncludes(`${config.key} outage chart render signature tracks next-year visibility`, indexHtml, "state.showNextYearForecast ? 'next' : 'no-next'");
  assertIncludes(`${config.key} outage chart SVG class`, indexHtml, "outageSeasonChart");
  assertIncludes(`${config.key} outage chart skips 4-week smoothing`, indexHtml, "noRolling:isOutageSeasonChart");
  assertIncludes(`${config.key} outage chart export control`, indexHtml, "data-outage-export-chart");
  assertIncludes(`${config.key} outage chart grid click handler`, indexHtml, "document.getElementById('outageChartGrid').addEventListener('click'");
  assertIncludes(`${config.key} outage chart region change handler`, indexHtml, "document.getElementById('outageChartRegion').addEventListener('change'");
  assertIncludes(`${config.key} outage start-date edits preserve manual offline capacity`, indexHtml, "outageStart').addEventListener('change', () => updateOutageCapacityDefault(false));");
  assertIncludes(`${config.key} outage type edits preserve manual offline capacity`, indexHtml, "if (e.target.value === 'Unplanned') applyUnplannedOutageDefault(); updateOutageCapacityDefault(false);");
  assertIncludes(`${config.key} unplanned defaults only fill missing dates`, indexHtml, "if (start && !start.value) start.value = localDateText(); if (end && !end.value) end.value = addLocalDays(start?.value || localDateText(), 7);");
  assertIncludes(`${config.key} adding an outage immediately queues a dashboard render`, indexHtml, "saveOutagesLocal(); clearOutageForm(); tableScrollSignatures = {}; queueRender();");
}

function verifyNortheastPowerCharts(indexHtml: string, config: ProductConfig, runtimePowerDfo: RuntimePowerDfo): void {
  assertIncludes(`${config.key} power DFO lazy chunk loader`, indexHtml, "async function ensurePowerDfoData(){ if (hasPowerDfoData()) return; await ensureLazyChunk('powerDfo'); }");
  assertIncludes(`${config.key} power DFO Northeast-only gate`, indexHtml, "function shouldShowNortheastPowerSection(){ return D.product?.key === 'diesel' && state.chartRegion === 'padd1ab'; }");
  assertIncludes(`${config.key} power DFO section renderer`, indexHtml, "function northeastPowerSectionHtml()");
  assertIncludes(`${config.key} distillate burn kb/d bar renderer`, indexHtml, "function drawDistillateBurnBarChart(svg, rows, options={})");
  assertIncludes(`${config.key} distillate burn calendar renderer`, indexHtml, "function drawDistillateBurnCalendar(container, rows)");
  assertIncludes(`${config.key} PADD 1 HDD renderer`, indexHtml, "function drawPowerDfoHddChart(svg, rows)");
  assertIncludes(`${config.key} distillate burn zoom control`, indexHtml, "data-power-zoom=\"burn\"");
  assertIncludes(`${config.key} distillate burn chart uses kb/d`, indexHtml, "valueKey:'estimatedDfoConsumptionKbd',unit:'kb/d'");
  assertIncludes(`${config.key} weather chart uses 14-day horizon`, indexHtml, "powerDfoWeatherWindowRows(14)");
  assertIncludes(`${config.key} weather source legend renderer`, indexHtml, "function hddLegendHtml(rows)");
  assertIncludes(`${config.key} burn percentile calendar threshold`, indexHtml, "if (p <= 80) return {background:'#fff'");
  if (config.key === "diesel") {
    if (runtimePowerDfo.powerDfoCharts?.available !== true) throw new Error("diesel power DFO chart payload is unavailable");
    const daily = runtimePowerDfo.powerDfoCharts?.daily ?? [];
    const weatherDaily = runtimePowerDfo.powerDfoCharts?.weatherDaily ?? [];
    if (daily.length === 0) throw new Error("diesel power DFO daily rows are empty");
    if (weatherDaily.length === 0) throw new Error("diesel power DFO weather rows are empty");
    if ((daily[0]?.date || "9999-99-99") > "2023-01-01") throw new Error("diesel power DFO daily history should start by 2023");
    if (!daily.some((row) => typeof row.estimatedDfoConsumptionKbd === "number")) throw new Error("diesel power DFO daily rows are missing kb/d burn values");
    const weatherDates = new Set(weatherDaily.map((row) => row.date).filter(Boolean));
    if (weatherDates.size < 14) throw new Error("diesel power DFO weather rows should expose the available 14-day horizon");
    if (!weatherDaily.some((row) => row.sourceLabel)) throw new Error("diesel power DFO weather rows are missing source labels");
    if (!String(runtimePowerDfo.powerDfoCharts?.weatherBaselineNote || "").includes("Historical PADD 1 HDD baseline rows")) {
      throw new Error("diesel power DFO weather baseline caveat is missing");
    }
  } else if (runtimePowerDfo.powerDfoCharts?.available !== false) {
    throw new Error(`${config.key} power DFO payload should remain unavailable`);
  }
}

function verifyPowerDfoSourceFiles(config: ProductConfig, runtimeReference: RuntimeReference): void {
  const roles = new Set((runtimeReference.sourceFiles ?? []).map((file) => file.role));
  const powerRoles = [
    "power_dfo_daily",
    "power_dfo_weather",
    "power_dfo_forecast_24h",
    "power_dfo_manifest",
    "power_dfo_hourly_manifest",
  ];
  if (config.key === "diesel") {
    const missing = powerRoles.filter((role) => !roles.has(role));
    if (missing.length) throw new Error(`diesel Power DFO source metadata missing roles: ${missing.join(", ")}`);
  } else {
    const present = powerRoles.filter((role) => roles.has(role));
    if (present.length) throw new Error(`${config.key} should not package Power DFO source roles: ${present.join(", ")}`);
  }
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
  assertIncludes(`${config.key} crude runs exposes a direct override row`, indexHtml, "{id:'crudeRunsAdjustmentKbd',label:'Crude Runs Override',kind:'item muted adjustment'}");
  assertIncludes(`${config.key} crude runs override targets the calculated row`, indexHtml, "if (lineId === 'crudeRunsAdjustmentKbd') return 'crudeRunsKbd';");
  assertIncludes(`${config.key} weekly crude overrides use exact period keys`, indexHtml, "function crudeCellAdjustmentIndexKey(frequency, period, regionKey, unitKey)");
  assertIncludes(`${config.key} crude cell overrides are stored with their frequency and period`, indexHtml, "normalizeCapacityAdjustment({scope:'crude_cell',frequency,period:scopedPeriod");
  assertIncludes(`${config.key} crude cell override replacement is exact-period scoped`, indexHtml, "filter(adj => !crudeCellAdjustmentMatches(adj, frequency, period, regionKey, targetLineId))");
  assertIncludes(`${config.key} crude run calculation applies the exact manual value`, indexHtml, "manualCrudeRuns !== null ? manualCrudeRuns : Math.max(0, runCeiling - unplanned)");
  assertIncludes(`${config.key} weekly crude override labels its single-week scope`, indexHtml, "state.frequency === 'weekly' ? 'week' : 'month'");
  assertIncludes(`${config.key} capacity ledger shows exact crude override period`, indexHtml, "if (isCrudeCellAdjustment(adj)) return (adj.frequency === 'weekly' ? 'Week ending ' : 'Month ') + adj.period + ' only';");
  assertNotIncludes(`${config.key} crude cell lookup is not month-wide`, indexHtml, "latestRegionalCapacityAdjustment(point.regionKey, crudeAdjustmentTargetLineId(lineId), periodMonthValue(point.period))");
  assertIncludes(`${config.key} settings saves are serialized to avoid revision races`, indexHtml, "let settingsSaveChain = Promise.resolve();");
  assertIncludes(`${config.key} settings saves survive an immediate reload`, indexHtml, "body:JSON.stringify(settingsPayload(overrides)),keepalive:true");
  assertIncludes(`${config.key} balance cell saves start immediately`, indexHtml, "function queueBalanceAdjustmentsToServer(options=null){ void saveBalanceAdjustmentsToServer(options || {}); }");
  assertIncludes(`${config.key} crude cell saves start immediately`, indexHtml, "function queueCapacityAdjustmentsToServer(){ void saveCapacityAdjustmentsToServer(); }");
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
  const [manifest, monthlyLatest, weeklyLatest, indexHtml, runtimeBase, runtimeWeekly, runtimeCrudeWeekly, runtimePowerDfo, runtimeReference] = await Promise.all([
    readJson<BalanceManifest>(config.manifestPath),
    latestCsvDate(config.monthlyCsv),
    latestCsvDate(config.weeklyCsv),
    readFile(config.indexPath, "utf8"),
    readAssignedJson<RuntimeBase>(config.runtimeBasePath, "window.BALANCE_DATA = "),
    readAssignedJson<RuntimeWeekly>(config.runtimeWeeklyPath, ".weekly = "),
    readAssignedJson<RuntimeCrudeWeekly>(config.runtimeCrudeWeeklyPath, ".crudeWeekly = "),
    readAssignedJson<RuntimePowerDfo>(config.runtimePowerDfoPath, ".powerDfo = "),
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
  if ((runtimeBase.optimization?.lazyChunks?.length ?? 0) < 4) throw new Error(`${config.key} runtime optimization lazy chunk diagnostics are incomplete`);
  if ((runtimeBase.optimization?.recommendations?.length ?? 0) === 0) throw new Error(`${config.key} runtime optimization recommendations are missing`);
  if ((runtimeWeekly.regionalBalance?.weekly?.length ?? 0) === 0) throw new Error(`${config.key} runtime weekly regional rows are empty`);
  if ((runtimeCrudeWeekly.crudeRuns?.weekly?.length ?? 0) === 0) throw new Error(`${config.key} runtime weekly crude rows are empty`);
  if ((runtimeReference.sourceFiles?.length ?? 0) === 0) throw new Error(`${config.key} runtime reference source files are empty`);
  verifyPowerDfoSourceFiles(config, runtimeReference);
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
  verifyChartScenarioPropagation(indexHtml, config);
  verifyOutageProductionOffline(indexHtml, config);
  verifyNortheastPowerCharts(indexHtml, config, runtimePowerDfo);
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

async function verifyWeeklyCallArchives(): Promise<string[]> {
  const outputRoot = join("weekly_call_outputs", "outputs");
  const catalog = await readJson<WeeklyCallCatalog>(join(outputRoot, "index.json"));
  if (catalog.schema_version !== 4) throw new Error(`weekly call catalog schema must be 4, received ${catalog.schema_version}`);
  const results: string[] = [];
  for (const config of PRODUCTS) {
    const latestWeekly = await latestCsvDate(config.weeklyCsv);
    const entry = catalog.weeks
      .filter((row) => row.product === config.key)
      .sort((left, right) => left.actual_week_ending.localeCompare(right.actual_week_ending))
      .at(-1);
    if (!entry) throw new Error(`${config.key} weekly call archive is missing from index.json`);
    const archiveFreshness = weeklyCallArchiveFreshness(config.key, entry.actual_week_ending, latestWeekly);
    assertEqual(`${config.key} weekly call archive folder`, entry.folder, entry.actual_week_ending);
    assertEqual(`${config.key} weekly call archive manifest name`, entry.manifest, `${config.key}_manifest.json`);
    assertEqual(`${config.key} weekly call archive table image name`, entry.table_image, `${config.key}_weekly_balance_table.png`);
    const expectedBarCharts = [
      `${config.key}_eia_actuals.png`,
      `${config.key}_forecast_week_1.png`,
      `${config.key}_forecast_week_2.png`,
    ];
    assertEqual(`${config.key} weekly call archive bar chart names`, entry.bar_chart_images.join("|"), expectedBarCharts.join("|"));
    const archiveDir = join(outputRoot, entry.folder);
    const manifest = await readJson<WeeklyCallManifest>(join(archiveDir, entry.manifest));
    assertEqual(`${config.key} weekly call manifest product`, manifest.product, config.key);
    assertEqual(`${config.key} weekly call manifest latest week`, manifest.actual_week_ending, entry.actual_week_ending);
    assertEqual(`${config.key} weekly call manifest JSON`, manifest.weekly_json, entry.weekly_json);
    if (manifest.images.length !== 4) throw new Error(`${config.key} weekly call manifest expected 4 images, received ${manifest.images.length}`);
    const tableImage = manifest.images.find((image) => image.file === entry.table_image);
    if (!tableImage) throw new Error(`${config.key} weekly call manifest is missing its table image`);
    if (tableImage.file !== entry.table_image || tableImage.width_px !== 1323 || tableImage.height_px !== 1269) {
      throw new Error(`${config.key} weekly call table image must be a 1323 x 1269 PNG`);
    }
    for (const chartName of expectedBarCharts) {
      const chartImage = manifest.images.find((image) => image.file === chartName);
      if (!chartImage || chartImage.width_px !== 765 || chartImage.height_px !== 458) {
        throw new Error(`${config.key} weekly call bar chart ${chartName} must be a 765 x 458 PNG`);
      }
    }
    const payload = await readJson<WeeklyCallPayload>(join(archiveDir, entry.weekly_json));
    if (payload.schema_version !== 3) throw new Error(`${config.key} weekly call JSON schema must be 3`);
    assertEqual(`${config.key} weekly call JSON product`, payload.product?.key ?? "", config.key);
    if (payload.product?.stats_title) throw new Error(`${config.key} weekly call JSON still contains a stats title`);
    const actualChart = payload.inventory_changes?.actual;
    const forecastCharts = payload.inventory_changes?.forecasts ?? [];
    if (payload.inventory_changes?.unit !== "million barrels" || !actualChart || forecastCharts.length !== 2) {
      throw new Error(`${config.key} weekly call JSON must contain one actual and two forecast inventory charts in million barrels`);
    }
    assertEqual(`${config.key} weekly call JSON actual week`, actualChart.week_ending, entry.actual_week_ending);
    if (actualChart.status !== "actual" || forecastCharts.some((chart) => chart.status !== "forecast")) {
      throw new Error(`${config.key} weekly call JSON inventory chart statuses are incorrect`);
    }
    const expectedBars = config.key === "diesel" ? 7 : 6;
    for (const chart of [actualChart, ...forecastCharts]) {
      if (chart.labels.length !== expectedBars || chart.region_keys.length !== expectedBars || chart.values_mb.length !== expectedBars) {
        throw new Error(`${config.key} weekly call chart ${chart.week_ending} expected ${expectedBars} regional bars`);
      }
      if (chart.values_mb.some((value) => !Number.isFinite(value))) {
        throw new Error(`${config.key} weekly call chart ${chart.week_ending} contains a non-finite value`);
      }
    }
    for (const image of manifest.images) {
      const content = await readFile(join(archiveDir, image.file));
      if (content.byteLength < 1_000) throw new Error(`${config.key} weekly call image ${image.file} is unexpectedly small`);
    }
    const lag = archiveFreshness === "lagging" ? `:source=${latestWeekly}:lagging` : "";
    results.push(`${config.key}:weekly-call=${entry.actual_week_ending}${lag}`);
  }
  return results;
}

const updatePipelineSource = await readFile("src/update_pipeline.ts", "utf8");
assertNotIncludes("Kpler failures are not optional", updatePipelineSource, "continueOnFailure");
assertNotIncludes("Kpler steps do not use the removed optional wrapper", updatePipelineSource, "optionalStep(");
assertIncludes("Kpler full flow step remains in the all/other package", updatePipelineSource, 'scriptStep("Kpler flow package", "kpler")');
assertIncludes("Kpler PADD 1 split remains in the all/other package", updatePipelineSource, 'scriptStep("Kpler PADD 1 EIA split", "kpler:padd1:eia")');

const updateServerSource = await readFile("src/dashboard_update_server.ts", "utf8");
assertIncludes("runner distinguishes partial completion", updateServerSource, 'type JobStatus = "running" | "succeeded" | "partial" | "failed";');
assertIncludes("runner promotes skipped steps to warnings", updateServerSource, 'hasWarnings ? "partial" : "succeeded"');
assertIncludes("runner accepts the weekly call output job", updateServerSource, '"weekly-call-outputs"');
assertIncludes("runner saves weekly call outputs with the configured Python runtime", updateServerSource, "args: [weeklyCallOutputScript");
assertIncludes("runner reports weekly call outputs as saved", updateServerSource, 'job.result = "saved";');
assertIncludes("runner requires a weekly call output product", updateServerSource, 'weekly-call-outputs requires product=diesel or product=jet');
assertIncludes("runner forwards the selected product to the generator", updateServerSource, '"--product", outputProduct');
assertNotIncludes("runner no longer emits misleading raw child status", updateServerSource, "finished status=");

const [results, weeklyCallResults] = await Promise.all([
  Promise.all(PRODUCTS.map((config) => verifyProduct(config))),
  verifyWeeklyCallArchives(),
]);
console.log(`dashboard freshness ok ${[...results, ...weeklyCallResults].join(" ")}`);
