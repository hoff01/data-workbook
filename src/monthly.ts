import { readdir, rename, rm, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { gzipSync } from "node:zlib";
import {
  dedupeRows,
  ensureDir,
  fetchBufferWithRetry,
  fetchJsonWithRetry,
  fileBytes,
  nowIso,
  parseNumber,
  runLimited,
  sanitizeEiaPayload,
  sha256,
} from "./common.js";

type FieldType = "string" | "number" | "integer";

type FieldSpec = {
  name: string;
  type: FieldType;
};

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

type EndpointConfig = {
  slug: string;
  url: string;
  facets: Record<string, string[]>;
};

type EiaRow = Record<string, string | number | null | undefined>;

type EiaPayload = {
  response?: {
    total?: string | number;
    data?: EiaRow[];
  };
};

type MonthlyRow = {
  period_month: string;
  period_idx: number;
  source_endpoint: string;
  series: string;
  series_description: string;
  product_code: string;
  product_name: string;
  duoarea_code: string;
  duoarea_name: string;
  origin_code: string;
  destination_code: string;
  unit: string;
  value: number | null;
  value_status: string;
};

const OUT_DIR = "eia_monthly";
const START_PERIOD = process.env.EIA_MONTHLY_START ?? "2016-01";
const PAGE_LENGTH = 5000;
const CONCURRENCY = Number(process.env.EIA_CONCURRENCY ?? 4);
const PUBLIC_EIA_API_KEY_FALLBACK = "4ZooAQ2fowZXw2nzj8dhtscw8orLWsdpcEk0sbzM";
const BULK_DOWNLOADS = [
  {
    label: "PET",
    path: "PET.zip",
    url: process.env.EIA_PET_BULK_URL ?? "https://api.eia.gov/bulk/PET.zip",
  },
  {
    label: "TOTAL",
    path: "TOTAL.zip",
    url: process.env.EIA_TOTAL_BULK_URL ?? "https://api.eia.gov/bulk/TOTAL.zip",
  },
];

const ENDPOINTS: EndpointConfig[] = [
  {
    slug: "move_pipe",
    url: "https://api.eia.gov/v2/petroleum/move/pipe/data/",
    facets: { product: ["EPD0"] },
  },
  {
    slug: "pnp_dwns",
    url: "https://api.eia.gov/v2/petroleum/pnp/dwns/data/",
    facets: { duoarea: ["NUS", "R10", "R20", "R30", "R40", "R50"] },
  },
  {
    slug: "pnp_refp",
    url: "https://api.eia.gov/v2/petroleum/pnp/refp/data/",
    facets: { duoarea: ["NUS", "R10", "R20", "R30", "R40", "R50"], product: ["EPD0"] },
  },
  {
    slug: "pnp_unc",
    url: "https://api.eia.gov/v2/petroleum/pnp/unc/data/",
    facets: { duoarea: ["NUS", "R10", "R20", "R30", "R40", "R50"] },
  },
  {
    slug: "stoc_ts",
    url: "https://api.eia.gov/v2/petroleum/stoc/ts/data/",
    facets: { duoarea: ["NUS", "R10", "R1X", "R1Y", "R1Z", "R20", "R30", "R40", "R50"], product: ["EPD0"] },
  },
  {
    slug: "move_tb",
    url: "https://api.eia.gov/v2/petroleum/move/tb/data/",
    facets: {
      duoarea: [
        "R10-R20",
        "R10-R30",
        "R10-R40",
        "R10-R50",
        "R1X-R30",
        "R1Y-R30",
        "R1Z-R30",
        "R20-R10",
        "R20-R30",
        "R20-R40",
        "R20-R50",
        "R30-R10",
        "R30-R20",
        "R30-R40",
        "R30-R50",
        "R40-R10",
        "R40-R20",
        "R40-R30",
        "R40-R50",
        "R50-R10",
        "R50-R20",
        "R50-R30",
        "R50-R40",
      ],
      product: ["EPD0"],
    },
  },
  {
    slug: "move_ptb",
    url: "https://api.eia.gov/v2/petroleum/move/ptb/data/",
    facets: {
      duoarea: [
        "R10-R20",
        "R10-R30",
        "R10-R40",
        "R10-R50",
        "R20-R10",
        "R20-R30",
        "R20-R40",
        "R20-R50",
        "R30-R10",
        "R30-R20",
        "R30-R40",
        "R30-R50",
        "R40-R10",
        "R40-R20",
        "R40-R30",
        "R40-R50",
        "R50-R10",
        "R50-R20",
        "R50-R30",
        "R50-R40",
      ],
      product: ["EPD0"],
    },
  },
  {
    slug: "cons_psup",
    url: "https://api.eia.gov/v2/petroleum/cons/psup/data/",
    facets: { product: ["EPD0"] },
  },
];

const FIELDS: FieldSpec[] = [
  { name: "period_month", type: "string" },
  { name: "period_idx", type: "integer" },
  { name: "source_endpoint", type: "string" },
  { name: "series", type: "string" },
  { name: "series_description", type: "string" },
  { name: "product_code", type: "string" },
  { name: "product_name", type: "string" },
  { name: "duoarea_code", type: "string" },
  { name: "duoarea_name", type: "string" },
  { name: "origin_code", type: "string" },
  { name: "destination_code", type: "string" },
  { name: "unit", type: "string" },
  { name: "value", type: "number" },
  { name: "value_status", type: "string" },
];

function resolveApiKey(): string {
  for (const key of ["EIA_API_KEY", "EIA_API_TOKEN", "EIA_KEY"]) {
    const value = process.env[key]?.trim();
    if (value) return value;
  }
  return PUBLIC_EIA_API_KEY_FALLBACK;
}

function requestParams(
  apiKey: string,
  endpoint: EndpointConfig,
  offset: number,
): [string, string | number][] {
  const params: [string, string | number][] = [
    ["api_key", apiKey],
    ["frequency", "monthly"],
    ["data[0]", "value"],
    ["start", START_PERIOD],
    ["sort[0][column]", "period"],
    ["sort[0][direction]", "asc"],
    ["offset", offset],
    ["length", PAGE_LENGTH],
  ];
  for (const [facet, values] of Object.entries(endpoint.facets)) {
    for (const value of [...new Set(values)]) {
      params.push([`facets[${facet}][]`, value]);
    }
  }
  return params;
}

function periodIndex(period: string): number {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return -1;
  return (Number(match[1]) - 2016) * 12 + (Number(match[2]) - 1);
}

function splitMovement(duoarea: string): { origin: string; destination: string } {
  const [origin, destination] = duoarea.includes("-") ? duoarea.split("-", 2) : ["", ""];
  return { origin: origin ?? "", destination: destination ?? "" };
}

function normalizeRows(endpoint: EndpointConfig, rows: readonly EiaRow[]): MonthlyRow[] {
  return rows.flatMap((row) => {
    const period = String(row.period ?? "").trim();
    if (!/^\d{4}-\d{2}$/.test(period) || period < START_PERIOD) return [];
    const idx = periodIndex(period);
    if (idx < 0) return [];
    const rawValue = row.value;
    const value = parseNumber(rawValue);
    const nonNumeric = value === null && rawValue !== null && rawValue !== undefined && String(rawValue).trim() !== "";
    const duoarea = String(row.duoarea ?? "").trim();
    const movement = splitMovement(duoarea);
    return [
      {
        period_month: `${period}-01`,
        period_idx: idx,
        source_endpoint: endpoint.slug,
        series: String(row.series ?? "").trim(),
        series_description: String(row["series-description"] ?? "").trim(),
        product_code: String(row.product ?? "").trim(),
        product_name: String(row["product-name"] ?? "").trim(),
        duoarea_code: duoarea,
        duoarea_name: String(row["area-name"] ?? "").trim(),
        origin_code: movement.origin,
        destination_code: movement.destination,
        unit: String(row.units ?? "").trim(),
        value,
        value_status: nonNumeric ? String(rawValue).trim() : "",
      },
    ];
  });
}

async function fetchEndpoint(apiKey: string, endpoint: EndpointConfig): Promise<{
  endpoint: EndpointConfig;
  rows: EiaRow[];
  hashes: string[];
}> {
  const first = await fetchJsonWithRetry<EiaPayload>(endpoint.url, requestParams(apiKey, endpoint, 0));
  const total = Number(first.response?.total ?? first.response?.data?.length ?? 0);
  const firstRows = first.response?.data ?? [];
  const offsets = [];
  for (let offset = PAGE_LENGTH; offset < total; offset += PAGE_LENGTH) offsets.push(offset);
  const pages = await runLimited(offsets, CONCURRENCY, async (offset) => {
    return fetchJsonWithRetry<EiaPayload>(endpoint.url, requestParams(apiKey, endpoint, offset));
  });
  const allPayloads = [first, ...pages];
  return {
    endpoint,
    rows: [firstRows, ...pages.map((page) => page.response?.data ?? [])].flat(),
    hashes: allPayloads.map((page) => sha256(JSON.stringify(sanitizeEiaPayload(page)))),
  };
}

async function cleanOutputDir(dir: string): Promise<void> {
  await ensureDir(dir);
  for (const entry of await readdir(dir)) {
    await rm(`${dir}/${entry}`, { recursive: true, force: true });
  }
}

async function refreshBulkZip(download: (typeof BULK_DOWNLOADS)[number]): Promise<number> {
  const content = await fetchBufferWithRetry(download.url);
  if (content.length < 1_000_000) {
    throw new Error(`${download.label} bulk download from ${download.url} is unexpectedly small`);
  }
  const tmpPath = `${download.path}.tmp`;
  await writeFile(tmpPath, content);
  await rename(tmpPath, download.path);
  return content.length;
}

async function writeCleanPlaceholder(path: string, payload: JsonValue): Promise<number> {
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  await writeFile(path, Buffer.concat([Buffer.from("EIA_CLEAN_V1\0"), gzipSync(body, { level: 9 })]));
  return fileBytes(path);
}

async function writeParquetZstd(
  path: string,
  fields: readonly FieldSpec[],
  rows: readonly Record<string, unknown>[],
  metadata: Record<string, JsonValue>,
): Promise<number> {
  const child = spawnSync(
    "python3",
    ["src/write_parquet_zstd.py", path],
    {
      cwd: process.cwd(),
      input: JSON.stringify({ fields, rows, metadata }),
      encoding: "utf8",
      maxBuffer: 50 * 1024 * 1024,
    },
  );
  if (child.status !== 0) {
    throw new Error(`write_parquet_zstd.py failed: ${child.stderr || child.stdout}`);
  }
  return fileBytes(path);
}

async function main(): Promise<void> {
  await cleanOutputDir(OUT_DIR);
  const apiKey = resolveApiKey();

  const fetched = await runLimited(ENDPOINTS, CONCURRENCY, (endpoint) => fetchEndpoint(apiKey, endpoint));
  const normalized = fetched.flatMap((item) => normalizeRows(item.endpoint, item.rows));
  const rows = dedupeRows(normalized, FIELDS.map((field) => field.name)) as MonthlyRow[];

  const rawBytes = await writeParquetZstd(`${OUT_DIR}/raw`, FIELDS, rows as unknown as Record<string, unknown>[], {
    eia_manifest: {
      pipeline_name: "eia_monthly",
      schema_version: 2,
      start_period: START_PERIOD,
      source_count: ENDPOINTS.length,
      row_count: rows.length,
      column_count: FIELDS.length,
      clean_subset_status: "clean is a zero-series typed binary placeholder until the forecast-required series list is defined.",
      endpoints: ENDPOINTS.map((endpoint) => ({ slug: endpoint.slug, url: endpoint.url, facets: endpoint.facets })),
    },
  });

  const cleanPayload: JsonValue = {
    pipeline_name: "eia_monthly",
    format: "eia_clean_placeholder",
    schema_version: 1,
    generated_at: nowIso(),
    source_content_hash: sha256(JSON.stringify(fetched.map((item) => item.hashes))),
    series_count: 0,
    period_count: 0,
    row_count: 0,
    reason: "Forecast clean series list has not been defined; do not load raw EIA history on client startup.",
  };
  const cleanBytes = await writeCleanPlaceholder(`${OUT_DIR}/clean`, cleanPayload);
  const latestPeriod = rows.map((row) => row.period_month).sort().at(-1)?.slice(0, 7) ?? "";
  const bulkResults = await Promise.all(BULK_DOWNLOADS.map(refreshBulkZip));
  const bulkText = BULK_DOWNLOADS.map((download, index) => `${download.label}=${bulkResults[index]}`).join(" ");
  console.log(`monthly rows=${rows.length} raw=${rawBytes} clean=${cleanBytes} latest=${latestPeriod} bulk=${bulkText}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
