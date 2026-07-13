import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { stableCsvFingerprint, updateDataFingerprint } from "../src/update_data_fingerprint.js";

const root = mkdtempSync(join(tmpdir(), "us-balances-fingerprint-"));
const capacityDir = join(root, "eia_capacity");
const capacityPath = join(capacityDir, "refinery_unit_capacities_2025.csv");
mkdirSync(capacityDir, { recursive: true });

try {
  writeFileSync(
    capacityPath,
    'refinery_id,unit_label,capacity_kbd,note,generated_at\nrefinery-a,"Atmos, Distillation",100,"quoted ""note""",2026-07-13T12:00:00Z\n',
  );
  const firstFile = stableCsvFingerprint(capacityPath);
  const firstGroup = updateDataFingerprint(root, "other");

  writeFileSync(
    capacityPath,
    'refinery_id,unit_label,capacity_kbd,note,generated_at\r\nrefinery-a,"Atmos, Distillation",100,"quoted ""note""",2026-07-13T13:00:00Z\r\n',
  );
  assert.equal(stableCsvFingerprint(capacityPath), firstFile, "volatile timestamp and line endings must not imply new data");
  assert.equal(updateDataFingerprint(root, "other"), firstGroup, "volatile-only refresh must remain current");

  writeFileSync(
    capacityPath,
    'refinery_id,unit_label,capacity_kbd,note,generated_at\nrefinery-a,"Atmos, Distillation",101,"quoted ""note""",2026-07-13T13:00:00Z\n',
  );
  assert.notEqual(stableCsvFingerprint(capacityPath), firstFile, "business-value changes must be detected");
  assert.notEqual(updateDataFingerprint(root, "other"), firstGroup, "group fingerprint must detect business-value changes");
  console.log("dashboard data fingerprint contract ok");
} finally {
  rmSync(root, { recursive: true, force: true });
}
