import { createHash, type Hash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";

export type UpdateGroup = "weekly" | "monthly" | "other" | "all" | "power-dfo";

const UPDATE_DATA_FILES: Record<Exclude<UpdateGroup, "all">, string[]> = {
  weekly: [
    "eia_weekly/diesel.csv",
    "eia_weekly/gasoline.csv",
    "eia_weekly/jet.csv",
    "Kpler/output/padd1_split/padd1_import_export_shares_weekly.csv",
  ],
  monthly: [
    "eia_monthly/diesel.csv",
    "eia_monthly/gasoline.csv",
    "eia_monthly/jet.csv",
    "padd_1/padd_1_distillate_estimates.csv",
    "padd_1/padd_1_distillate_shares.csv",
  ],
  other: [
    "Kpler/output",
    "eia_capacity/downstream_charge_capacity_monthly_wide.csv",
    "eia_capacity/downstream_charge_capacity_high_level_monthly_wide.csv",
    "eia_capacity/refinery_unit_capacities_2025.csv",
    "power_generation_dfo/estimated_daily_dfo.csv",
    "power_generation_dfo/dfo_generation_forecast_24h.csv",
    "power_generation_dfo/weather_14d_padd1_cities.csv",
  ],
  "power-dfo": [
    "power_generation_dfo/estimated_daily_dfo.csv",
    "power_generation_dfo/dfo_generation_forecast_24h.csv",
    "power_generation_dfo/weather_14d_padd1_cities.csv",
  ],
};

const VOLATILE_CSV_COLUMNS = new Set([
  "created_at",
  "generated_at",
  "generatedat",
  "pull_timestamp",
  "pulled_at",
  "request_hash",
  "run_at",
  "run_ended_at",
  "run_started_at",
  "snapshot_date",
  "source_hash",
  "updated_at",
]);

function normalizeHeader(value: string): string {
  return value
    .replace(/^\uFEFF/, "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }
    if (!quoted && character === ",") {
      row.push(field);
      field = "";
      continue;
    }
    if (!quoted && (character === "\n" || character === "\r")) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      continue;
    }
    field += character;
  }
  if (quoted) throw new Error("unterminated quoted CSV field");
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function hashValue(hash: Hash, value: string): void {
  const bytes = Buffer.from(value, "utf8");
  hash.update(String(bytes.length));
  hash.update(":");
  hash.update(bytes);
  hash.update(";");
}

export function stableCsvFingerprint(path: string): string {
  const rows = parseCsv(readFileSync(path, "utf8"));
  const header = rows.shift() || [];
  const keepIndexes = header
    .map((value, index) => ({ index, name: normalizeHeader(value) }))
    .filter(({ name }) => !VOLATILE_CSV_COLUMNS.has(name));
  const hash = createHash("sha256");
  for (const { name } of keepIndexes) hashValue(hash, name);
  hash.update("\n");
  for (const row of rows) {
    for (const { index } of keepIndexes) hashValue(hash, row[index] || "");
    hash.update("\n");
  }
  return hash.digest("hex");
}

function collectFingerprintFiles(path: string): string[] {
  if (!existsSync(path)) return [];
  const stat = statSync(path);
  if (stat.isFile()) return extname(path).toLowerCase() === ".csv" ? [path] : [];
  if (!stat.isDirectory()) return [];
  return readdirSync(path, { withFileTypes: true })
    .flatMap((entry) => collectFingerprintFiles(join(path, entry.name)));
}

export function updateDataFingerprint(root: string, group: UpdateGroup): string {
  const targets = group === "all"
    ? [...new Set(Object.values(UPDATE_DATA_FILES).flat())]
    : UPDATE_DATA_FILES[group];
  const files = [...new Set(targets.flatMap((target) => collectFingerprintFiles(join(root, target))))]
    .sort((left, right) => left.localeCompare(right));
  const hash = createHash("sha256");
  for (const file of files) {
    hashValue(hash, relative(root, file));
    hashValue(hash, stableCsvFingerprint(file));
  }
  return hash.digest("hex");
}
