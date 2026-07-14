#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const invocations = [
  ["--import", "tsx", "src/update_pipeline.ts", "entrypoint-probe-invalid-group"],
  [resolve(ROOT, "node_modules", "tsx", "dist", "cli.mjs"), resolve(ROOT, "src", "update_pipeline.ts"), "entrypoint-probe-invalid-group"],
];

for (const args of invocations) {
  const result = spawnSync(process.execPath, args, {
    cwd: ROOT,
    encoding: "utf8",
    env: { ...process.env, FORCE_COLOR: "0" },
    windowsHide: true,
  });
  const output = `${result.stdout || ""}${result.stderr || ""}`;
  assert.equal(result.error, undefined);
  assert.equal(result.status, 1, `update entrypoint should reject the probe group; output:\n${output}`);
  assert.match(output, /Unknown update group entrypoint-probe-invalid-group/);
}
console.log("update pipeline entrypoint contract ok");
