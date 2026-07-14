import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export function isMainModule(metaUrl: string, entryPath = process.argv[1]): boolean {
  if (!entryPath) return false;
  const entryUrl = pathToFileURL(resolve(entryPath)).href;
  return process.platform === "win32" ? metaUrl.toLowerCase() === entryUrl.toLowerCase() : metaUrl === entryUrl;
}
