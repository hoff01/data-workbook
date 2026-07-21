import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { weeklyCallArchiveFreshness } from "./weekly_call_archive_freshness.js";

type ProductKey = "diesel" | "jet";

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
  dashboard_state_json: string;
  dashboard_state_fingerprint: string;
  images: Array<{ file: string; width_px: number; height_px: number }>;
};

type DashboardStateRow = {
  period: string;
  status: "actual" | "forecast";
  regionKey: string;
  demandKbd?: number;
  exportsKbd?: number;
  exportsLatinAmericaKbd?: number;
  exportsEuropeKbd?: number;
  exportsAfricaKbd?: number;
  exportsOtherKbd?: number;
  periodBuildDrawKb?: number;
};

type PortableDashboardState = {
  schema?: string;
  schemaVersion?: number;
  product?: string;
  fingerprint?: string;
  settings?: Record<string, unknown> & { revision?: string };
  materialized?: { regionalBalance?: { monthly?: DashboardStateRow[]; weekly?: DashboardStateRow[] } };
};

type WeeklyCallTableRow = { key?: string; values?: Record<string, number | null> };
type WeeklyCallTableRegion = { key?: string; region_key?: string; rows?: WeeklyCallTableRow[] };

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
  periods?: Array<{ week_ending?: string; status?: "actual" | "forecast" }>;
  table?: { frequency?: string; regions?: WeeklyCallTableRegion[] };
  dashboard_state?: PortableDashboardState;
  inventory_changes?: {
    unit?: string;
    actual?: WeeklyCallInventoryChart;
    forecasts?: WeeklyCallInventoryChart[];
  };
};

const PRODUCTS: Array<{ key: ProductKey; weeklyCsv: string; savedState: string }> = [
  { key: "diesel", weeklyCsv: "eia_weekly/diesel.csv", savedState: "Diesel_Balance/diesel_balance.json" },
  { key: "jet", weeklyCsv: "eia_weekly/jet.csv", savedState: "Jet_Balance/jet_balance.json" },
];

async function readJson<T>(path: string): Promise<T> {
  return JSON.parse(await readFile(path, "utf8")) as T;
}

