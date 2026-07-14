import { existsSync } from "node:fs";

const delayMs = Math.max(0, Number(process.env.US_BALANCES_FAKE_UPDATE_DELAY_MS || 75));
await new Promise((resolve) => setTimeout(resolve, delayMs));
const updateScript = String(process.argv[2] || "");
const updateGroup = String(process.argv[3] || "");
const suppressStart = Boolean(process.env.US_BALANCES_FAKE_NO_START_FILE && existsSync(process.env.US_BALANCES_FAKE_NO_START_FILE));
if (updateScript.endsWith("update_pipeline.ts") && !suppressStart) {
  console.log(`[update] group=${updateGroup} steps=1 phases=1 started_at=${new Date().toISOString()}`);
}
console.log("fake update completed without changing source data");
