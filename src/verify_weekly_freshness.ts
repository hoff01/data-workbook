import "./env.js";
import { readFile } from "node:fs/promises";
import { fetchBufferWithRetry } from "./common.js";

const EIA_WEEKLY_LATEST_SOURCE_ENV = "EIA_WEEKLY_LATEST_SOURCE";
const EIA_WEEKLY_SOURCE_CONFIG_ENV = "EIA_WEEKLY_SOURCE_CONFIG";
const EIA_WEEKLY_SOURCE_CONFIG_PATH = "config/eia_weekly_source.json";
const EIA_WPSR_PAGE_URL = "https://www.eia.gov/petroleum/supply/weekly/";
const EIA_WPSR_CSV_TEST_URL = "https://irtest.eia.gov/wpsr/wpsr.csv";
const EIA_WPSR_CSV_PROD_URL = "https://ir.eia.gov/wpsr/wpsr.csv";
const EIA_WPSR_CSV_PROD_START = "2026-06-10";
const PRODUCT_FILES = ["eia_weekly/diesel.csv", "eia_weekly/jet.csv", "eia_weekly/gasoline.csv"];

type LatestSource = "xls" | "csv";
type WeeklySourceConfig = {
  latest_source?: string;
  xls?: {
    page_url?: string;
  };
  csv?: {
    url?: string;
    test_url?: string;
    prod_url?: string;
    production_start?: string;
  };
};

const DEFAULT_WEEKLY_SOURCE_CONFIG: WeeklySourceConfig = {
  latest_source: "xls",
  xls: {
    page_url: EIA_WPSR_PAGE_URL,
  },
  csv: {
    url: "",
    test_url: EIA_WPSR_CSV_TEST_URL,
    prod_url: EIA_WPSR_CSV_PROD_URL,
    production_start: EIA_WPSR_CSV_PROD_START,
  },
};

function mergeConfig(base: WeeklySourceConfig, override: WeeklySourceConfig): WeeklySourceConfig {
  return {
    ...base,
    ...override,
    xls: { ...(base.xls ?? {}), ...(override.xls ?? {}) },
    csv: { ...(base.csv ?? {}), ...(override.csv ?? {}) },
  };
}

async function loadWeeklySourceConfig(): Promise<{ config: WeeklySourceConfig; path: string; exists: boolean }> {
  const path = process.env[EIA_WEEKLY_SOURCE_CONFIG_ENV]?.trim() || EIA_WEEKLY_SOURCE_CONFIG_PATH;
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as WeeklySourceConfig;
    return { config: mergeConfig(DEFAULT_WEEKLY_SOURCE_CONFIG, parsed), path, exists: true };
  } catch (error) {
    const code = typeof error === "object" && error && "code" in error ? String((error as { code?: unknown }).code) : "";
    if (code === "ENOENT") return { config: DEFAULT_WEEKLY_SOURCE_CONFIG, path, exists: false };
    throw error;
  }
}

function latestSourceMode(config: WeeklySourceConfig): LatestSource {
  const raw = (process.env[EIA_WEEKLY_LATEST_SOURCE_ENV] ?? config.latest_source ?? "xls").trim().toLowerCase();
  if (["xls", "xlsx", "excel", "tables", "wpsr_xls", "wpsr-xls"].includes(raw)) return "xls";
  if (["csv", "wpsr_csv", "wpsr-csv"].includes(raw)) return "csv";
  throw new Error(`Unsupported ${EIA_WEEKLY_LATEST_SOURCE_ENV}=${raw}; use xls or csv`);
}

function todayIso(): string {
  const override = process.env.EIA_WPSR_TODAY?.trim();
  if (override) return override;
  return new Date().toISOString().slice(0, 10);
}

function wpsrCsvUrl(config: WeeklySourceConfig, today = todayIso()): string {
  const override = process.env.EIA_WPSR_CSV_URL?.trim();
  if (override) return override;
  const configuredUrl = config.csv?.url?.trim();
  if (configuredUrl) return configuredUrl;
  const productionStart = config.csv?.production_start?.trim() || EIA_WPSR_CSV_PROD_START;
  const prodUrl = config.csv?.prod_url?.trim() || EIA_WPSR_CSV_PROD_URL;
  const testUrl = config.csv?.test_url?.trim() || EIA_WPSR_CSV_TEST_URL;
  return today >= productionStart ? prodUrl : testUrl;
}

function parseCsvLine(line: string): string[] {
  const values: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      values.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  values.push(current);
  return values;
}

function dateHeaderToIso(value: string): string {
  const match = value.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
  if (!match) throw new Error(`could not parse WPSR date column ${value}`);
  const month = match[1].padStart(2, "0");
  const day = match[2].padStart(2, "0");
  const rawYear = match[3];
  const year = rawYear.length === 2 ? `20${rawYear}` : rawYear;
  return `${year}-${month}-${day}`;
}

function latestWeekFromWpsr(text: string): string {
  const lines = text.split(/\r?\n/);
  const headerLine = lines.find((line) => line.startsWith("stub_1,"));
  if (!headerLine) throw new Error("WPSR CSV did not contain the expected stub_1 header");
  const columns = parseCsvLine(headerLine);
  if (columns.length < 4) throw new Error("WPSR CSV is missing current/week-ago date columns");
  return dateHeaderToIso(columns[2]);
}

function monthNameToNumber(value: string): string {
  const index = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
  ].indexOf(value.trim().toLowerCase());
  if (index < 0) throw new Error(`could not parse WPSR month ${value}`);
  return String(index + 1).padStart(2, "0");
}

function latestWeekFromWpsrPage(text: string): string {
  const compact = text.replace(/\s+/g, " ");
  const match = compact.match(/Data for week ending\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})/i);
  if (!match) throw new Error("WPSR page did not contain a Data for week ending line");
  return `${match[3]}-${monthNameToNumber(match[1])}-${match[2].padStart(2, "0")}`;
}

async function upstreamLatestWeek(config: WeeklySourceConfig): Promise<{ latest: string; source: string; mode: LatestSource }> {
  const mode = latestSourceMode(config);
  if (mode === "csv") {
    const sourceUrl = wpsrCsvUrl(config);
    return {
      latest: latestWeekFromWpsr((await fetchBufferWithRetry(sourceUrl)).toString("utf8")),
      source: sourceUrl,
      mode,
    };
  }
  const sourceUrl = config.xls?.page_url?.trim() || EIA_WPSR_PAGE_URL;
  return {
    latest: latestWeekFromWpsrPage((await fetchBufferWithRetry(sourceUrl)).toString("utf8")),
    source: sourceUrl,
    mode,
  };
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
  if (!latest) throw new Error(`${path} contains no week_ending rows`);
  return latest;
}

const { config: sourceConfig, path: sourceConfigPath, exists: sourceConfigExists } = await loadWeeklySourceConfig();
const { latest: upstreamLatest, source, mode } = await upstreamLatestWeek(sourceConfig);
const local = await Promise.all(PRODUCT_FILES.map(async (path) => ({ path, latest: await latestCsvDate(path) })));
const stale = local.filter((item) => item.latest < upstreamLatest);
if (stale.length) {
  throw new Error(
    `weekly freshness failed: upstream latest=${upstreamLatest}; stale exports=${stale
      .map((item) => `${item.path}:${item.latest}`)
      .join(", ")}`,
  );
}
console.log(
  `weekly freshness ok upstream=${upstreamLatest} source=${source} latest_source=${mode} config=${sourceConfigPath}:${sourceConfigExists ? "found" : "default"} ${local
    .map((item) => `${item.path}=${item.latest}`)
    .join(" ")}`,
);