async function readOptionalJson<T>(path: string): Promise<T | null> {
  try {
    return await readJson<T>(path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
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

function assertEqual(label: string, actual: string, expected: string): void {
  if (actual !== expected) throw new Error(`${label} mismatch: expected=${expected} actual=${actual}`);
}

function assertNear(label: string, actual: number | null | undefined, expected: number, tolerance: number): void {
  if (!Number.isFinite(Number(actual)) || Math.abs(Number(actual) - expected) > tolerance) {
    throw new Error(`${label} mismatch: expected=${expected} actual=${actual}`);
  }
}

function roundHalfUp(value: number, digits: number): number {
  const factor = 10 ** digits;
  const sign = value < 0 ? -1 : 1;
  return sign * Math.floor(Math.abs(value) * factor + 0.500000001) / factor;
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
    assertEqual(`${config.key} weekly call dashboard-state name`, manifest.dashboard_state_json, `${config.key}_dashboard_state.json`);
    if (!/^[a-f0-9]{64}$/.test(manifest.dashboard_state_fingerprint)) throw new Error(`${config.key} weekly call manifest has an invalid dashboard-state fingerprint`);
    if (manifest.images.length !== 4) throw new Error(`${config.key} weekly call manifest expected 4 images, received ${manifest.images.length}`);
    const tableImage = manifest.images.find((image) => image.file === entry.table_image);
    if (!tableImage || tableImage.width_px !== 1323 || tableImage.height_px !== 1269) {
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
    const dashboardState = await readJson<PortableDashboardState>(join(archiveDir, manifest.dashboard_state_json));
    if (dashboardState.schema !== "us-balances.dashboard-state" || dashboardState.schemaVersion !== 1) throw new Error(`${config.key} archived dashboard state has an invalid schema`);
    assertEqual(`${config.key} archived dashboard-state product`, dashboardState.product ?? "", config.key);
    assertEqual(`${config.key} archived dashboard-state fingerprint`, dashboardState.fingerprint ?? "", manifest.dashboard_state_fingerprint);
    assertEqual(`${config.key} embedded dashboard-state fingerprint`, payload.dashboard_state?.fingerprint ?? "", manifest.dashboard_state_fingerprint);
    assertEqual(`${config.key} embedded dashboard-state settings revision`, payload.dashboard_state?.settings?.revision ?? "", dashboardState.settings?.revision ?? "");
    const currentSavedState = await readOptionalJson<PortableDashboardState>(config.savedState);
    if (currentSavedState) {
      assertEqual(`${config.key} current saved-state product`, currentSavedState.product ?? "", config.key);
      assertEqual(`${config.key} archive settings match current saved state`, JSON.stringify(dashboardState.settings ?? {}), JSON.stringify(currentSavedState.settings ?? {}));
      assertEqual(`${config.key} archive monthly rows match current saved state`, JSON.stringify(dashboardState.materialized?.regionalBalance?.monthly ?? []), JSON.stringify(currentSavedState.materialized?.regionalBalance?.monthly ?? []));
      assertEqual(`${config.key} archive weekly rows match current saved state`, JSON.stringify(dashboardState.materialized?.regionalBalance?.weekly ?? []), JSON.stringify(currentSavedState.materialized?.regionalBalance?.weekly ?? []));
    }
    const stateRows = dashboardState.materialized?.regionalBalance?.weekly ?? [];
    if (!stateRows.length) throw new Error(`${config.key} archived dashboard state contains no materialized weekly rows`);
    const outputPeriods = payload.periods ?? [];
    if (outputPeriods.length !== 6 || outputPeriods[0]?.status !== "actual" || outputPeriods.slice(1).some((period) => period.status !== "forecast")) {
      throw new Error(`${config.key} weekly call JSON must place one current actual before five forecast weeks`);
    }
    assertEqual(`${config.key} weekly call first period`, outputPeriods[0]?.week_ending ?? "", entry.actual_week_ending);
    const stateByKey = new Map(stateRows.map((row) => [`${row.period}|${row.regionKey}`, row]));
    for (const chart of [actualChart, ...forecastCharts]) {
      chart.region_keys.forEach((regionKey, index) => {
        const stateRow = stateByKey.get(`${chart.week_ending}|${regionKey}`);
        if (!stateRow) throw new Error(`${config.key} dashboard state is missing ${chart.week_ending} ${regionKey}`);
        assertNear(`${config.key} ${chart.week_ending} ${regionKey} inventory change`, chart.values_mb[index], roundHalfUp(Number(stateRow.periodBuildDrawKb || 0) / 1_000, 2), 0.001);
      });
    }
    for (const region of payload.table?.regions ?? []) {
      const regionKey = region.region_key ?? region.key ?? "";
      const rowsByKey = new Map((region.rows ?? []).map((row) => [row.key, row]));
      for (const period of outputPeriods) {
        const week = period.week_ending ?? "";
        const stateRow = stateByKey.get(`${week}|${regionKey}`);
        if (!stateRow) throw new Error(`${config.key} table dashboard state is missing ${week} ${regionKey}`);
        assertNear(`${config.key} ${week} ${regionKey} table exports`, rowsByKey.get("exports")?.values?.[week], roundHalfUp(Number(stateRow.exportsKbd || 0), 1), 0.001);
        assertNear(`${config.key} ${week} ${regionKey} table demand`, rowsByKey.get("demand")?.values?.[week], roundHalfUp(Number(stateRow.demandKbd || 0), 1), 0.001);
        assertNear(`${config.key} ${week} ${regionKey} table build/draw`, rowsByKey.get("net_kb")?.values?.[week], roundHalfUp(Number(stateRow.periodBuildDrawKb || 0), 0), 0.001);
      }
    }
    for (const row of stateRows.filter((point) => point.status === "forecast" && point.regionKey === "padd3")) {
      const destinationTotal = Number(row.exportsLatinAmericaKbd || 0) + Number(row.exportsEuropeKbd || 0) + Number(row.exportsAfricaKbd || 0) + Number(row.exportsOtherKbd || 0);
      assertNear(`${config.key} ${row.period} PADD 3 forecast destination sum`, row.exportsKbd, destinationTotal, 0.03);
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

const results = await verifyWeeklyCallArchives();
console.log(`weekly call outputs ok ${results.join(" ")}`);
