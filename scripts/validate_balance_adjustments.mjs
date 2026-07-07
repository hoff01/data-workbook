#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";

const ROOT = process.cwd();
const DAY_MS = 24 * 60 * 60 * 1000;
const OUTAGE_RAMP_DOWN_DAYS = 3;

const PRODUCTS = [
  {
    key: "diesel",
    folder: "Diesel_Balance",
    baseFile: "data/diesel_balance_runtime_base.js",
    weeklyFile: "data/diesel_balance_runtime_weekly.js",
    crudeWeeklyFile: "data/diesel_balance_runtime_crude_weekly.js",
  },
  {
    key: "jet",
    folder: "Jet_Balance",
    baseFile: "data/jet_balance_runtime_base.js",
    weeklyFile: "data/jet_balance_runtime_weekly.js",
    crudeWeeklyFile: "data/jet_balance_runtime_crude_weekly.js",
  },
];

const CRUDE_AGGREGATES = {
  us: ["padd1", "padd2", "padd3", "padd4", "padd5"],
  p123: ["padd1", "padd2", "padd3"],
  p13: ["padd1", "padd3"],
};

const EXPORT_DESTINATION_FIELDS = [
  "exportsLatinAmericaKbd",
  "exportsEuropeKbd",
  "exportsAfricaKbd",
  "exportsOtherKbd",
];

const EXPORT_DESTINATION_LINE_BY_FIELD = {
  exportsLatinAmericaKbd: "exportsLatinAmerica",
  exportsEuropeKbd: "exportsEurope",
  exportsAfricaKbd: "exportsAfrica",
  exportsOtherKbd: "exportsOther",
};

const ADJUSTABLE_BALANCE_LINES = new Set([
  "yieldAdjustmentPct",
  "demandAdjustment",
  "importsAdjustment",
  "canadaImportsAdjustment",
  "nonCanadaImportsAdjustment",
  "exportsAdjustment",
  "exportsLatinAmericaAdjustment",
  "exportsEuropeAdjustment",
  "exportsAfricaAdjustment",
  "exportsOtherAdjustment",
]);

const BALANCE_ADJUSTMENT_ALIASES = {
  production: ["production", "productionKbd"],
  productionKbd: ["productionKbd", "production"],
  demand: ["demand", "demandKbd", "productSupplied", "demandAdjustment"],
  demandAdjustment: ["demandAdjustment", "demand", "demandKbd", "productSupplied"],
  productSupplied: ["productSupplied", "demand", "demandKbd", "demandAdjustment"],
  imports: ["imports", "importsKbd", "importsAdjustment"],
  importsAdjustment: ["importsAdjustment", "imports", "importsKbd"],
  canadaImports: ["canadaImports", "canadaImportsKbd", "canadaImportsAdjustment"],
  canadaImportsKbd: ["canadaImportsKbd", "canadaImports", "canadaImportsAdjustment"],
  canadaImportsAdjustment: ["canadaImportsAdjustment", "canadaImports", "canadaImportsKbd"],
  nonCanadaImports: ["nonCanadaImports", "nonCanadaImportsKbd", "nonCanadaImportsAdjustment"],
  nonCanadaImportsKbd: ["nonCanadaImportsKbd", "nonCanadaImports", "nonCanadaImportsAdjustment"],
  nonCanadaImportsAdjustment: ["nonCanadaImportsAdjustment", "nonCanadaImports", "nonCanadaImportsKbd"],
  exports: ["exports", "exportsKbd", "exportsAdjustment"],
  exportsAdjustment: ["exportsAdjustment", "exports", "exportsKbd"],
  exportsLatinAmerica: ["exportsLatinAmerica", "exportsLatinAmericaKbd", "exportsLatinAmericaAdjustment"],
  exportsLatinAmericaKbd: ["exportsLatinAmericaKbd", "exportsLatinAmerica", "exportsLatinAmericaAdjustment"],
  exportsLatinAmericaAdjustment: ["exportsLatinAmericaAdjustment", "exportsLatinAmerica", "exportsLatinAmericaKbd"],
  exportsEurope: ["exportsEurope", "exportsEuropeKbd", "exportsEuropeAdjustment"],
  exportsEuropeKbd: ["exportsEuropeKbd", "exportsEurope", "exportsEuropeAdjustment"],
  exportsEuropeAdjustment: ["exportsEuropeAdjustment", "exportsEurope", "exportsEuropeKbd"],
  exportsAfrica: ["exportsAfrica", "exportsAfricaKbd", "exportsAfricaAdjustment"],
  exportsAfricaKbd: ["exportsAfricaKbd", "exportsAfrica", "exportsAfricaAdjustment"],
  exportsAfricaAdjustment: ["exportsAfricaAdjustment", "exportsAfrica", "exportsAfricaKbd"],
  exportsOther: ["exportsOther", "exportsOtherKbd", "exportsOtherAdjustment"],
  exportsOtherKbd: ["exportsOtherKbd", "exportsOther", "exportsOtherAdjustment"],
  exportsOtherAdjustment: ["exportsOtherAdjustment", "exportsOther", "exportsOtherKbd"],
  netReceiptsKbd: ["netReceiptsKbd", "netReceipts"],
  stocks: ["stocks", "stocksKb"],
  stocksKb: ["stocksKb", "stocks"],
  yieldPct: ["yieldPct", "yield", "yieldPercent", "yieldAdjustmentPct"],
  yield: ["yield", "yieldPct", "yieldPercent", "yieldAdjustmentPct"],
  yieldAdjustmentPct: ["yieldAdjustmentPct", "yieldPct", "yield", "yieldPercent"],
};

const BALANCE_LINE_CANONICAL = {
  productionKbd: "production",
  demandKbd: "demand",
  productSupplied: "demand",
  demandAdjustment: "demand",
  importsKbd: "imports",
  importsAdjustment: "imports",
  canadaImportsKbd: "canadaImports",
  canadaImportsAdjustment: "canadaImports",
  nonCanadaImportsKbd: "nonCanadaImports",
  nonCanadaImportsAdjustment: "nonCanadaImports",
  exportsKbd: "exports",
  exportsAdjustment: "exports",
  exportsLatinAmericaKbd: "exportsLatinAmerica",
  exportsLatinAmericaAdjustment: "exportsLatinAmerica",
  exportsEuropeKbd: "exportsEurope",
  exportsEuropeAdjustment: "exportsEurope",
  exportsAfricaKbd: "exportsAfrica",
  exportsAfricaAdjustment: "exportsAfrica",
  exportsOtherKbd: "exportsOther",
  exportsOtherAdjustment: "exportsOther",
  netReceipts: "netReceiptsKbd",
  stocksKb: "stocks",
  yield: "yieldPct",
  yieldPercent: "yieldPct",
  yieldAdjustmentPct: "yieldPct",
};

const SUM_FIELDS = [
  "demandKbd",
  "productionKbd",
  "importsKbd",
  "canadaImportsKbd",
  "nonCanadaImportsKbd",
  "exportsKbd",
  "exportsLatinAmericaKbd",
  "exportsEuropeKbd",
  "exportsAfricaKbd",
  "exportsOtherKbd",
  "netReceiptsKbd",
  "receiptsKbd",
  "shipmentsKbd",
  "stockChangeKbd",
  "stocksKb",
  "operableCapacityKbd",
  "operatingCapacityKbd",
  "plannedMaintenanceKbd",
  "unplannedMaintenanceKbd",
  "crudeRunsKbd",
];

const DIFF_FIELDS = [
  ...SUM_FIELDS,
  "balanceKbd",
  "yieldPct",
  "yieldAdjustmentPct",
  "operatingUtilizationPct",
  "exPlannedUtilizationPct",
  "daysForwardCover",
];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function round1(value) {
  return Math.round(Number(value || 0) * 10) / 10;
}

function round2(value) {
  return Math.round(Number(value || 0) * 100) / 100;
}

function round3(value) {
  return Math.round(Number(value || 0) * 1000) / 1000;
}

function roundCapacity1(value) {
  return Math.round(Math.max(0, Number(value || 0)) * 10) / 10;
}

function near(left, right, tolerance = 0.015) {
  const a = Number(left);
  const b = Number(right);
  if (!Number.isFinite(a) && !Number.isFinite(b)) return true;
  return Math.abs((Number.isFinite(a) ? a : 0) - (Number.isFinite(b) ? b : 0)) <= tolerance;
}

function safePct(numerator, denominator) {
  const n = Number(numerator);
  const d = Number(denominator);
  return Number.isFinite(n) && Number.isFinite(d) && d > 0 ? (n / d) * 100 : 0;
}

function average(values) {
  const valid = values.map(Number).filter(Number.isFinite);
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
}

function yearOf(period) {
  return Number(String(period || "").slice(0, 4));
}

function monthOf(period) {
  return Number(String(period || "").slice(5, 7));
}

function periodMonthValue(period) {
  return String(period || "").slice(0, 7);
}

