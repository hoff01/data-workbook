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
  if (!indexHtml.includes(`src="data/${config.key}_balance_runtime_base.js"`)) {
    throw new Error(`${config.key} index.html does not reference expected runtime base script`);
  }

  for (const file of runtimeReference.sourceFiles ?? []) {
    const actualChecksum = await packagedChecksum(config, file.path);
    assertEqual(`${config.key} checksum ${file.role}`, runtimeReference.checksums?.[file.role] ?? "", actualChecksum);
    if (file.checksum) assertEqual(`${config.key} sourceFiles checksum ${file.role}`, file.checksum, actualChecksum);
  }

  return `${config.key}:weekly=${weeklyLatest}:monthly=${monthlyLatest}`;
}

const results = await Promise.all(PRODUCTS.map((config) => verifyProduct(config)));
console.log(`dashboard freshness ok ${results.join(" ")}`);
