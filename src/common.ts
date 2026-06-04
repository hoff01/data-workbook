import { createHash } from "node:crypto";
import { mkdir, stat } from "node:fs/promises";

export const USER_AGENT =
  "python-pulls-eia-pipeline/0.1 (build-time data pipeline; local forecast artifacts)";

export function nowIso(): string {
  return new Date().toISOString();
}

export async function ensureDir(path: string): Promise<void> {
  await mkdir(path, { recursive: true });
}

export function sha256(data: Buffer | Uint8Array | string): string {
  return createHash("sha256").update(data).digest("hex");
}

export function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const normalized = String(value).replace(/,/g, "").trim();
  if (!normalized || normalized === "." || normalized === "--") return null;
  if (/^[^\d.-]+$/.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

export async function fileBytes(path: string): Promise<number> {
  return (await stat(path)).size;
}

function stableRowKey(row: Record<string, unknown>, columns: readonly string[]): string {
  return columns.map((column) => `${column}=${String(row[column] ?? "")}`).join("\u001f");
}

export function dedupeRows<T extends Record<string, unknown>>(
  rows: readonly T[],
  columns: readonly string[],
): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const row of rows) {
    const key = stableRowKey(row, columns);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

export async function fetchBufferWithRetry(url: string, attempts = 3): Promise<Buffer> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          "User-Agent": USER_AGENT,
        },
        redirect: "follow",
      });
      const arrayBuffer = await response.arrayBuffer();
      const buffer = Buffer.from(arrayBuffer);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} for ${url}: ${buffer.toString("utf8", 0, 200)}`);
      }
      return buffer;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** (attempt - 1)));
      }
    }
  }
  throw lastError;
}

export async function fetchJsonWithRetry<T>(
  url: string,
  params: readonly [string, string | number][],
  attempts = 3,
): Promise<T> {
  const queryUrl = new URL(url);
  for (const [key, value] of params) {
    queryUrl.searchParams.append(key, String(value));
  }
  const response = await fetchBufferWithRetry(queryUrl.toString(), attempts);
  return JSON.parse(response.toString("utf8")) as T;
}

export function sanitizeEiaPayload<T>(payload: T): T {
  return JSON.parse(
    JSON.stringify(payload, (key, value) => {
      if (key === "api_key") return "[redacted]";
      return value;
    }),
  ) as T;
}

export async function runLimited<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  async function worker(): Promise<void> {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await fn(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => worker()));
  return results;
}
