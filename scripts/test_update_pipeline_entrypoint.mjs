#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
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
const updatePipelineSource = readFileSync(resolve(ROOT, "src", "update_pipeline.ts"), "utf8");
const weeklyGroup = updatePipelineSource.slice(
  updatePipelineSource.indexOf("  weekly: ["),
  updatePipelineSource.indexOf("  monthly: ["),
);
assert.match(weeklyGroup, /\.\.\.kplerContextSteps\(\)/, "weekly updates must run the full Kpler package and PADD 1 split");
assert.match(updatePipelineSource, /warningOnFailure/, "Kpler failures must become visible non-blocking update warnings");
assert.match(updatePipelineSource, /Kpler API data was not updated; continuing with existing Kpler guides and last valid packaged PADD 1 shares/);
const standaloneWeeklySource = readFileSync(resolve(ROOT, "src", "run_weekly_pipeline.ts"), "utf8");
const kplerFlowIndex = standaloneWeeklySource.indexOf('label: "Kpler flow package"');
const kplerSplitIndex = standaloneWeeklySource.indexOf('label: "Kpler PADD 1 EIA split"');
assert.ok(kplerFlowIndex >= 0 && kplerSplitIndex > kplerFlowIndex, "standalone weekly refresh must pull Kpler before applying its PADD 1 split");
assert.match(standaloneWeeklySource, /US_BALANCES_SKIP_KPLER_REFRESH/g, "standalone weekly Kpler steps must honor the shared skip switch");
console.log("update pipeline entrypoint contract ok");
