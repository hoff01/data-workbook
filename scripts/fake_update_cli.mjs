import { appendFileSync, existsSync, unlinkSync } from "node:fs";

const delayMs = Math.max(0, Number(process.env.US_BALANCES_FAKE_UPDATE_DELAY_MS || 75));
await new Promise((resolve) => setTimeout(resolve, delayMs));
const updateScript = String(process.argv[2] || "");
const updateGroup = String(process.argv[3] || "");
const settingsRebuild = !updateScript;
if (settingsRebuild && process.env.US_BALANCES_FAKE_SETTINGS_REBUILD_LOG) {
  appendFileSync(process.env.US_BALANCES_FAKE_SETTINGS_REBUILD_LOG, `rebuild ${new Date().toISOString()}\n`);
}
if (settingsRebuild && process.env.US_BALANCES_FAKE_SETTINGS_REBUILD_FAIL_FILE && existsSync(process.env.US_BALANCES_FAKE_SETTINGS_REBUILD_FAIL_FILE)) {
  unlinkSync(process.env.US_BALANCES_FAKE_SETTINGS_REBUILD_FAIL_FILE);
  console.error("fake settings rebuild failed once");
  process.exitCode = 7;
} else {
const suppressStart = Boolean(process.env.US_BALANCES_FAKE_NO_START_FILE && existsSync(process.env.US_BALANCES_FAKE_NO_START_FILE));
if (updateScript.endsWith("update_pipeline.ts") && !suppressStart) {
  console.log(`[update] group=${updateGroup} steps=1 phases=1 started_at=${new Date().toISOString()}`);
  if (["weekly", "monthly"].includes(updateGroup) && process.env.US_BALANCES_FAKE_KPLER_WARNING === "1") {
    console.log("[update] step 1/1 warning: Kpler flow package reason=Kpler API data was not updated; continuing with existing Kpler guides and last valid packaged PADD 1 shares");
  }
}
console.log("fake update completed without changing source data");
}
