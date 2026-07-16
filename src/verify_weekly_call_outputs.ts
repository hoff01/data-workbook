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

const PRODUCTS: Array<{ key: ProductKey; weeklyCsv: string }> = [
  { key: "diesel", weeklyCsv: "eia_weekly/diesel.csv" },
  { key: "jet", weeklyCsv: "eia_weekly/jet.csv" },
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

function assertEqual(label: string, actual: string, expected: string): void {
  if (actual !== expected) throw new Error(`${label} mismatch: expected=${expected} actual=${actual}`);
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
