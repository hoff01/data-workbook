import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const DASHBOARD_SERVER_APP_ID = "balance-dashboard-update-server";

const DASHBOARD_SERVER_BUILD_INPUTS = [
  "src/dashboard_server_contract.ts",
  "src/dashboard_update_server.ts",
  "src/shared_outages.ts",
  "src/update_data_fingerprint.ts",
  "src/update_pipeline.ts",
  "weekly_call_outputs/generate_weekly_images.py",
  "weekly_call_outputs/weekly_stats_config.json",
];

export function dashboardServerBuildId(root: string): string {
  const hash = createHash("sha256");
  for (const relativePath of DASHBOARD_SERVER_BUILD_INPUTS) {
    hash.update(relativePath);
    hash.update("\0");
    hash.update(readFileSync(join(root, relativePath)));
    hash.update("\0");
  }
  return hash.digest("hex").slice(0, 16);
}
