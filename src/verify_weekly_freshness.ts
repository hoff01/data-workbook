import { readFile } from "node:fs/promises";
import { fetchBufferWithRetry } from "./common.js";

const EIA_WPSR_CSV_TEST_URL = "https://irtest.eia.gov/wpsr/wpsr.csv";
const EIA_WPSR_CSV_PROD_URL = "https://ir.eia.gov/wpsr/wpsr.csv";
const EIA_WPSR_CSV_PROD_START = "2026-06-10";
const PRODUCT_FILES = ["eia_weekly/diesel.csv", "eia_weekly/jet.csv", "eia_weekly/gasoline.csv"];

function todayIso(): string {
  const override = process.env.EIA_WPSR_TODAY?.trim();
  if (override) return override;
  return new Date().toISOString().slice(0, 10);
}

function wpsrCsvUrl(today = todayIso()): string {
  return today >= EIA_WPSR_CSV_PROD_START ? EIA_WPSR_CSV_PROD_URL : EIA_WPSR_CSV_TEST_URL;
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

const sourceUrl = wpsrCsvUrl();
const upstreamLatest = latestWeekFromWpsr((await fetchBufferWithRetry(sourceUrl)).toString("utf8"));
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
  `weekly freshness ok upstream=${upstreamLatest} source=${sourceUrl} ${local
    .map((item) => `${item.path}=${item.latest}`)
    .join(" ")}`,
);
