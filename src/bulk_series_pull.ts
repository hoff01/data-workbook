import "./env.js";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { fetchBufferWithRetry } from "./common.js";

type BulkDownload = {
  label: string;
  path: string;
  url: string;
};

const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = process.env.US_BALANCES_SHARED_ROOT ? resolve(process.env.US_BALANCES_SHARED_ROOT) : SOURCE_ROOT;
const MIN_BULK_BYTES = 1_000_000;

const BULK_DOWNLOADS: BulkDownload[] = [
  {
    label: "PET",
    path: process.env.EIA_MONTHLY_BULK_SOURCE ?? "cache/eia/PET.zip",
    url: process.env.EIA_PET_BULK_URL ?? "https://api.eia.gov/bulk/PET.zip",
  },
];

async function refreshBulkZip(download: BulkDownload): Promise<number> {
  const content = await fetchBufferWithRetry(download.url);
  if (content.length < MIN_BULK_BYTES) {
    throw new Error(`${download.label} bulk download from ${download.url} is unexpectedly small`);
  }
  const targetPath = join(ROOT, download.path);
  const tmpPath = `${targetPath}.tmp`;
  await mkdir(dirname(targetPath), { recursive: true });
  await writeFile(tmpPath, content);
  await rename(tmpPath, targetPath);
  return content.length;
}

async function main(): Promise<void> {
  const results = await Promise.all(BULK_DOWNLOADS.map(refreshBulkZip));
  const summary = BULK_DOWNLOADS.map((download, index) => `${download.path}=${results[index]}`).join(" ");
  console.log(`bulk series local files refreshed ${summary}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
