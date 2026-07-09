import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function parseEnvValue(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2 && trimmed[0] === trimmed.at(-1) && ["'", '"'].includes(trimmed[0])) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function loadEnvFile(path: string, protectedKeys: Set<string>, override = false): void {
  if (!existsSync(path)) return;
  const lines = readFileSync(path, "utf8").split(/\r?\n/);
  for (const rawLine of lines) {
    let line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.startsWith("export ")) line = line.slice(7).trim();
    const separator = line.indexOf("=");
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    const value = parseEnvValue(line.slice(separator + 1));
    if (!key || key.startsWith("#") || protectedKeys.has(key) || value === "") continue;
    if (override || process.env[key] === undefined) process.env[key] = value;
  }
}

export function loadEnvFiles(repoDir = REPO_DIR): void {
  const protectedKeys = new Set(Object.keys(process.env));
  const runtimeRoot = process.env.US_BALANCES_RUNTIME_ROOT;
  loadEnvFile(resolve(repoDir, ".env"), protectedKeys);
  loadEnvFile(resolve(repoDir, ".env.local"), protectedKeys, true);
  if (runtimeRoot) loadEnvFile(resolve(runtimeRoot, ".env.local"), protectedKeys, true);
}

loadEnvFiles();