function addDaysText(period, days) {
  const date = new Date(String(period) + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function addMonthsText(period, months) {
  const date = new Date(Date.UTC(yearOf(period), monthOf(period) - 1 + months, 1));
  return date.toISOString().slice(0, 7);
}

function periodDays(period) {
  const text = String(period || "");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return 7;
  const start = Date.UTC(yearOf(text), monthOf(text) - 1, 1);
  const end = Date.UTC(yearOf(text), monthOf(text), 0);
  return Math.round((end - start) / DAY_MS) + 1;
}

function dateValue(value) {
  const time = Date.parse(String(value || "") + "T00:00:00Z");
  return Number.isFinite(time) ? time : null;
}

function dateKeyFromMs(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function periodRange(period, frequency) {
  if (frequency === "weekly") {
    const anchor = new Date(period + "T00:00:00Z");
    const end = new Date(anchor);
    end.setUTCDate(anchor.getUTCDate() - 1);
    const start = new Date(anchor);
    start.setUTCDate(anchor.getUTCDate() - 7);
    return { start: start.getTime(), end: end.getTime(), days: 7 };
  }
  const start = Date.UTC(yearOf(period), monthOf(period) - 1, 1);
  const end = Date.UTC(yearOf(period), monthOf(period), 0);
  return { start, end, days: Math.round((end - start) / DAY_MS) + 1 };
}

function isoWeekInfo(period) {
  const date = new Date(String(period || "").slice(0, 10) + "T00:00:00Z");
  if (!Number.isFinite(date.getTime())) return { year: yearOf(String(period || "")), week: 1 };
  const day = date.getUTCDay() || 7;
  const thursday = new Date(date);
  thursday.setUTCDate(date.getUTCDate() + 4 - day);
  const isoYear = thursday.getUTCFullYear();
  const yearStart = new Date(Date.UTC(isoYear, 0, 1));
  const week = Math.ceil(((thursday.getTime() - yearStart.getTime()) / DAY_MS + 1) / 7);
  return { year: isoYear, week: Math.min(53, Math.max(1, week)) };
}

function slotOf(period, frequency) {
  return frequency === "weekly" ? isoWeekInfo(period).week : monthOf(period);
}

function minForecastEnd(a, b) {
  const left = String(a || "");
  const right = String(b || "");
  if (!left) return right;
  if (!right) return left;
  return left < right ? left : right;
}

function receiptLineId(flowId) {
  return "receipt:" + flowId;
}

function receiptAdjustmentLineId(flowId) {
  return "receiptAdjustment:" + flowId;
}

function isReceiptFlowLine(lineId) {
  return String(lineId || "").startsWith("receipt:");
}

function isReceiptAdjustmentLine(lineId) {
  return String(lineId || "").startsWith("receiptAdjustment:");
}

function receiptAdjustmentFlowId(lineId) {
  return String(lineId || "").replace(/^receiptAdjustment:/, "");
}

function adjustmentTargetLineId(lineId) {
  const raw = String(lineId || "").trim();
  if (isReceiptAdjustmentLine(raw)) return receiptLineId(receiptAdjustmentFlowId(raw));
  if (raw === "demandAdjustment") return "demand";
  if (raw === "importsAdjustment") return "imports";
  if (raw === "canadaImportsAdjustment") return "canadaImports";
  if (raw === "nonCanadaImportsAdjustment") return "nonCanadaImports";
  if (raw === "exportsAdjustment") return "exports";
  if (raw === "exportsLatinAmericaAdjustment") return "exportsLatinAmerica";
  if (raw === "exportsEuropeAdjustment") return "exportsEurope";
  if (raw === "exportsAfricaAdjustment") return "exportsAfrica";
  if (raw === "exportsOtherAdjustment") return "exportsOther";
  return raw;
}

function normalizeBalanceLineId(lineId) {
  const target = adjustmentTargetLineId(lineId);
  return BALANCE_LINE_CANONICAL[target] || target;
}

function balanceAdjustmentAliases(lineId) {
  return (BALANCE_ADJUSTMENT_ALIASES[lineId] || [lineId]).map(normalizeBalanceLineId);
}

function normalizeBalanceAdjustment(row, baseRegions) {
  if (!row || typeof row !== "object") return null;
  const frequency = row.frequency === "weekly" ? "weekly" : "monthly";
  const period = String(row.period || "").trim();
  const regionKey = String(row.regionKey || "").trim();
  const lineId = normalizeBalanceLineId(row.lineId);
  const valueKbd = Number(row.valueKbd ?? row.value ?? row.percent ?? 0);
  if (!period || !baseRegions.includes(regionKey) || !lineId || !Number.isFinite(valueKbd) || valueKbd < 0) return null;
  return {
    frequency,
    period,
    regionKey,
    lineId,
    valueKbd: round3(valueKbd),
    note: String(row.note || "").trim(),
    updatedAt: row.updatedAt || new Date().toISOString(),
  };
}

function loadRuntime(product) {
  const window = {};
  const context = { window };
  window.window = window;
  for (const relative of [product.baseFile, product.weeklyFile, product.crudeWeeklyFile]) {
    const file = join(ROOT, product.folder, relative);
    vm.runInNewContext(readFileSync(file, "utf8"), context, { filename: file });
  }
  const data = clone(window.BALANCE_DATA);
  const chunks = window.__BALANCE_CHUNKS__ || {};
  if (chunks.weekly?.regionalBalance?.weekly) {
    data.regionalBalance.weekly = clone(chunks.weekly.regionalBalance.weekly);
    const weeklyFlows = new Map((chunks.weekly.regionalBalance.movementFlows || []).map((flow) => [flow.id, flow.weekly || []]));
    data.regionalBalance.movementFlows = (data.regionalBalance.movementFlows || []).map((flow) => ({
      ...flow,
      weekly: clone(weeklyFlows.get(flow.id) || flow.weekly || []),
    }));
  }
  if (chunks.crudeWeekly?.crudeRuns?.weekly) {
    data.crudeRuns.weekly = clone(chunks.crudeWeekly.crudeRuns.weekly);
  }
  return data;
}

class Calculator {
  constructor(runtime, extraAdjustments = []) {
    this.D = clone(runtime);
    this.hasSinglePadd1 = this.D.regionalBalance.regions.some((region) => region.key === "padd1");
    this.aggregates = this.hasSinglePadd1
      ? { us: ["padd1", "padd2", "padd3", "padd4", "padd5"], p123: ["padd1", "padd2", "padd3"], p13: ["padd1", "padd3"] }
      : { us: ["padd1ab", "padd1c", "padd2", "padd3", "padd4", "padd5"], p123: ["padd1ab", "padd1c", "padd2", "padd3"], p13: ["padd1ab", "padd1c", "padd3"] };
    this.baseRegions = this.D.regionalBalance.regions.map((region) => region.key).filter((key) => !this.aggregates[key]);
    this.adjustments = [...(this.D.settings?.adjustments || []), ...extraAdjustments]
      .map((row) => normalizeBalanceAdjustment(row, this.baseRegions))
      .filter(Boolean)
      .sort((a, b) => a.frequency.localeCompare(b.frequency) || a.period.localeCompare(b.period) || a.regionKey.localeCompare(b.regionKey) || a.lineId.localeCompare(b.lineId));
    this.crudeOutages = clone(this.D.settings?.crudeOutages || []);
    this.capacityAdjustments = clone(this.D.settings?.refineryCapacityAdjustments || []);
    this.cache = new Map();
    this.movementById = new Map((this.D.regionalBalance.movementFlows || []).map((flow) => [flow.id, flow]));
  }

  cached(key, build) {
    if (this.cache.has(key)) return this.cache.get(key);
    const value = build();
    this.cache.set(key, value);
    return value;
  }

  forecastEnd(frequency) {
    const settingEnd = frequency === "weekly" ? this.D.settings.forecastEnd : this.D.settings.forecastEnd.slice(0, 7);
    const embedded = frequency === "weekly" ? this.D.forecast.weeklyThrough : this.D.forecast.monthlyThrough;
    return minForecastEnd(settingEnd, embedded);
  }

  rawRowsForFrequency(frequency) {
    return frequency === "weekly" ? this.D.regionalBalance.weekly || [] : this.D.regionalBalance.monthly || [];
  }

  rowsForFrequency(frequency) {
    return frequency === "weekly" ? this.adjustedWeeklyBalanceRows() : this.adjustedMonthlyBalanceRows();
  }

  bucketRows(rows) {
    const periods = new Map();
    for (const row of rows) {
      const bucket = periods.get(row.period) || {};
      bucket[row.regionKey] = row;
      periods.set(row.period, bucket);
    }
    return periods;
  }

  rawBuckets(frequency) {
    return this.cached(`rawBuckets:${frequency}`, () => this.bucketRows(this.rawRowsForFrequency(frequency)));
  }

  rowsByRegion(regionKey, frequency, adjusted = true) {
    const source = adjusted ? this.rowsForFrequency(frequency) : this.rawRowsForFrequency(frequency);
    return source.filter((row) => row.regionKey === regionKey);
  }

  periodBuckets(frequency) {
    const rows = this.rowsForFrequency(frequency);
    return Array.from(this.bucketRows(rows).entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }

  periodEntriesForBalance(frequency) {
    const end = this.forecastEnd(frequency);
    return this.periodBuckets(frequency).filter(([period, bucket]) => {
      const hasForecast = Object.values(bucket).some((row) => row?.status === "forecast");
      return !hasForecast || period <= end;
    });
  }

  regionMemberKeys(regionKey) {
    return this.baseRegions.includes(regionKey) ? [regionKey] : this.aggregates[regionKey] || [];
  }

  balanceAdjustmentValue(frequency, period, regionKey, lineId) {
    const aliases = balanceAdjustmentAliases(lineId);
    let latest = null;
    for (const adjustment of this.adjustments) {
      if (adjustment.frequency !== frequency || adjustment.period !== period || adjustment.regionKey !== regionKey) continue;
      if (!aliases.includes(normalizeBalanceLineId(adjustment.lineId))) continue;
      if (!latest || String(adjustment.updatedAt || "").localeCompare(String(latest.updatedAt || "")) >= 0) latest = adjustment;
    }
    const value = latest ? Number(latest.valueKbd) : null;
    return Number.isFinite(value) ? value : null;
  }

  applyBalanceAdjustment(value, frequency, period, regionKey, lineId) {
    const override = this.balanceAdjustmentValue(frequency, period, regionKey, lineId);
    return override === null ? value : override;
  }

  movementScope(regionKey) {
    return this.cached(`movementScope:${regionKey}`, () => {
      const memberKeys = this.regionMemberKeys(regionKey);
      const members = new Set(memberKeys);
      const flows = this.D.regionalBalance.movementFlows || [];
      const touchingFlows = flows.filter((flow) => members.has(flow.toRegionKey) || members.has(flow.fromRegionKey));
      return { members, touchingFlows };
    });
  }

  movementRow(frequency, period, flowId) {
    const flow = this.movementById.get(flowId);
    return (flow?.[frequency] || []).find((row) => row.period === period) || null;
  }

  movementBaseValue(frequency, period, flowId) {
    const row = this.movementRow(frequency, period, flowId);
    return row ? Number(row.valueKbd || 0) : null;
  }

  movementFlowValue(frequency, period, flowId) {
    const flow = this.movementById.get(flowId);
    const row = this.movementRow(frequency, period, flowId);
    const base = row ? Number(row.valueKbd || 0) : null;
    if (!flow || base === null) return null;
    const override = row.status === "forecast" ? this.balanceAdjustmentValue(frequency, period, flow.toRegionKey, receiptLineId(flowId)) : null;
    return override === null ? base : override;
  }

  movementSummaryForRegion(frequency, period, regionKey) {
    const scope = this.movementScope(regionKey);
    if (!scope.members.size || !(this.D.regionalBalance.movementFlows || []).length) {
      return { hasFlows: false, receiptsKbd: 0, shipmentsKbd: 0, netReceiptsKbd: null };
    }
    let receiptsKbd = 0;
    let shipmentsKbd = 0;
    let count = 0;
    for (const flow of scope.touchingFlows) {
      const value = this.movementFlowValue(frequency, period, flow.id);
      if (value === null) continue;
      count += 1;
      if (scope.members.has(flow.toRegionKey)) receiptsKbd += value;
      if (scope.members.has(flow.fromRegionKey)) shipmentsKbd += value;
    }
    return { hasFlows: count > 0, receiptsKbd: round2(receiptsKbd), shipmentsKbd: round2(shipmentsKbd), netReceiptsKbd: round2(receiptsKbd - shipmentsKbd) };
  }

  validBaseCrudeRegion(regionKey) {
    return ["padd1", "padd2", "padd3", "padd4", "padd5"].includes(regionKey);
  }

  crudeRegionForBalanceRegion(regionKey) {
    return regionKey === "padd1ab" || regionKey === "padd1c" ? "padd1" : regionKey;
  }

  crudeRowsForFrequency(frequency) {
    return frequency === "weekly" ? this.D.crudeRuns.weekly || [] : this.D.crudeRuns.monthly || [];
  }

  crudeRowsForRegion(regionKey, frequency) {
    return this.crudeRowsForFrequency(frequency).filter((row) => row.regionKey === regionKey);
  }

  crudePeriodBuckets(frequency) {
    return this.cached(`crudePeriodBuckets:${frequency}`, () => {
      const buckets = this.bucketRows(this.crudeRowsForFrequency(frequency));
      return Array.from(buckets.entries()).sort((a, b) => a[0].localeCompare(b[0]));
    });
  }

  crudeAllPeriods(frequency) {
    return this.cached(`crudeAllPeriods:${frequency}`, () => {
      const buckets = new Map(this.crudePeriodBuckets(frequency));
      const actualPeriods = Array.from(buckets.keys()).sort();
      const latest = actualPeriods.at(-1);
      const end = this.forecastEnd(frequency);
      const future = [];
      if (latest) {
        let next = frequency === "weekly" ? addDaysText(latest, 7) : addMonthsText(latest, 1);
        for (let guard = 0; next <= end && guard < 520; guard += 1) {
          if (!buckets.has(next)) future.push(next);
          next = frequency === "weekly" ? addDaysText(next, 7) : addMonthsText(next, 1);
        }
      }
      return [
        ...actualPeriods.map((period) => [period, buckets.get(period) || {}, true]),
        ...future.map((period) => [period, {}, false]),
      ];
    });
  }

  crudeInfoIndex(frequency) {
    return this.cached(`crudeInfoIndex:${frequency}`, () => new Map(this.crudeAllPeriods(frequency).map(([period, bucket, isActual]) => [period, { bucket, isActual }])));
  }

  latestMonthlyCrudeBasis(regionKey, period) {
    const month = periodMonthValue(period);
    const rows = this.crudeRowsForRegion(regionKey, "monthly");
    return rows.filter((row) => row.period <= month).at(-1) || rows.at(-1) || {};
  }

  latestCapacityAdjustmentIn(rows, periodMonth) {
    const target = String(periodMonth || "");
    for (let index = (rows?.length || 0) - 1; index >= 0; index -= 1) {
      if (String(rows[index]?.periodMonth || "") <= target) return rows[index];
    }
    return null;
  }

  exactCapacityAdjustmentIn(rows, periodMonth) {
    const target = String(periodMonth || "");
    for (let index = (rows?.length || 0) - 1; index >= 0; index -= 1) {
      if (String(rows[index]?.periodMonth || "") === target) return rows[index];
    }
    return null;
  }

  regionalCapacityAdjustmentCarriesForward(lineId) {
    return lineId !== "exPlannedUtilizationAdjustmentPct";
  }

  latestRegionalCapacityAdjustment(regionKey, lineId, periodMonth) {
    const rows = this.capacityAdjustments
      .filter((row) => row.refineryId === "__regional_capacity__" && row.regionKey === regionKey && row.unitKey === lineId)
      .sort((a, b) => String(a.periodMonth || "").localeCompare(String(b.periodMonth || "")));
    const exact = this.regionalCapacityAdjustmentCarriesForward(lineId) ? this.latestCapacityAdjustmentIn(rows, periodMonth) : this.exactCapacityAdjustmentIn(rows, periodMonth);
    if (exact) return exact;
    if (lineId !== "operableCapacityKbd") return null;
    const fallbackRows = this.capacityAdjustments
      .filter((row) => row.refineryId === "__regional_capacity__" && row.regionKey === regionKey && row.unitKey === "operatingCapacityKbd")
      .sort((a, b) => String(a.periodMonth || "").localeCompare(String(b.periodMonth || "")));
    return this.latestCapacityAdjustmentIn(fallbackRows, periodMonth);
  }

  regionalCapacityRowValue(regionKey, lineId, periodMonth, fallback = 0) {
    const adjustment = this.latestRegionalCapacityAdjustment(regionKey, lineId, periodMonth);
    return adjustment ? Number(adjustment.capacityKbd || 0) : Number(fallback || 0);
  }

  outageRampFactor(dayOffset) {
    if (!Number.isFinite(dayOffset) || dayOffset < 1 || dayOffset > OUTAGE_RAMP_DOWN_DAYS) return 0;
    return (OUTAGE_RAMP_DOWN_DAYS - dayOffset + 1) / (OUTAGE_RAMP_DOWN_DAYS + 1);
  }

  outageDailyVector() {
    return this.cached("outageDailyVector", () => {
      const days = new Map();
      const addValue = (target, type, value) => {
        const bucket = type === "Planned" ? "planned" : type === "Unplanned" ? "unplanned" : "other";
        target[bucket] += value;
        target.total += value;
      };
      const applyOutageValue = (regionKey, type, dateMs, value) => {
        if (!value) return;
        const dateKey = dateKeyFromMs(dateMs);
        const byRegion = days.get(dateKey) || {};
        const regionTotals = byRegion[regionKey] || { planned: 0, unplanned: 0, other: 0, total: 0 };
        addValue(regionTotals, type, value);
        byRegion[regionKey] = regionTotals;
        days.set(dateKey, byRegion);
      };
      for (const outage of this.crudeOutages) {
        const regionKey = this.validBaseCrudeRegion(outage.regionKey) ? outage.regionKey : "";
        const start = dateValue(outage.startDate);
        const end = dateValue(outage.endDate);
        const value = Number(outage.capacityOfflineKbd || 0);
        if (!regionKey || start === null || end === null || !value) continue;
        for (let ms = start, guard = 0; ms <= end && guard < 10000; ms += DAY_MS, guard += 1) applyOutageValue(regionKey, outage.type, ms, value);
        for (let dayOffset = 1; dayOffset <= OUTAGE_RAMP_DOWN_DAYS; dayOffset += 1) {
          const rampValue = roundCapacity1(value * this.outageRampFactor(dayOffset));
          if (rampValue) applyOutageValue(regionKey, outage.type, end + dayOffset * DAY_MS, rampValue);
        }
      }
      return days;
    });
  }

  outageTotalsForPeriod(regionKey, period, frequency) {
    const days = this.outageDailyVector();
    const range = periodRange(period, frequency);
    const totals = { planned: 0, unplanned: 0, other: 0, total: 0 };
    for (let ms = range.start, guard = 0; ms <= range.end && guard < 10000; ms += DAY_MS, guard += 1) {
      const byRegion = days.get(dateKeyFromMs(ms));
      if (!byRegion) continue;
      const sourceKeys = CRUDE_AGGREGATES[regionKey] || [regionKey];
      for (const key of sourceKeys) {
        const daily = byRegion[key];
        if (!daily) continue;
        totals.planned += Number(daily.planned || 0);
        totals.unplanned += Number(daily.unplanned || 0);
        totals.other += Number(daily.other || 0);
        totals.total += Number(daily.total || 0);
      }
    }
    const divisor = Math.max(Number(range.days || 1), 1);
    return {
      planned: round3(totals.planned / divisor),
      unplanned: round3(totals.unplanned / divisor),
      other: round3(totals.other / divisor),
      total: round3(totals.total / divisor),
    };
  }

  historicalCrudeUtilizationGap(regionKey, period, frequency) {
    const rows = this.crudeRowsForRegion(regionKey, frequency);
    const targetSlot = slotOf(period, frequency);
    const seasonalRows = rows.filter((row) => row.period < period && slotOf(row.period, frequency) === targetSlot).slice(-3);
    const gaps = seasonalRows
      .map((row) => {
        const capacity = Number(row.operableCapacityKbd || 0);
        const runs = Number(row.crudeRunsKbd || 0);
        return capacity > 0 ? Math.max(0, 1 - runs / capacity) : null;
      })
      .filter(Number.isFinite);
    return Math.max(0, average(gaps) || 0);
  }

  modeledUnplannedMaintenanceKbd(regionKey, period, operableCapacityKbd, plannedMaintenanceKbd, idleCapacityKbd, frequency) {
    const exPlannedCapacity = Math.max(0, Number(operableCapacityKbd || 0) - Number(plannedMaintenanceKbd || 0));
    return Math.max(0, exPlannedCapacity * this.historicalCrudeUtilizationGap(regionKey, period, frequency) - Number(idleCapacityKbd || 0));
  }

  useHistoricalCrudeOutageEstimate(period) {
    return periodMonthValue(period) >= "2022-01";
  }

  historicalUnplannedMaintenanceKbd(operableCapacityKbd, plannedMaintenanceKbd, crudeRunsKbd) {
    return Math.max(0, Number(operableCapacityKbd || 0) - Number(plannedMaintenanceKbd || 0) - Number(crudeRunsKbd || 0));
  }

  crudeSchedulePoint(regionKey, period, bucket, isActual, frequency) {
    const actual = bucket[regionKey] || null;
    if (CRUDE_AGGREGATES[regionKey] && !(actual && isActual)) {
      const paddPoints = CRUDE_AGGREGATES[regionKey].map((key) => this.crudeSchedulePoint(key, period, bucket, isActual, frequency));
      const sum = (key) => paddPoints.reduce((total, point) => total + Number(point[key] || 0), 0);
      const operable = sum("operableCapacityKbd");
      const idle = sum("idleCapacityKbd");
      const operating = sum("operatingCapacityKbd");
      const planned = sum("plannedMaintenanceKbd");
      const unplanned = sum("unplannedMaintenanceKbd");
      const crudeRuns = Math.max(0, sum("crudeRunsKbd"));
      const grossInputs = Math.max(0, sum("grossInputsKbd"));
      const exPlannedCapacity = Math.max(0, operable - planned);
      return {
        period,
        status: "forecast",
        regionKey,
        operableCapacityKbd: round2(operable),
        idleCapacityKbd: round2(idle),
        operatingCapacityKbd: round2(operating),
        plannedMaintenanceKbd: round2(planned),
        unplannedMaintenanceKbd: round2(unplanned),
        otherMaintenanceKbd: round2(sum("otherMaintenanceKbd")),
        totalOfflineKbd: round2(planned + unplanned),
        crudeRunsKbd: round2(crudeRuns),
        grossInputsKbd: round2(grossInputs),
        utilizationPct: round2(safePct(crudeRuns, operable)),
        operatingUtilizationPct: round2(safePct(crudeRuns, operating)),
        exPlannedUtilizationPct: round2(safePct(crudeRuns, exPlannedCapacity)),
      };
    }
    const monthlyBasis = this.latestMonthlyCrudeBasis(regionKey, period);
    const basis = actual && isActual ? actual : monthlyBasis;
    const outage = this.outageTotalsForPeriod(regionKey, period, frequency);
    const month = periodMonthValue(period);
    const basisOperable = Number(basis.operableCapacityKbd || monthlyBasis.operableCapacityKbd || basis.operatingCapacityKbd || 0);
    const operable = basisOperable;
    const basisOperating = Number(basis.operatingCapacityKbd || Math.max(0, basisOperable - Number(basis.idleCapacityKbd || 0)) || 0);
    const basisIdle = actual && isActual ? Math.max(0, basisOperable - basisOperating) : 0;
    const idle = actual && isActual ? basisIdle : this.regionalCapacityRowValue(regionKey, "idleCapacityKbd", month, basisIdle);
    const operating = actual && isActual ? basisOperating : Math.max(0, operable - idle);
    const baseRuns = Number((actual && isActual ? actual.crudeRunsKbd : monthlyBasis.crudeRunsKbd) || 0);
    const blankHistoricalOutages = Boolean(actual && isActual && !this.useHistoricalCrudeOutageEstimate(period));
    const planned = blankHistoricalOutages ? null : Number(outage.planned || 0);
    const plannedForCalc = Number(planned || 0);
    const unplannedOverride = actual && isActual ? null : this.latestRegionalCapacityAdjustment(regionKey, "unplannedMaintenanceKbd", month);
    const explicitUnplanned = unplannedOverride ? Number(unplannedOverride.capacityKbd || 0) : Number(outage.unplanned || 0);
    const exPlannedCapacity = Math.max(0, operable - plannedForCalc);
    const runCeiling = Math.max(0, operating - plannedForCalc);
    const exPlannedUtilizationAdjustment = actual && isActual ? null : this.latestRegionalCapacityAdjustment(regionKey, "exPlannedUtilizationAdjustmentPct", month);
    const modeledUnplanned = this.modeledUnplannedMaintenanceKbd(regionKey, period, operable, plannedForCalc, idle, frequency);
    const targetRuns = exPlannedUtilizationAdjustment ? (exPlannedCapacity * Math.max(0, Math.min(100, Number(exPlannedUtilizationAdjustment.capacityKbd || 0)))) / 100 : null;
    const utilizationSolvedUnplanned = targetRuns !== null ? Math.max(0, runCeiling - targetRuns) : null;
    const explicitUnplannedAboveModel = explicitUnplanned > modeledUnplanned;
    const historicalUnplanned = blankHistoricalOutages ? null : this.historicalUnplannedMaintenanceKbd(operable, plannedForCalc, baseRuns);
    const unplanned = actual && isActual ? historicalUnplanned : explicitUnplannedAboveModel ? explicitUnplanned : utilizationSolvedUnplanned !== null ? utilizationSolvedUnplanned : modeledUnplanned;
    const totalOffline = planned === null && unplanned === null ? null : Number(planned || 0) + Number(unplanned || 0);
    const crudeRuns = actual && isActual ? baseRuns : Math.max(0, runCeiling - Number(unplanned || 0));
    const baseGross = Number((actual && isActual ? actual.grossInputsKbd : monthlyBasis.grossInputsKbd) || crudeRuns || baseRuns || 0);
    return {
      period,
      status: actual && isActual ? "actual" : "forecast",
      regionKey,
      operableCapacityKbd: round2(operable),
      idleCapacityKbd: round2(idle),
      operatingCapacityKbd: round2(operating),
      plannedMaintenanceKbd: planned === null ? null : round2(planned),
      unplannedMaintenanceKbd: unplanned === null ? null : round2(unplanned),
      otherMaintenanceKbd: round2(outage.other),
      totalOfflineKbd: totalOffline === null ? null : round2(totalOffline),
      crudeRunsKbd: round2(crudeRuns),
      grossInputsKbd: round2(baseGross),
      utilizationPct: round2(safePct(crudeRuns, operable)),
      operatingUtilizationPct: round2(safePct(crudeRuns, operating)),
      exPlannedUtilizationPct: round2(safePct(crudeRuns, exPlannedCapacity)),
    };
  }

  allocatedCrudeDetail(regionKey, period, rawBucket, crudeBucket, isActual, frequency, splitBucket = rawBucket) {
    const crudeRegion = this.crudeRegionForBalanceRegion(regionKey);
    const crudePoint = this.crudeSchedulePoint(crudeRegion, period, crudeBucket || {}, isActual, frequency);
    const share = crudeRegion === "padd1" ? this.padd1SplitShare(regionKey, splitBucket || rawBucket) : 1;
    const scale = (key) => round2(Number(crudePoint[key] || 0) * share);
    const scaleNullable = (key) => (crudePoint[key] === null || crudePoint[key] === undefined ? null : scale(key));
    const operableCapacityKbd = scale("operableCapacityKbd");
    const operatingCapacityKbd = scale("operatingCapacityKbd");
    const plannedMaintenanceKbd = scaleNullable("plannedMaintenanceKbd");
    const unplannedMaintenanceKbd = scaleNullable("unplannedMaintenanceKbd");
    const crudeRunsKbd = scale("crudeRunsKbd");
    const exPlannedCapacity = Math.max(0, operableCapacityKbd - Number(plannedMaintenanceKbd || 0));
    return {
      operableCapacityKbd,
      operatingCapacityKbd,
      plannedMaintenanceKbd,
      unplannedMaintenanceKbd,
      crudeRunsKbd,
      operatingUtilizationPct: round2(safePct(crudeRunsKbd, operatingCapacityKbd)),
      exPlannedUtilizationPct: round2(safePct(crudeRunsKbd, exPlannedCapacity)),
    };
  }

  padd1SplitShare(regionKey, rawBucket) {
    if (regionKey !== "padd1ab" && regionKey !== "padd1c") return 1;
    const point = rawBucket?.[regionKey] || {};
    const ab = Number(rawBucket?.padd1ab?.productionKbd || 0);
    const c = Number(rawBucket?.padd1c?.productionKbd || 0);
    const total = ab + c;
    if (total > 0) return Math.max(0, Math.min(1, Number(point.productionKbd || 0) / total));
    const demandTotal = Number(rawBucket?.padd1ab?.demandKbd || 0) + Number(rawBucket?.padd1c?.demandKbd || 0);
    if (demandTotal > 0) return Math.max(0, Math.min(1, Number(point.demandKbd || 0) / demandTotal));
    return regionKey === "padd1ab" ? 1 : 0;
  }

  seasonalYieldPct(regionKey, period, rawBuckets, crudeInfoByPeriod) {
    const month = String(monthOf(period)).padStart(2, "0");
    const years = Array.isArray(this.D.forecast?.seasonYears) && this.D.forecast.seasonYears.length ? this.D.forecast.seasonYears : [2023, 2024, 2025];
    const yields = years
      .map((year) => {
        const seasonPeriod = year + "-" + month;
        const rawBucket = rawBuckets.get(seasonPeriod);
        const rawPoint = rawBucket?.[regionKey];
        if (!rawPoint) return null;
        const crudeInfo = crudeInfoByPeriod.get(seasonPeriod) || { bucket: {}, isActual: true };
        const detail = this.allocatedCrudeDetail(regionKey, seasonPeriod, rawBucket, crudeInfo.bucket, true, "monthly");
        return detail.crudeRunsKbd > 0 ? (Number(rawPoint.productionKbd || 0) / detail.crudeRunsKbd) * 100 : null;
      })
      .filter(Number.isFinite);
    return round2(average(yields) || 0);
  }

  forceZeroExports(regionKey) {
    return this.D.product?.key === "diesel" && regionKey === "padd1c";
  }

  adjustedImportComponents(point, importsKbd) {
    const total = Math.max(0, Number(importsKbd || 0));
    const sourceCanada = Math.max(0, Number(point?.canadaImportsKbd || 0));
    const sourceNonCanada = Math.max(0, Number(point?.nonCanadaImportsKbd ?? Math.max(0, Number(point?.importsKbd || 0) - sourceCanada)));
    const sourceTotal = sourceCanada + sourceNonCanada;
    const canadaImportsKbd = sourceTotal > 0 ? round2(Math.min(total, (total * sourceCanada) / sourceTotal)) : 0;
    return { canadaImportsKbd, nonCanadaImportsKbd: round2(Math.max(0, total - canadaImportsKbd)) };
  }

  adjustedImportValues(point, importsKbd, frequency, period, regionKey, isActual) {
    const base = this.adjustedImportComponents(point, importsKbd);
    if (isActual || frequency === "weekly" || regionKey !== "padd1ab") return { importsKbd: round2(importsKbd), ...base };
    let canadaImportsKbd = base.canadaImportsKbd;
    let nonCanadaImportsKbd = base.nonCanadaImportsKbd;
    const canadaOverride = this.balanceAdjustmentValue(frequency, period, regionKey, "canadaImports");
    const nonCanadaOverride = this.balanceAdjustmentValue(frequency, period, regionKey, "nonCanadaImports");
    if (canadaOverride !== null) canadaImportsKbd = round2(canadaOverride);
    if (nonCanadaOverride !== null) nonCanadaImportsKbd = round2(nonCanadaOverride);
    return { importsKbd: round2(canadaImportsKbd + nonCanadaImportsKbd), canadaImportsKbd, nonCanadaImportsKbd };
  }

  adjustedExportDestinationValues(point, exportsKbd) {
    const total = Math.max(0, Number(exportsKbd || 0));
    const base = EXPORT_DESTINATION_FIELDS.map((key) => Math.max(0, Number(point?.[key] || 0)));
    const baseTotal = base.reduce((sum, value) => sum + value, 0);
    const values = {};
    if (baseTotal <= 0) {
      EXPORT_DESTINATION_FIELDS.forEach((key, index) => {
        values[key] = index === EXPORT_DESTINATION_FIELDS.length - 1 ? round2(total) : 0;
      });
      return values;
    }
    EXPORT_DESTINATION_FIELDS.forEach((key, index) => {
      values[key] = round2((total * base[index]) / baseTotal);
    });
    const drift = round2(total - EXPORT_DESTINATION_FIELDS.reduce((sum, key) => sum + Number(values[key] || 0), 0));
    values.exportsOtherKbd = round2(Math.max(0, Number(values.exportsOtherKbd || 0) + drift));
    return values;
  }

  exportDestinationTotal(values) {
    return round2(EXPORT_DESTINATION_FIELDS.reduce((sum, key) => sum + Number(values?.[key] || 0), 0));
  }

  adjustedPadd3ExportDestinationValues(point, frequency, period, isActual) {
    const values = {};
    EXPORT_DESTINATION_FIELDS.forEach((key) => {
      values[key] = round2(Math.max(0, Number(point?.[key] || 0)));
    });
    if (!isActual) {
      EXPORT_DESTINATION_FIELDS.forEach((key) => {
        const override = this.balanceAdjustmentValue(frequency, period, "padd3", EXPORT_DESTINATION_LINE_BY_FIELD[key]);
        if (override !== null) values[key] = round2(override);
      });
    }
    return values;
  }

  adjustedBaseMonthlyPoint(rawPoint, rawBucket, crudeInfo, rawBuckets, crudeInfoByPeriod, priorPoint) {
    const isActual = rawPoint.status === "actual";
    const detail = this.allocatedCrudeDetail(rawPoint.regionKey, rawPoint.period, rawBucket, crudeInfo?.bucket || {}, isActual, "monthly");
    let yieldPct = isActual ? round2(detail.crudeRunsKbd > 0 ? (Number(rawPoint.productionKbd || 0) / detail.crudeRunsKbd) * 100 : 0) : this.seasonalYieldPct(rawPoint.regionKey, rawPoint.period, rawBuckets, crudeInfoByPeriod);
    const yieldAdjustmentPct = isActual ? null : this.balanceAdjustmentValue("monthly", rawPoint.period, rawPoint.regionKey, "yieldAdjustmentPct");
    if (yieldAdjustmentPct !== null) yieldPct = round2(yieldAdjustmentPct);
    let productionKbd = isActual ? Number(rawPoint.productionKbd || 0) : round2((detail.crudeRunsKbd * yieldPct) / 100);
    const productionOverride = isActual ? null : this.balanceAdjustmentValue("monthly", rawPoint.period, rawPoint.regionKey, "production");
    if (!isActual) productionKbd = round2(productionOverride === null ? productionKbd : productionOverride);
    if (!isActual && productionOverride !== null) yieldPct = round2(safePct(productionKbd, detail.crudeRunsKbd));
    const demandKbd = isActual ? Number(rawPoint.demandKbd || 0) : round2(this.applyBalanceAdjustment(Number(rawPoint.demandKbd || 0), "monthly", rawPoint.period, rawPoint.regionKey, "demand"));
    let importsKbd = Number(rawPoint.importsKbd || 0);
    if (!isActual && rawPoint.regionKey !== "padd1ab") importsKbd = round2(this.applyBalanceAdjustment(importsKbd, "monthly", rawPoint.period, rawPoint.regionKey, "imports"));
    const importValues = this.adjustedImportValues(rawPoint, importsKbd, "monthly", rawPoint.period, rawPoint.regionKey, isActual);
    importsKbd = importValues.importsKbd;
    const exportsOverride = isActual ? null : this.balanceAdjustmentValue("monthly", rawPoint.period, rawPoint.regionKey, "exports");
    let exportsKbd = this.forceZeroExports(rawPoint.regionKey) && exportsOverride === null ? 0 : isActual ? Number(rawPoint.exportsKbd || 0) : round2(exportsOverride === null ? Number(rawPoint.exportsKbd || 0) : exportsOverride);
    let exportDestinationValues = this.adjustedExportDestinationValues(rawPoint, exportsKbd);
    if (this.forceZeroExports(rawPoint.regionKey) && exportsOverride === null) exportDestinationValues = this.adjustedExportDestinationValues(rawPoint, 0);
    if (rawPoint.regionKey === "padd3") {
      exportDestinationValues = isActual ? this.adjustedExportDestinationValues(rawPoint, exportsKbd) : this.adjustedPadd3ExportDestinationValues(rawPoint, "monthly", rawPoint.period, isActual);
      if (!isActual) exportsKbd = this.exportDestinationTotal(exportDestinationValues);
    }
    const movement = this.movementSummaryForRegion("monthly", rawPoint.period, rawPoint.regionKey);
    const receiptsKbd = movement.hasFlows ? movement.receiptsKbd : null;
    const shipmentsKbd = movement.hasFlows ? movement.shipmentsKbd : null;
    const netReceiptsKbd = movement.hasFlows ? movement.netReceiptsKbd : Number(rawPoint.netReceiptsKbd || 0);
    const balanceKbd = round2(productionKbd + importsKbd + netReceiptsKbd - exportsKbd - demandKbd);
    const stocksKb = isActual ? Number(rawPoint.stocksKb || 0) : round2(Number(priorPoint?.stocksKb || rawPoint.stocksKb || 0) + balanceKbd * periodDays(rawPoint.period));
    return { ...rawPoint, ...detail, yieldPct, yieldAdjustmentPct, demandKbd, productionKbd, ...importValues, exportsKbd, ...exportDestinationValues, netReceiptsKbd, receiptsKbd, shipmentsKbd, stockChangeKbd: isActual ? Number(rawPoint.stockChangeKbd || 0) : balanceKbd, balanceKbd, stocksKb };
  }

  adjustedBaseWeeklyPoint(rawPoint, rawBucket, monthlyBucket, crudeInfo, priorPoint) {
    const isActual = rawPoint.status === "actual";
    const monthlyActualPoint = monthlyBucket?.[rawPoint.regionKey] || null;
    const monthlyPoint = monthlyActualPoint || rawPoint;
    const detail = this.allocatedCrudeDetail(rawPoint.regionKey, rawPoint.period, rawBucket, crudeInfo?.bucket || {}, isActual, "weekly", monthlyBucket || rawBucket);
    let yieldPct = isActual ? round2(safePct(Number(rawPoint.productionKbd || 0), detail.crudeRunsKbd)) : Number(monthlyPoint.yieldPct || 0);
    const yieldAdjustmentPct = isActual ? null : this.balanceAdjustmentValue("weekly", rawPoint.period, rawPoint.regionKey, "yieldAdjustmentPct");
    if (yieldAdjustmentPct !== null) yieldPct = round2(yieldAdjustmentPct);
    let productionKbd = isActual ? Number(rawPoint.productionKbd || 0) : round2((detail.crudeRunsKbd * yieldPct) / 100);
    const productionOverride = isActual ? null : this.balanceAdjustmentValue("weekly", rawPoint.period, rawPoint.regionKey, "production");
    if (!isActual) productionKbd = round2(productionOverride === null ? productionKbd : productionOverride);
    if (!isActual && productionOverride !== null) yieldPct = round2(safePct(productionKbd, detail.crudeRunsKbd));
    let demandKbd = isActual ? Number(rawPoint.demandKbd || 0) : round2(this.applyBalanceAdjustment(Number(monthlyPoint.demandKbd ?? rawPoint.demandKbd ?? 0), "weekly", rawPoint.period, rawPoint.regionKey, "demand"));
    let importsKbd = Number(monthlyPoint.importsKbd ?? rawPoint.importsKbd ?? 0);
    if (isActual) importsKbd = Number(rawPoint.importsKbd || 0);
    else importsKbd = round2(this.applyBalanceAdjustment(Number(rawPoint.importsKbd ?? monthlyPoint.importsKbd ?? 0), "weekly", rawPoint.period, rawPoint.regionKey, "imports"));
    const importValues = this.adjustedImportValues(monthlyPoint || rawPoint, importsKbd, "weekly", rawPoint.period, rawPoint.regionKey, isActual);
    importsKbd = importValues.importsKbd;
    const exportsOverride = isActual ? null : this.balanceAdjustmentValue("weekly", rawPoint.period, rawPoint.regionKey, "exports");
    let exportsKbd = this.forceZeroExports(rawPoint.regionKey) && exportsOverride === null ? 0 : isActual ? Number(rawPoint.exportsKbd || 0) : round2(exportsOverride === null ? Number(rawPoint.exportsKbd ?? monthlyPoint.exportsKbd ?? 0) : exportsOverride);
    let exportDestinationValues = this.adjustedExportDestinationValues(rawPoint || monthlyPoint, exportsKbd);
    if (this.forceZeroExports(rawPoint.regionKey) && exportsOverride === null) exportDestinationValues = this.adjustedExportDestinationValues(rawPoint || monthlyPoint, 0);
    if (rawPoint.regionKey === "padd3") {
      exportDestinationValues = isActual ? this.adjustedExportDestinationValues(rawPoint || monthlyPoint, exportsKbd) : this.adjustedPadd3ExportDestinationValues(rawPoint || monthlyPoint, "weekly", rawPoint.period, isActual);
      if (!isActual) exportsKbd = this.exportDestinationTotal(exportDestinationValues);
    }
    const movement = this.movementSummaryForRegion("weekly", rawPoint.period, rawPoint.regionKey);
    const receiptsKbd = movement.hasFlows ? movement.receiptsKbd : null;
    const shipmentsKbd = movement.hasFlows ? movement.shipmentsKbd : null;
    const netReceiptsKbd = movement.hasFlows ? movement.netReceiptsKbd : Number(monthlyPoint.netReceiptsKbd ?? rawPoint.netReceiptsKbd ?? 0);
    if (isActual && monthlyActualPoint?.status !== "actual") demandKbd = round2(productionKbd + importsKbd + netReceiptsKbd - exportsKbd - Number(rawPoint.stockChangeKbd || 0));
    const balanceKbd = round2(productionKbd + importsKbd + netReceiptsKbd - exportsKbd - demandKbd);
    const stocksKb = isActual ? Number(rawPoint.stocksKb || 0) : round2(Number(priorPoint?.stocksKb || rawPoint.stocksKb || monthlyPoint.stocksKb || 0) + balanceKbd * periodDays(rawPoint.period));
    return { ...rawPoint, ...detail, yieldPct, yieldAdjustmentPct, demandKbd, productionKbd, ...importValues, exportsKbd, ...exportDestinationValues, netReceiptsKbd, receiptsKbd, shipmentsKbd, stockChangeKbd: isActual ? Number(rawPoint.stockChangeKbd || 0) : balanceKbd, balanceKbd, stocksKb };
  }

  aggregatePoint(period, regionKey, parts, frequency) {
    const status = parts.some((point) => point.status === "forecast") ? "forecast" : "actual";
    const sum = (key) => parts.reduce((total, point) => total + Number(point[key] || 0), 0);
    const nullableSum = (key) => (parts.every((point) => point[key] === null || point[key] === undefined) ? null : round2(sum(key)));
    const productionKbd = sum("productionKbd");
    const importsKbd = sum("importsKbd");
    const canadaImportsKbd = sum("canadaImportsKbd");
    const nonCanadaImportsKbd = sum("nonCanadaImportsKbd");
    const movement = this.movementSummaryForRegion(frequency, period, regionKey);
    const receiptsKbd = movement.hasFlows ? movement.receiptsKbd : sum("receiptsKbd");
    const shipmentsKbd = movement.hasFlows ? movement.shipmentsKbd : sum("shipmentsKbd");
    const netReceiptsKbd = movement.hasFlows ? movement.netReceiptsKbd : sum("netReceiptsKbd");
    const exportsKbd = sum("exportsKbd");
    const exportsLatinAmericaKbd = sum("exportsLatinAmericaKbd");
    const exportsEuropeKbd = sum("exportsEuropeKbd");
    const exportsAfricaKbd = sum("exportsAfricaKbd");
    const exportsOtherKbd = sum("exportsOtherKbd");
    const demandKbd = sum("demandKbd");
    const operableCapacityKbd = sum("operableCapacityKbd");
    const operatingCapacityKbd = sum("operatingCapacityKbd");
    const plannedMaintenanceKbd = nullableSum("plannedMaintenanceKbd");
    const unplannedMaintenanceKbd = nullableSum("unplannedMaintenanceKbd");
    const crudeRunsKbd = sum("crudeRunsKbd");
    const exPlannedCapacity = Math.max(0, operableCapacityKbd - Number(plannedMaintenanceKbd || 0));
    return {
      period,
      status,
      regionKey,
      demandKbd: round2(demandKbd),
      productionKbd: round2(productionKbd),
      importsKbd: round2(importsKbd),
      canadaImportsKbd: round2(canadaImportsKbd),
      nonCanadaImportsKbd: round2(nonCanadaImportsKbd),
      exportsKbd: round2(exportsKbd),
      exportsLatinAmericaKbd: round2(exportsLatinAmericaKbd),
      exportsEuropeKbd: round2(exportsEuropeKbd),
      exportsAfricaKbd: round2(exportsAfricaKbd),
      exportsOtherKbd: round2(exportsOtherKbd),
      netReceiptsKbd: round2(netReceiptsKbd),
      receiptsKbd: round2(receiptsKbd),
      shipmentsKbd: round2(shipmentsKbd),
      stockChangeKbd: round2(sum("stockChangeKbd")),
      stocksKb: round2(sum("stocksKb")),
      balanceKbd: round2(productionKbd + importsKbd + netReceiptsKbd - exportsKbd - demandKbd),
      operableCapacityKbd: round2(operableCapacityKbd),
      operatingCapacityKbd: round2(operatingCapacityKbd),
      plannedMaintenanceKbd,
      unplannedMaintenanceKbd,
      crudeRunsKbd: round2(crudeRunsKbd),
      operatingUtilizationPct: round2(safePct(crudeRunsKbd, operatingCapacityKbd)),
      exPlannedUtilizationPct: round2(safePct(crudeRunsKbd, exPlannedCapacity)),
      yieldPct: round2(safePct(productionKbd, crudeRunsKbd)),
      yieldAdjustmentPct: null,
    };
  }

  adjustedMonthlyActualBaseline() {
    return this.cached("adjustedMonthlyActualBaseline", () => {
      const rawBuckets = this.rawBuckets("monthly");
      const crudeInfoByPeriod = this.crudeInfoIndex("monthly");
      const priorByRegion = new Map();
      const out = [];
      for (const period of Array.from(rawBuckets.keys()).sort()) {
        const rawBucket = rawBuckets.get(period) || {};
        if (Object.values(rawBucket).some((row) => row?.status === "forecast")) continue;
        const crudeInfo = crudeInfoByPeriod.get(period) || { bucket: {}, isActual: true };
        const adjusted = new Map();
        for (const regionKey of this.baseRegions) {
          const rawPoint = rawBucket[regionKey];
          if (!rawPoint) continue;
          const point = this.adjustedBaseMonthlyPoint(rawPoint, rawBucket, crudeInfo, rawBuckets, crudeInfoByPeriod, priorByRegion.get(regionKey));
          adjusted.set(regionKey, point);
          priorByRegion.set(regionKey, point);
        }
        for (const [regionKey, keys] of Object.entries(this.aggregates)) {
          const parts = keys.map((key) => adjusted.get(key)).filter(Boolean);
          if (parts.length === keys.length) adjusted.set(regionKey, this.aggregatePoint(period, regionKey, parts, "monthly"));
        }
        for (const region of this.D.regionalBalance.regions) {
          const point = adjusted.get(region.key);
          if (point) out.push(point);
        }
      }
      return { rows: out, buckets: this.bucketRows(out), priorByRegion: new Map(priorByRegion) };
    });
  }

  adjustedMonthlyBalanceRows() {
    return this.cached("adjustedMonthlyBalanceRows", () => {
      const actualBaseline = this.adjustedMonthlyActualBaseline();
      const rawBuckets = this.rawBuckets("monthly");
      const crudeInfoByPeriod = this.crudeInfoIndex("monthly");
      const priorByRegion = new Map(actualBaseline.priorByRegion);
      const out = actualBaseline.rows.slice();
      for (const period of Array.from(rawBuckets.keys()).sort()) {
        const rawBucket = rawBuckets.get(period) || {};
        if (!Object.values(rawBucket).some((row) => row?.status === "forecast")) continue;
        const crudeInfo = crudeInfoByPeriod.get(period) || { bucket: {}, isActual: false };
        const adjusted = new Map();
        for (const regionKey of this.baseRegions) {
          const rawPoint = rawBucket[regionKey];
          if (!rawPoint) continue;
          const point = this.adjustedBaseMonthlyPoint(rawPoint, rawBucket, crudeInfo, rawBuckets, crudeInfoByPeriod, priorByRegion.get(regionKey));
          adjusted.set(regionKey, point);
          priorByRegion.set(regionKey, point);
        }
        for (const [regionKey, keys] of Object.entries(this.aggregates)) {
          const parts = keys.map((key) => adjusted.get(key)).filter(Boolean);
          if (parts.length === keys.length) adjusted.set(regionKey, this.aggregatePoint(period, regionKey, parts, "monthly"));
        }
        for (const region of this.D.regionalBalance.regions) {
          const point = adjusted.get(region.key);
          if (point) out.push(point);
        }
      }
      this.applyDaysForwardCover(out, "monthly");
      return out;
    });
  }

  adjustedWeeklyActualBaseline() {
    return this.cached("adjustedWeeklyActualBaseline", () => {
      const rawBuckets = this.rawBuckets("weekly");
      const monthlyBuckets = this.adjustedMonthlyActualBaseline().buckets;
      const crudeInfoByPeriod = this.crudeInfoIndex("weekly");
      const priorByRegion = new Map();
      const out = [];
      for (const period of Array.from(rawBuckets.keys()).sort()) {
        const rawBucket = rawBuckets.get(period) || {};
        if (Object.values(rawBucket).some((row) => row?.status === "forecast")) continue;
        const monthlyBucket = monthlyBuckets.get(periodMonthValue(period)) || {};
        const crudeInfo = crudeInfoByPeriod.get(period) || { bucket: {}, isActual: true };
        const adjusted = new Map();
        for (const regionKey of this.baseRegions) {
          const rawPoint = rawBucket[regionKey];
          if (!rawPoint) continue;
          const point = this.adjustedBaseWeeklyPoint(rawPoint, rawBucket, monthlyBucket, crudeInfo, priorByRegion.get(regionKey));
          adjusted.set(regionKey, point);
          priorByRegion.set(regionKey, point);
        }
        for (const [regionKey, keys] of Object.entries(this.aggregates)) {
          const parts = keys.map((key) => adjusted.get(key)).filter(Boolean);
          if (parts.length === keys.length) adjusted.set(regionKey, this.aggregatePoint(period, regionKey, parts, "weekly"));
        }
        for (const region of this.D.regionalBalance.regions) {
          const point = adjusted.get(region.key);
          if (point) out.push(point);
        }
      }
      return { rows: out, buckets: this.bucketRows(out), priorByRegion: new Map(priorByRegion) };
    });
  }

  adjustedWeeklyBalanceRows() {
    return this.cached("adjustedWeeklyBalanceRows", () => {
      const actualBaseline = this.adjustedWeeklyActualBaseline();
      const rawBuckets = this.rawBuckets("weekly");
      const monthlyBuckets = this.bucketRows(this.adjustedMonthlyBalanceRows());
      const crudeInfoByPeriod = this.crudeInfoIndex("weekly");
      const priorByRegion = new Map(actualBaseline.priorByRegion);
      const out = actualBaseline.rows.slice();
      for (const period of Array.from(rawBuckets.keys()).sort()) {
        const rawBucket = rawBuckets.get(period) || {};
        if (!Object.values(rawBucket).some((row) => row?.status === "forecast")) continue;
        const monthlyBucket = monthlyBuckets.get(periodMonthValue(period)) || {};
        const crudeInfo = crudeInfoByPeriod.get(period) || { bucket: {}, isActual: false };
        const adjusted = new Map();
        for (const regionKey of this.baseRegions) {
          const rawPoint = rawBucket[regionKey];
          if (!rawPoint) continue;
          const point = this.adjustedBaseWeeklyPoint(rawPoint, rawBucket, monthlyBucket, crudeInfo, priorByRegion.get(regionKey));
          adjusted.set(regionKey, point);
          priorByRegion.set(regionKey, point);
        }
        for (const [regionKey, keys] of Object.entries(this.aggregates)) {
          const parts = keys.map((key) => adjusted.get(key)).filter(Boolean);
          if (parts.length === keys.length) adjusted.set(regionKey, this.aggregatePoint(period, regionKey, parts, "weekly"));
        }
        for (const region of this.D.regionalBalance.regions) {
          const point = adjusted.get(region.key);
          if (point) out.push(point);
        }
      }
      this.applyDaysForwardCover(out, "weekly");
      return out;
    });
  }

  applyDaysForwardCover(rows, frequency) {
    const lookahead = frequency === "weekly" ? 8 : 2;
    const byRegion = new Map();
    for (const row of rows) {
      if (!row?.regionKey || !row.period) continue;
      const list = byRegion.get(row.regionKey) || [];
      list.push(row);
      byRegion.set(row.regionKey, list);
    }
    for (const list of byRegion.values()) {
      list.sort((a, b) => String(a.period).localeCompare(String(b.period)));
      const demand = list.map((point) => Number(point?.demandKbd));
      let sum = 0;
      let valid = 0;
      for (let index = 0; index < list.length; index += 1) {
        if (index === 0) {
          for (let offset = 1; offset <= lookahead && offset < list.length; offset += 1) {
            const value = demand[offset];
            if (Number.isFinite(value)) {
              sum += value;
              valid += 1;
            }
          }
        } else {
          const leaving = demand[index];
          if (Number.isFinite(leaving)) {
            sum -= leaving;
            valid -= 1;
          }
          const entering = demand[index + lookahead];
          if (Number.isFinite(entering)) {
            sum += entering;
            valid += 1;
          }
        }
        const avgDemand = valid === lookahead ? sum / lookahead : null;
        list[index].daysForwardCover = Number.isFinite(avgDemand) && avgDemand > 0 ? round2(Number(list[index].stocksKb || 0) / avgDemand) : NaN;
      }
    }
  }

  pointReceiptTotal(point) {
    if (!point) return 0;
    if (point.receiptsKbd !== null && point.receiptsKbd !== undefined && Number.isFinite(Number(point.receiptsKbd))) return Number(point.receiptsKbd || 0);
    return Math.max(Number(point.netReceiptsKbd || 0), 0);
  }

  pointShipmentTotal(point) {
    if (!point) return 0;
    if (point.shipmentsKbd !== null && point.shipmentsKbd !== undefined && Number.isFinite(Number(point.shipmentsKbd))) return Number(point.shipmentsKbd || 0);
    return Math.max(-Number(point.netReceiptsKbd || 0), 0);
  }

  totals(point, frequency) {
    const receipts = this.pointReceiptTotal(point);
    const shipments = this.pointShipmentTotal(point);
    const supply = Number(point.productionKbd || 0) + Number(point.importsKbd || 0) + receipts;
    const demand = Number(point.demandKbd || 0) + Number(point.exportsKbd || 0) + shipments;
    const daily = supply - demand;
    const total = frequency === "weekly" && point.status === "actual" ? Number(point.stockChangeKbd || 0) * periodDays(point.period || "") : daily * periodDays(point.period || "");
    return { receipts, shipments, supply, demand, daily, total };
  }

  valueForLine(point, lineId, frequency, regionKey = point?.regionKey) {
    if (!point) return null;
    const totals = this.totals(point, frequency);
    if (isReceiptFlowLine(lineId)) return this.movementFlowValue(frequency, point.period, String(lineId).replace(/^receipt:/, ""));
    if (lineId === "demand") return point.demandKbd;
    if (lineId === "imports") return frequency === "monthly" && regionKey === "padd1ab" ? Number(point.canadaImportsKbd || 0) + Number(point.nonCanadaImportsKbd || 0) : point.importsKbd;
    if (lineId === "canadaImports") return point.canadaImportsKbd || 0;
    if (lineId === "nonCanadaImports") return point.nonCanadaImportsKbd || 0;
    if (lineId === "exports") return frequency === "monthly" && regionKey === "padd3" ? this.exportDestinationTotal(point) : point.exportsKbd;
    if (lineId === "exportsLatinAmerica") return point.exportsLatinAmericaKbd || 0;
    if (lineId === "exportsEurope") return point.exportsEuropeKbd || 0;
    if (lineId === "exportsAfrica") return point.exportsAfricaKbd || 0;
    if (lineId === "exportsOther") return point.exportsOtherKbd || 0;
    if (lineId === "yieldPct") return point.yieldPct;
    if (lineId === "totalSupply") return totals.supply;
    if (lineId === "totalDemand") return totals.demand;
    if (lineId === "buildDaily") return totals.daily;
    if (lineId === "buildTotal") return totals.total;
    return point[lineId];
  }
}

function rowKey(row) {
  return `${row.period}|${row.regionKey}`;
}

function indexRows(rows) {
  return new Map(rows.map((row) => [rowKey(row), row]));
}

function changedCells(beforeRows, afterRows) {
  const before = indexRows(beforeRows);
  const after = indexRows(afterRows);
  const changes = [];
  for (const [key, afterRow] of after.entries()) {
    const beforeRow = before.get(key);
    if (!beforeRow) continue;
    for (const field of DIFF_FIELDS) {
      const left = beforeRow[field];
      const right = afterRow[field];
      if (left === undefined && right === undefined) continue;
      if (!near(left, right)) changes.push({ period: afterRow.period, regionKey: afterRow.regionKey, field, before: left, after: right, delta: round3(Number(right || 0) - Number(left || 0)) });
    }
  }
  return changes;
}

function firstForecastPoint(calc, frequency, regionKey) {
  return calc.rowsByRegion(regionKey, frequency).find((row) => row.status === "forecast");
}

function firstForecastPeriod(calc, frequency) {
  return Array.from(new Set(calc.rowsForFrequency(frequency).filter((row) => row.status === "forecast").map((row) => row.period))).sort()[0] || "";
}

function firstForecastColumnPoint(calc, frequency, period, regionKey) {
  return calc.rowsForFrequency(frequency).find((row) => row.period === period && row.regionKey === regionKey && row.status === "forecast") || null;
}

function displayTargetLineId(lineId) {
  const target = adjustmentTargetLineId(lineId);
  return target === "yieldAdjustmentPct" ? "yieldPct" : target;
}

function importAdjustmentLinesForUi(runtime, frequency, regionKey) {
  const product = runtime.product?.key || "";
  if (product === "diesel" && regionKey === "padd1ab") {
    return frequency === "monthly" ? ["canadaImportsAdjustment", "nonCanadaImportsAdjustment"] : ["importsAdjustment"];
  }
  if (product === "jet" && regionKey === "padd1") return frequency === "weekly" ? ["importsAdjustment"] : [];
  const monthlyLowerAtlanticImportGuide = frequency === "monthly" && product === "diesel" && regionKey === "padd1c";
  return frequency === "weekly" || monthlyLowerAtlanticImportGuide ? ["importsAdjustment"] : [];
}

function exportGuideFlowsForUi(runtime, regionKey) {
  const product = runtime.product?.key || "";
  if (product === "diesel" && regionKey === "padd1ab") return ["padd1abExportsEurope", "padd1abExportsOther", "padd1abExportsTotal"];
  if (product === "diesel" && regionKey === "padd1c") return ["padd1cExports"];
  if (product === "jet" && regionKey === "padd1") return ["padd1Exports"];
  if (regionKey === "padd5") return ["padd5Exports"];
  return [];
}

function exportAdjustmentLinesForUi(runtime, calc, regionKey) {
  if (regionKey === "padd3") {
    const rows = ["exportsLatinAmericaAdjustment", "exportsEuropeAdjustment"];
    if (runtime.product?.key === "diesel") rows.push("exportsAfricaAdjustment");
    rows.push("exportsOtherAdjustment");
    return rows;
  }
  return !calc.forceZeroExports(regionKey) || exportGuideFlowsForUi(runtime, regionKey).length ? ["exportsAdjustment"] : [];
}

function receiptAdjustmentLinesForColumn(runtime, frequency, period, regionKey) {
  return (runtime.regionalBalance.movementFlows || [])
    .filter((flow) => flow.toRegionKey === regionKey)
    .filter((flow) => (flow[frequency] || []).some((row) => row.period === period && row.status === "forecast" && Number.isFinite(Number(row.valueKbd))))
    .map((flow) => ({ lineId: receiptAdjustmentLineId(flow.id), flowId: flow.id, targetLine: receiptLineId(flow.id) }));
}

function syntheticColumnValue(calc, point, frequency, regionKey, lineId, targetLine, ordinal) {
  const current = Number(calc.valueForLine(point, targetLine, frequency, regionKey) || 0);
  if (targetLine === "yieldPct") {
    const delta = 1.35 + (ordinal % 5) * 0.17;
    return current > 92 ? round3(Math.max(0, current - delta)) : round3(Math.min(99, current + delta));
  }
  return round3(Math.max(0, current) + 7.5 + (ordinal % 17) * 0.713);
}

function makeColumnTests(runtime, calc) {
  const tests = [];
  for (const frequency of ["monthly", "weekly"]) {
    const period = firstForecastPeriod(calc, frequency);
    if (!period) throw new Error(`${runtime.product.key} ${frequency} has no forecast period`);
    let ordinal = 0;
    for (const regionKey of calc.baseRegions) {
      const point = firstForecastColumnPoint(calc, frequency, period, regionKey);
      if (!point) continue;
      const directLines = [
        "yieldAdjustmentPct",
        ...importAdjustmentLinesForUi(runtime, frequency, regionKey),
        ...exportAdjustmentLinesForUi(runtime, calc, regionKey),
        "demandAdjustment",
      ];
      for (const lineId of directLines) {
        const targetLine = displayTargetLineId(lineId);
        const isDestination = ["exportsLatinAmerica", "exportsEurope", "exportsAfrica", "exportsOther"].includes(targetLine);
        tests.push({
          kind: isDestination ? "destination" : "direct",
          name: "first forecast column editable row",
          scope: "column",
          frequency,
          regionKey,
          period,
          lineId,
          targetLine,
          value: syntheticColumnValue(calc, point, frequency, regionKey, lineId, targetLine, ordinal++),
        });
      }
      for (const receipt of receiptAdjustmentLinesForColumn(runtime, frequency, period, regionKey)) {
        tests.push({
          kind: "receipt",
          name: "first forecast column receipt row",
          scope: "column",
          frequency,
          regionKey,
          period,
          flowId: receipt.flowId,
          lineId: receipt.lineId,
          targetLine: receipt.targetLine,
          value: syntheticColumnValue(calc, point, frequency, regionKey, receipt.lineId, receipt.targetLine, ordinal++),
        });
      }
    }
  }
  return tests;
}

function dedupeTests(tests) {
  const seen = new Set();
  const out = [];
  for (const test of tests) {
    const key = [test.frequency, test.period, test.regionKey, test.lineId].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(test);
  }
  return out;
}

function containingRegions(calc, regionKey) {
  return Object.entries(calc.aggregates)
    .filter(([, members]) => members.includes(regionKey))
    .map(([key]) => key);
}

function affectedRegionsForCase(calc, test) {
  if (test.kind === "receipt") {
    const flow = calc.movementById.get(test.flowId);
    const base = new Set([flow.fromRegionKey, flow.toRegionKey]);
    for (const region of [flow.fromRegionKey, flow.toRegionKey]) containingRegions(calc, region).forEach((key) => base.add(key));
    return base;
  }
  return new Set([test.regionKey, ...containingRegions(calc, test.regionKey)]);
}

function assertFormulaInvariants(calc, frequency, rows, label) {
  const failures = [];
  const byKey = indexRows(rows);
  for (const row of rows) {
    const expectedBalance = round2(Number(row.productionKbd || 0) + Number(row.importsKbd || 0) + Number(row.netReceiptsKbd || 0) - Number(row.exportsKbd || 0) - Number(row.demandKbd || 0));
    if (!near(row.balanceKbd, expectedBalance)) {
      failures.push(`${label}: ${frequency} ${row.period} ${row.regionKey} balanceKbd=${row.balanceKbd} expected ${expectedBalance}`);
    }
    if (row.status === "forecast" && !near(row.stockChangeKbd, row.balanceKbd)) {
      failures.push(`${label}: ${frequency} ${row.period} ${row.regionKey} stockChangeKbd=${row.stockChangeKbd} expected balance ${row.balanceKbd}`);
    }
    if (row.status === "forecast") {
      const previous = rows
        .filter((candidate) => candidate.regionKey === row.regionKey && candidate.period < row.period)
        .sort((a, b) => a.period.localeCompare(b.period))
        .at(-1);
      if (previous) {
        const expectedStocks = round2(Number(previous.stocksKb || 0) + Number(row.balanceKbd || 0) * periodDays(row.period));
        if (!near(row.stocksKb, expectedStocks, 0.11)) failures.push(`${label}: ${frequency} ${row.period} ${row.regionKey} stocksKb=${row.stocksKb} expected ${expectedStocks}`);
      }
    }
    const members = calc.aggregates[row.regionKey];
    if (members) {
      for (const field of SUM_FIELDS) {
        const memberRows = members.map((member) => byKey.get(`${row.period}|${member}`)).filter(Boolean);
        if (memberRows.length !== members.length) continue;
        const expected = round2(memberRows.reduce((sum, memberRow) => sum + Number(memberRow[field] || 0), 0));
        if (!near(row[field], expected, 0.03)) failures.push(`${label}: ${frequency} ${row.period} ${row.regionKey}.${field}=${row[field]} expected member sum ${expected}`);
      }
    }
  }
  return failures;
}

function replacementAdjustments(runtime, calc, adjustment) {
  const normalized = normalizeBalanceAdjustment(adjustment, calc.baseRegions);
  const existing = runtime.settings?.adjustments || [];
  const aliases = balanceAdjustmentAliases(normalized.lineId);
  const kept = existing.filter((row) => !(row.frequency === normalized.frequency && row.period === normalized.period && row.regionKey === normalized.regionKey && aliases.includes(normalizeBalanceLineId(row.lineId))));
  return [...kept, normalized];
}

function runtimeWithAdjustments(runtime, calc, adjustment) {
  const next = clone(runtime);
  next.settings.adjustments = replacementAdjustments(runtime, calc, adjustment);
  return next;
}

function runtimeWithAdjustmentList(runtime, calc, adjustments) {
  const next = clone(runtime);
  for (const adjustment of adjustments) {
    next.settings.adjustments = replacementAdjustments(next, calc, adjustment);
  }
  return next;
}

function makeStandardTests(runtime) {
  const calc = new Calculator(runtime);
  const tests = [];
  for (const frequency of ["monthly", "weekly"]) {
    const regionKey = calc.baseRegions.includes("padd2") ? "padd2" : calc.baseRegions[0];
    const point = firstForecastPoint(calc, frequency, regionKey);
    if (!point) throw new Error(`${runtime.product.key} ${frequency} has no forecast point for ${regionKey}`);
    tests.push({ kind: "direct", name: "demand adjustment", frequency, regionKey, period: point.period, lineId: "demandAdjustment", targetLine: "demand", value: round3(Number(point.demandKbd || 0) + 17.321) });
    tests.push({ kind: "direct", name: "imports adjustment", frequency, regionKey, period: point.period, lineId: "importsAdjustment", targetLine: "imports", value: round3(Number(point.importsKbd || 0) + 13.217) });
    const yieldTarget = Number(point.yieldPct || 0) > 92 ? round3(Number(point.yieldPct || 0) - 2.25) : round3(Number(point.yieldPct || 0) + 2.25);
    tests.push({ kind: "direct", name: "yield adjustment", frequency, regionKey, period: point.period, lineId: "yieldAdjustmentPct", targetLine: "yieldPct", value: yieldTarget });

    const p3 = firstForecastPoint(calc, frequency, "padd3");
    if (p3) {
      tests.push({ kind: "destination", name: "PADD 3 Europe export destination adjustment", frequency, regionKey: "padd3", period: p3.period, lineId: "exportsEuropeAdjustment", targetLine: "exportsEurope", value: round3(Number(p3.exportsEuropeKbd || 0) + 19.875) });
    }

    const receipt = (runtime.regionalBalance.movementFlows || []).find((flow) => {
      if (!calc.baseRegions.includes(flow.toRegionKey) || !calc.baseRegions.includes(flow.fromRegionKey)) return false;
      return (flow[frequency] || []).some((row) => row.status === "forecast" && Number.isFinite(Number(row.valueKbd)));
    });
    if (receipt) {
      const row = (receipt[frequency] || []).find((candidate) => candidate.status === "forecast" && Number.isFinite(Number(candidate.valueKbd)));
      tests.push({ kind: "receipt", name: "receipt movement adjustment", frequency, regionKey: receipt.toRegionKey, period: row.period, flowId: receipt.id, lineId: receiptAdjustmentLineId(receipt.id), targetLine: receiptLineId(receipt.id), value: round3(Number(row.valueKbd || 0) + 11.111) });
    }
  }
  return tests;
}

function validateExpectedValue(afterCalc, test) {
  const failures = [];
  const afterRows = afterCalc.rowsForFrequency(test.frequency);
  const afterMap = indexRows(afterRows);
  const afterPoint = afterMap.get(`${test.period}|${test.regionKey}`);
  if (!afterPoint) return [`${test.name}: missing after point ${test.frequency} ${test.period} ${test.regionKey}`];

  if (test.kind === "direct") {
    const actual = afterCalc.valueForLine(afterPoint, test.targetLine, test.frequency, test.regionKey);
    if (!near(actual, test.value, 0.03)) failures.push(`${test.name}: ${test.frequency} ${test.period} ${test.regionKey} ${test.targetLine}=${actual} expected edited value ${test.value}`);
  }
  if (test.kind === "destination") {
    const destinationValue = afterCalc.valueForLine(afterPoint, test.targetLine, test.frequency, test.regionKey);
    if (!near(destinationValue, test.value, 0.03)) failures.push(`${test.name}: ${test.frequency} ${test.period} ${test.regionKey} ${test.targetLine}=${destinationValue} expected edited destination value ${test.value}`);
    const totalExports = afterCalc.valueForLine(afterPoint, "exports", test.frequency, test.regionKey);
    const expectedTotal = afterCalc.exportDestinationTotal(afterPoint);
    if (!near(totalExports, expectedTotal, 0.03)) failures.push(`${test.name}: ${test.frequency} ${test.period} ${test.regionKey} total exports=${totalExports} expected destination sum ${expectedTotal}`);
  }
  if (test.kind === "receipt") {
    const actual = afterCalc.movementFlowValue(test.frequency, test.period, test.flowId);
    if (!near(actual, test.value, 0.03)) failures.push(`${test.name}: ${test.frequency} ${test.period} ${test.flowId} movement=${actual} expected edited value ${test.value}`);
  }
  return failures;
}

function validateExpectedChange(beforeCalc, afterCalc, test) {
  const failures = validateExpectedValue(afterCalc, test);
  const afterRows = afterCalc.rowsForFrequency(test.frequency);
  const beforeRows = beforeCalc.rowsForFrequency(test.frequency);
  const changes = changedCells(beforeRows, afterRows);
  const affected = affectedRegionsForCase(beforeCalc, test);
  const unrelated = changes.filter((change) => !affected.has(change.regionKey) && change.field !== "daysForwardCover");
  if (unrelated.length) {
    failures.push(`${test.name}: ${test.frequency} changed unrelated rows: ${unrelated.slice(0, 8).map((row) => `${row.period}/${row.regionKey}/${row.field}`).join(", ")}`);
  }

  const selectedChanges = changes.filter((change) => change.period === test.period && affected.has(change.regionKey));
  if (!selectedChanges.length) failures.push(`${test.name}: ${test.frequency} ${test.period} produced no selected-period dependent changes`);
  return failures;
}

function runProduct(product) {
  const runtime = loadRuntime(product);
  const baselineCalc = new Calculator(runtime);
  const tests = makeStandardTests(runtime);
  const columnTests = makeColumnTests(runtime, baselineCalc);
  const baselineRows = [...baselineCalc.rowsForFrequency("monthly"), ...baselineCalc.rowsForFrequency("weekly")];
  const failures = [
    ...assertFormulaInvariants(baselineCalc, "monthly", baselineCalc.rowsForFrequency("monthly"), `${product.key} baseline`),
    ...assertFormulaInvariants(baselineCalc, "weekly", baselineCalc.rowsForFrequency("weekly"), `${product.key} baseline`),
  ];
  const summaries = [];

  for (const test of tests) {
    const testRuntime = runtimeWithAdjustments(runtime, baselineCalc, {
      frequency: test.frequency,
      period: test.period,
      regionKey: test.regionKey,
      lineId: test.lineId,
      valueKbd: test.value,
      note: "Synthetic validation override",
      updatedAt: "2099-01-01T00:00:00.000Z",
    });
    const beforeCalc = new Calculator(runtime);
    const afterCalc = new Calculator(testRuntime);
    const afterRows = afterCalc.rowsForFrequency(test.frequency);
    const changes = changedCells(beforeCalc.rowsForFrequency(test.frequency), afterRows);
    failures.push(...validateExpectedChange(beforeCalc, afterCalc, test));
    failures.push(...assertFormulaInvariants(afterCalc, test.frequency, afterRows, `${product.key} ${test.name}`));
    summaries.push({
      product: product.key,
      frequency: test.frequency,
      period: test.period,
      region: test.regionKey,
      edit: test.lineId,
      targetValue: test.value,
      changedCells: changes.length,
      changedRegions: Array.from(new Set(changes.map((change) => change.regionKey))).sort(),
      changedFields: Array.from(new Set(changes.map((change) => change.field))).sort(),
    });
  }

  const columnGroups = new Map();
  for (const test of columnTests) {
    const key = `${test.frequency}|${test.period}`;
    const group = columnGroups.get(key) || [];
    group.push(test);
    columnGroups.set(key, group);
  }
  for (const [key, group] of columnGroups.entries()) {
    const [frequency, period] = key.split("|");
    const adjustmentRows = group.map((test) => ({
      frequency: test.frequency,
      period: test.period,
      regionKey: test.regionKey,
      lineId: test.lineId,
      valueKbd: test.value,
      note: "Synthetic first-column validation override",
      updatedAt: "2099-01-01T00:00:00.000Z",
    }));
    const testRuntime = runtimeWithAdjustmentList(runtime, baselineCalc, adjustmentRows);
    const afterCalc = new Calculator(testRuntime);
    const afterRows = afterCalc.rowsForFrequency(frequency);
    const changes = changedCells(baselineCalc.rowsForFrequency(frequency), afterRows);
    for (const test of group) failures.push(...validateExpectedValue(afterCalc, test));
    failures.push(...assertFormulaInvariants(afterCalc, frequency, afterRows, `${product.key} first forecast column ${frequency}`));
    summaries.push({
      product: product.key,
      frequency,
      period,
      region: "all-base",
      edit: `${group.length} first-column editable rows`,
      targetValue: "",
      changedCells: changes.length,
      changedRegions: Array.from(new Set(changes.map((change) => change.regionKey))).sort(),
      changedFields: Array.from(new Set(changes.map((change) => change.field))).sort(),
    });
  }

  return {
    product: product.key,
    generatedAt: runtime.generatedAt,
    baselineRows: baselineRows.length,
    tests: summaries,
    failures,
  };
}

const results = PRODUCTS.map(runProduct);
const failures = results.flatMap((result) => result.failures.map((failure) => `${result.product}: ${failure}`));

for (const result of results) {
  console.log(`\n${result.product.toUpperCase()} generated ${result.generatedAt}`);
  console.log(`  baseline adjusted rows checked: ${result.baselineRows}`);
  for (const test of result.tests) {
    console.log(`  ${test.frequency.padEnd(7)} ${test.period} ${test.region.padEnd(7)} ${test.edit.padEnd(32)} changed=${String(test.changedCells).padStart(3)} fields=${test.changedFields.join("|")}`);
  }
}

if (failures.length) {
  console.error("\nFAILURES");
  failures.slice(0, 80).forEach((failure) => console.error(" - " + failure));
  if (failures.length > 80) console.error(` - ... ${failures.length - 80} more`);
  process.exitCode = 1;
} else {
  console.log("\nPASS balance adjustment propagation and formula invariants passed for Diesel_Balance and Jet_Balance monthly/weekly modes.");
}
