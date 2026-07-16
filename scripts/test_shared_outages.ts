import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { writeSharedOutageExport } from "../src/shared_outages.js";

const root = mkdtempSync(join(tmpdir(), "us-balances-outages-"));
const outputPath = join(root, "outages.json");

try {
  const payload = writeSharedOutageExport(
    outputPath,
    [
      {
        id: "later",
        regionKey: "padd3",
        refinery: "Beta Refinery",
        capacityOfflineKbd: 12.26,
        startDate: "2026-08-10",
        endDate: "2026-08-12",
        type: "Unplanned",
      },
      {
        id: "earlier",
        regionKey: "padd2",
        refineryId: "alpha",
        refineryName: "Alpha Refinery",
        unitKey: "atmospheric-distillation",
        unitLabel: "Atmospheric Distillation",
        refinery: "Alpha Refinery",
        capacityOfflineKbd: 25,
        startDate: "2026-08-01",
        endDate: "2026-08-05",
        type: "Planned",
        note: "Turnaround",
        updatedAt: "2026-07-16T12:00:00.000Z",
      },
    ],
    "2026-07-16T12:00:00.000Z",
    "2026-07-16T12:01:00.000Z",
  );
  const saved = JSON.parse(readFileSync(outputPath, "utf8"));
  assert.deepEqual(saved, JSON.parse(JSON.stringify(payload)));
  assert.equal(saved.schemaVersion, 1);
  assert.deepEqual(saved.sharedProducts, ["diesel", "jet"]);
  assert.equal(saved.capacityUnit, "thousand barrels per day");
  assert.equal(saved.outageCount, 2);
  assert.deepEqual(saved.outages.map((row: { id: string }) => row.id), ["earlier", "later"]);
  assert.equal(saved.outages[1].capacityOfflineKbd, 12.3);

  writeSharedOutageExport(
    outputPath,
    [],
    "2026-07-16T13:00:00.000Z",
    "2026-07-16T13:01:00.000Z",
  );
  const refreshed = JSON.parse(readFileSync(outputPath, "utf8"));
  assert.equal(refreshed.outageCount, 0);
  assert.deepEqual(refreshed.outages, []);
  assert.equal(refreshed.source.updatedAt, "2026-07-16T13:00:00.000Z");
  console.log("shared outages export contract ok");
} finally {
  rmSync(root, { recursive: true, force: true });
}
