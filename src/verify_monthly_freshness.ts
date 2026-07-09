import "./env.js";
import { readFile } from "node:fs/promises";
import { fetchJsonWithRetry } from "./common.js";

type EiaRow = Record<string, string | number | null | undefined>;
type EiaPayload = {
  response?: {
    data?: EiaRow[];
  };
};

const PUBLIC_EIA_API_KEY_FALLBACK = "4ZooAQ2fowZXw2nzj8dhtscw8orLWsdpcEk0sbzM";
const CHECK_ENDPOINTS = [
  {
    label: "monthly product supplied",
    url: "https://api.eia.gov/v2/petroleum/cons/psup/data/",
    facets: { product: ["EPD0"] },
  },
  {
    label: "monthly refinery/downstream",
    url: "https://api.eia.gov/v2/petroleum/pnp/dwns/data/",
    facets: { duoarea: ["NUS"] },
  },
];
const PRODUCT_FILES = ["eia_monthly/diesel.csv", "eia_monthly/jet.csv"];

function resolveApiKey(): string {
  for (const key of ["EIA_API_KEY", "EIA_API_TOKEN", "EIA_KEY"]) {
    const value = process.env[key]?.trim();
    if (value) return value;
  }
  return PUBLIC_EIA_API_KEY_FALLBACK;
}

function requestParams(apiKey: string, endpoint: (typeof CHECK_ENDPOINTS)[number]): [string, string | number][] {
  const params: [string, string | number][] = [
    ["api_key", apiKey],
    ["frequency", "monthly"],
    ["data[0]", "value"],
    ["start", "2024-01"],
    ["sort[0][column]", "period"],
    ["sort[0][direction]", "desc"],
    ["offset", 0],
    ["length", 10],
  ];
  for (const [facet, values] of Object.entries(endpoint.facets)) {
    for (const value of values) params.push([`facets[${facet}][]`, value]);
  }
  return params;
}

async function latestUpstreamMonth(): Promise<string> {
  const apiKey = resolveApiKey();
  const periods = await Promise.all(CHECK_ENDPOINTS.map(async (endpoint) => {
    const payload = await fetchJsonWithRetry<EiaPayload>(endpoint.url, requestParams(apiKey, endpoint));
    const latest = (payload.response?.data ?? [])
      .map((row) => String(row.period ?? ""))
      .filter((period) => /^\d{4}-\d{2}$/.test(period))
      .sort()
      .at(-1);
    if (!latest) throw new Error(`${endpoint.label} returned no monthly periods`);
    return latest;
  }));
  return periods.sort().at(-1) ?? "";
}

async function latestCsvMonth(path: string): Promise<string> {
  const text = await readFile(path, "utf8");
  const dates = text
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.split(",", 1)[0])
    .filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date))
    .map((date) => date.slice(0, 7))
    .sort();
  const latest = dates.at(-1);
  if (!latest) throw new Error(`${path} contains no Date rows`);
  return latest;
}

const upstreamLatest = await latestUpstreamMonth();
const local = await Promise.all(PRODUCT_FILES.map(async (path) => ({ path, latest: await latestCsvMonth(path) })));
const stale = local.filter((item) => item.latest < upstreamLatest);
if (stale.length) {
  throw new Error(
    `monthly freshness failed: upstream latest=${upstreamLatest}; stale exports=${stale
      .map((item) => `${item.path}:${item.latest}`)
      .join(", ")}`,
  );
}
console.log(`monthly freshness ok upstream=${upstreamLatest} ${local.map((item) => `${item.path}=${item.latest}`).join(" ")}`);
