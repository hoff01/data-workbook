import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

export type SharedOutage = {
  id: string;
  regionKey: string;
  refineryId?: string;
  refineryName?: string;
  unitKey?: string;
  unitLabel?: string;
  refinery: string;
  capacityOfflineKbd: number;
  startDate: string;
  endDate: string;
  type: "Planned" | "Unplanned" | "Other";
  note?: string;
  updatedAt?: string;
};

export type SharedOutageExport = {
  schemaVersion: 1;
  generatedAt: string;
  source: {
    file: "balance_dashboard_settings.json";
    updatedAt: string;
  };
  sharedProducts: ["diesel", "jet"];
  capacityUnit: "thousand barrels per day";
  outageCount: number;
  outages: SharedOutage[];
};

function roundCapacity(value: unknown): number {
  return Math.round(Math.max(0, Number(value || 0)) * 10) / 10;
}

export function canonicalSharedOutages(rows: readonly SharedOutage[]): SharedOutage[] {
  return rows
    .map((row) => ({
      id: String(row.id || ""),
      regionKey: String(row.regionKey || ""),
      refineryId: row.refineryId ? String(row.refineryId) : undefined,
      refineryName: row.refineryName ? String(row.refineryName) : undefined,
      unitKey: row.unitKey ? String(row.unitKey) : undefined,
      unitLabel: row.unitLabel ? String(row.unitLabel) : undefined,
      refinery: String(row.refinery || row.refineryName || ""),
      capacityOfflineKbd: roundCapacity(row.capacityOfflineKbd),
      startDate: String(row.startDate || ""),
      endDate: String(row.endDate || ""),
      type: row.type,
      note: row.note ? String(row.note) : undefined,
      updatedAt: row.updatedAt ? String(row.updatedAt) : undefined,
    }))
    .sort(
      (left, right) =>
        left.startDate.localeCompare(right.startDate) ||
        left.endDate.localeCompare(right.endDate) ||
        left.regionKey.localeCompare(right.regionKey) ||
        left.refinery.localeCompare(right.refinery) ||
        String(left.unitLabel || "").localeCompare(String(right.unitLabel || "")) ||
        left.id.localeCompare(right.id),
    );
}

export function sharedOutageExportPayload(
  outages: readonly SharedOutage[],
  sourceUpdatedAt: string,
  generatedAt = new Date().toISOString(),
): SharedOutageExport {
  const canonical = canonicalSharedOutages(outages);
  return {
    schemaVersion: 1,
    generatedAt,
    source: {
      file: "balance_dashboard_settings.json",
      updatedAt: sourceUpdatedAt,
    },
    sharedProducts: ["diesel", "jet"],
    capacityUnit: "thousand barrels per day",
    outageCount: canonical.length,
    outages: canonical,
  };
}

export function writeSharedOutageExport(
  outputPath: string,
  outages: readonly SharedOutage[],
  sourceUpdatedAt: string,
  generatedAt = new Date().toISOString(),
): SharedOutageExport {
  const payload = sharedOutageExportPayload(outages, sourceUpdatedAt, generatedAt);
  mkdirSync(dirname(outputPath), { recursive: true });
  const tempPath = join(dirname(outputPath), `.outages.${process.pid}.${Date.now()}.tmp`);
  writeFileSync(tempPath, JSON.stringify(payload, null, 2) + "\n");
  renameSync(tempPath, outputPath);
  return payload;
}
