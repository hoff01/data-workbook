#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

async function openPort() {
  return await new Promise((resolvePort, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      const port = typeof address === "object" && address ? address.port : 0;
      probe.close((error) => error ? reject(error) : resolvePort(port));
    });
  });
}

async function fetchJson(url, init) {
  const response = await fetch(url, init);
  const body = await response.json();
  return { response, body };
}

async function waitForHealth(baseUrl, timeoutMs = 12_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const { response, body } = await fetchJson(`${baseUrl}/api/health`);
      if (response.ok && body.ok) return body;
    } catch {
      // Server is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`dashboard server did not become healthy at ${baseUrl}`);
}

async function waitForTerminalJob(baseUrl, timeoutMs = 12_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { response, body } = await fetchJson(`${baseUrl}/api/update/status`);
    assert.equal(response.status, 200);
    if (body.job && body.job.status !== "running") return body.job;
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error("fake dashboard update did not finish");
}

async function waitForSettingsRebuild(baseUrl, expected = true, timeoutMs = 12_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { response, body } = await fetchJson(`${baseUrl}/api/update/status`);
    assert.equal(response.status, 200);
    if (body.settingsRebuild === expected) return body;
    await new Promise((resolveWait) => setTimeout(resolveWait, 25));
  }
  throw new Error(`settings rebuild did not reach expected=${expected}`);
}

const port = await openPort();
const baseUrl = `http://127.0.0.1:${port}`;
const readyFile = join(tmpdir(), `us-balances-refresh-ready-${process.pid}-${Date.now()}`);
const silentNoopFile = join(tmpdir(), `us-balances-silent-noop-${process.pid}-${Date.now()}`);
const settingsDir = mkdtempSync(join(tmpdir(), "us-balances-settings-test-"));
const settingsPath = join(settingsDir, "balance_dashboard_settings.json");
const outagesExportPath = join(settingsDir, "outages.json");
const settingsRebuildLog = join(settingsDir, "rebuild.log");
const settingsRebuildFailFile = join(settingsDir, "fail-once");
writeFileSync(settingsPath, JSON.stringify({
  forecastEnd: "2027-06-01",
  adjustments: { diesel: [], jet: [] },
  crudeOutages: [],
  refineryCapacityAdjustments: [],
  updatedAt: new Date().toISOString(),
}, null, 2));
const output = [];
const child = spawn(process.execPath, ["--import", "tsx", "src/dashboard_update_server.ts"], {
  cwd: ROOT,
  env: {
    ...process.env,
    DASHBOARD_UPDATE_PORT: String(port),
    US_BALANCES_NODE_COMMAND: process.execPath,
    US_BALANCES_PYTHON: process.execPath,
    US_BALANCES_REFRESH_READY_FILE: readyFile,
    US_BALANCES_TSX_CLI: join(ROOT, "scripts", "fake_update_cli.mjs"),
    US_BALANCES_WEEKLY_OUTPUT_SCRIPT: join(ROOT, "scripts", "fake_update_cli.mjs"),
    US_BALANCES_FAKE_NO_START_FILE: silentNoopFile,
    US_BALANCES_FAKE_UPDATE_DELAY_MS: "250",
    US_BALANCES_SETTINGS_PATH: settingsPath,
    US_BALANCES_DASHBOARD_STATE_ROOT: settingsDir,
    US_BALANCES_SETTINGS_REBUILD_SCRIPT: join(ROOT, "scripts", "fake_update_cli.mjs"),
    US_BALANCES_FAKE_SETTINGS_REBUILD_LOG: settingsRebuildLog,
    US_BALANCES_FAKE_SETTINGS_REBUILD_FAIL_FILE: settingsRebuildFailFile,
    DASHBOARD_POWER_DFO_STARTUP_REFRESH: "1",
  },
  stdio: ["ignore", "pipe", "pipe"],
});
child.stdout.on("data", (chunk) => output.push(chunk.toString("utf8")));
child.stderr.on("data", (chunk) => output.push(chunk.toString("utf8")));

try {
  const initialHealth = await waitForHealth(baseUrl);
  assert.equal(initialHealth.app, "balance-dashboard-update-server");
  assert.equal(typeof initialHealth.buildId, "string");
  assert.ok(initialHealth.buildId.length >= 8);
  assert.equal(initialHealth.refreshReady, false);
  const publicOutages = await fetchJson(`${baseUrl}/outages.json`);
  assert.equal(publicOutages.response.status, 200);
  assert.equal(publicOutages.body.schemaVersion, 1);
  assert.deepEqual(publicOutages.body.sharedProducts, ["diesel", "jet"]);
  await new Promise((resolveWait) => setTimeout(resolveWait, 400));
  const initialStatus = await fetchJson(`${baseUrl}/api/update/status`);
  assert.equal(initialStatus.response.status, 200);
  assert.equal(initialStatus.body.job, null, "server startup must remain idle even when the removed startup-refresh env is set");
  assert.equal(initialStatus.body.refreshReady, false);

  const blocked = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "all", force: true }),
  });
  assert.equal(blocked.response.status, 503);
  assert.match(blocked.body.error, /Refresh tools are still being prepared/);

  writeFileSync(readyFile, new Date().toISOString());
  const readyHealth = await waitForHealth(baseUrl);
  assert.equal(readyHealth.refreshReady, true);

  const initialSettings = await fetchJson(`${baseUrl}/api/settings`);
  assert.equal(initialSettings.response.status, 200);
  const shortenedRequest = fetchJson(`${baseUrl}/api/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ forecastEnd: "2026-12-31", baseRevision: initialSettings.body.settings.revision }),
  });
  await waitForSettingsRebuild(baseUrl, true);
  const settingsDuringRebuild = await fetchJson(`${baseUrl}/api/settings`);
  assert.equal(settingsDuringRebuild.response.status, 200);
  assert.equal(settingsDuringRebuild.body.rebuildPending, true);
  assert.equal(settingsDuringRebuild.body.settings.forecastEnd, "2027-06-01", "GET must expose only the last committed settings during a rebuild");
  assert.equal(settingsDuringRebuild.body.settings.revision, initialSettings.body.settings.revision);

  const blockedSettingsWrite = await fetchJson(`${baseUrl}/api/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      forecastEnd: "2027-06-01",
      product: "diesel",
      adjustments: [{ frequency: "monthly", period: "2026-10", regionKey: "padd1", lineId: "imports", valueKbd: 1 }],
      baseRevision: initialSettings.body.settings.revision,
    }),
  });
  assert.equal(blockedSettingsWrite.response.status, 409);
  assert.match(blockedSettingsWrite.body.error, /rebuild in progress/);
  assert.equal(blockedSettingsWrite.body.settings.forecastEnd, "2027-06-01");

  const blockedRefreshDuringSettingsRebuild = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "all", force: true }),
  });
  assert.equal(blockedRefreshDuringSettingsRebuild.response.status, 409);
  assert.equal(blockedRefreshDuringSettingsRebuild.body.settingsRebuild, true);
  assert.match(blockedRefreshDuringSettingsRebuild.body.error, /Forecast settings are rebuilding/);

  const shortened = await shortenedRequest;
  assert.equal(shortened.response.status, 200);
  assert.equal(shortened.body.rebuilt, true);
  assert.equal(shortened.body.settings.forecastEnd, "2026-12-31");
  assert.equal(readFileSync(settingsRebuildLog, "utf8").trim().split(/\r?\n/).length, 1);
  const settledSettingsStatus = await waitForSettingsRebuild(baseUrl, false);
  assert.equal(settledSettingsStatus.settingsRebuild, false);

  const sharedOutage = {
    id: "outage-test",
    regionKey: "padd3",
    refineryId: "refinery-test",
    refineryName: "Test Refinery",
    unitKey: "atmospheric-distillation",
    unitLabel: "Atmospheric Distillation",
    refinery: "Test Refinery",
    capacityOfflineKbd: 42.26,
    startDate: "2026-08-01",
    endDate: "2026-08-05",
    type: "Planned",
    note: "Server export contract",
  };
  const outageSave = await fetchJson(`${baseUrl}/api/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ crudeOutages: [sharedOutage], baseRevision: shortened.body.settings.revision }),
  });
  assert.equal(outageSave.response.status, 200);
  assert.equal(outageSave.body.rebuilt, false);
  const exportedOutages = JSON.parse(readFileSync(outagesExportPath, "utf8"));
  assert.equal(exportedOutages.schemaVersion, 1);
  assert.deepEqual(exportedOutages.sharedProducts, ["diesel", "jet"]);
  assert.equal(exportedOutages.outageCount, 1);
  assert.equal(exportedOutages.outages[0].id, sharedOutage.id);
  assert.equal(exportedOutages.outages[0].capacityOfflineKbd, 42.3);

  writeFileSync(settingsRebuildFailFile, "fail once\n");
  const failedRevision = outageSave.body.settings.revision;
  const failedRebuild = await fetchJson(`${baseUrl}/api/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ forecastEnd: "2027-03-31", baseRevision: failedRevision }),
  });
  assert.equal(failedRebuild.response.status, 500);
  assert.equal(failedRebuild.body.rebuilt, false);
  assert.equal(failedRebuild.body.settings.forecastEnd, "2026-12-31");
  assert.match(failedRebuild.body.error, /Previous settings and dashboard packages were restored/);
  assert.equal(JSON.parse(readFileSync(settingsPath, "utf8")).forecastEnd, "2026-12-31");
  assert.equal(JSON.parse(readFileSync(outagesExportPath, "utf8")).outageCount, 1);
  assert.equal(readFileSync(settingsRebuildLog, "utf8").trim().split(/\r?\n/).length, 3, "failed build plus rollback must both run");

  const started = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "all", force: true }),
  });
  assert.equal(started.response.status, 202);
  assert.equal(started.body.job.status, "running");
  assert.ok(Number.isInteger(started.body.job.pid) && started.body.job.pid > 0);

  const settingsWhileRunning = await fetchJson(`${baseUrl}/api/settings`);
  const concurrentForecastSave = await fetchJson(`${baseUrl}/api/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ forecastEnd: "2027-01-31", baseRevision: settingsWhileRunning.body.settings.revision }),
  });
  assert.equal(concurrentForecastSave.response.status, 409);
  assert.equal(concurrentForecastSave.body.settings.forecastEnd, "2026-12-31");

  const job = await waitForTerminalJob(baseUrl);
  assert.equal(job.status, "succeeded");
  assert.equal(job.exitCode, 0);
  assert.equal(job.signal, null);
  assert.equal(job.result, "current");
  assert.equal(job.dataChanged, false);
  assert.match(job.lines.join("\n"), /process started pid=\d+/);
  assert.match(job.lines.join("\n"), /source data was unchanged, and the workbooks were rebuilt anyway/);

  const repeated = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "all", force: true }),
  });
  assert.equal(repeated.response.status, 202);
  assert.notEqual(repeated.body.job.id, job.id, "a repeated forced refresh must start a new job");
  const repeatedJob = await waitForTerminalJob(baseUrl);
  assert.equal(repeatedJob.status, "succeeded");
  assert.equal(repeatedJob.result, "current");
  assert.match(repeatedJob.lines.join("\n"), /source data was unchanged, and the workbooks were rebuilt anyway/);

  const routedGroups = ["weekly", "monthly", "other", "power-dfo"];
  const routedJobIds = new Set([job.id, repeatedJob.id]);
  for (const group of routedGroups) {
    const routed = await fetchJson(`${baseUrl}/api/update/start`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ group, force: true }),
    });
    assert.equal(routed.response.status, 202, `${group} refresh must start`);
    assert.equal(routed.body.job.group, group);
    assert.equal(routed.body.job.status, "running");
    assert.equal(routedJobIds.has(routed.body.job.id), false, `${group} refresh must get a new job id`);
    routedJobIds.add(routed.body.job.id);
    const routedJob = await waitForTerminalJob(baseUrl);
    assert.equal(routedJob.group, group);
    assert.equal(routedJob.status, "succeeded");
    assert.equal(routedJob.result, "current");
    assert.match(routedJob.lines.join("\n"), /source data was unchanged, and the workbooks were rebuilt anyway/);
  }
  const missingWeeklyOutputProduct = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "weekly-call-outputs" }),
  });
  assert.equal(missingWeeklyOutputProduct.response.status, 400);
  assert.match(missingWeeklyOutputProduct.body.error, /requires product=diesel or product=jet/);

  const missingDashboardState = await fetchJson(`${baseUrl}/api/dashboard-state?product=jet`);
  assert.equal(missingDashboardState.response.status, 404);
  const currentSettings = await fetchJson(`${baseUrl}/api/settings`);
  const portableState = {
    schema: "us-balances.dashboard-state",
    schemaVersion: 1,
    id: "test-jet-state",
    product: "jet",
    savedAt: new Date().toISOString(),
    provenance: { latestWeekly: "2026-07-17", sourceChecksums: { eia_weekly: "synthetic" } },
    settings: {
      forecastEnd: currentSettings.body.settings.forecastEnd,
      revision: currentSettings.body.settings.revision,
      adjustments: currentSettings.body.settings.adjustments.jet,
      crudeOutages: currentSettings.body.settings.crudeOutages,
      refineryCapacityAdjustments: currentSettings.body.settings.refineryCapacityAdjustments,
    },
    materialized: {
      regionalBalance: {
        monthly: [{ period: "2026-07", status: "forecast", regionKey: "padd3", exportsKbd: 10 }],
        weekly: [{ period: "2026-07-24", status: "forecast", regionKey: "padd3", exportsKbd: 10 }],
      },
    },
  };
  const wrongProductState = await fetchJson(`${baseUrl}/api/dashboard-state`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ product: "diesel", state: portableState }),
  });
  assert.equal(wrongProductState.response.status, 400);
  assert.match(wrongProductState.body.error, /does not match diesel/);
  const savedDashboardState = await fetchJson(`${baseUrl}/api/dashboard-state`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ product: "jet", state: portableState }),
  });
  assert.equal(savedDashboardState.response.status, 200);
  assert.equal(savedDashboardState.body.state.product, "jet");
  assert.match(savedDashboardState.body.fingerprint, /^[a-f0-9]{64}$/);
  const savedDashboardStatePath = join(settingsDir, "Jet_Balance", "dashboard_state.json");
  assert.equal(existsSync(savedDashboardStatePath), true);
  assert.equal(JSON.parse(readFileSync(savedDashboardStatePath, "utf8")).fingerprint, savedDashboardState.body.fingerprint);
  const loadedDashboardState = await fetchJson(`${baseUrl}/api/dashboard-state?product=jet`);
  assert.equal(loadedDashboardState.response.status, 200);
  assert.equal(loadedDashboardState.body.state.id, portableState.id);

  const dieselPortableState = {
    ...portableState,
    id: "test-diesel-state",
    product: "diesel",
    settings: {
      ...portableState.settings,
      adjustments: currentSettings.body.settings.adjustments.diesel,
    },
  };
  const savedDieselState = await fetchJson(`${baseUrl}/api/dashboard-state`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ product: "diesel", state: dieselPortableState }),
  });
  assert.equal(savedDieselState.response.status, 200);
  const savedDieselStatePath = join(settingsDir, "Diesel_Balance", "dashboard_state.json");
  assert.equal(existsSync(savedDieselStatePath), true);

  const noOpJetSettingsSave = await fetchJson(`${baseUrl}/api/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      forecastEnd: currentSettings.body.settings.forecastEnd,
      product: "jet",
      adjustments: currentSettings.body.settings.adjustments.jet,
      crudeOutages: currentSettings.body.settings.crudeOutages,
      refineryCapacityAdjustments: currentSettings.body.settings.refineryCapacityAdjustments,
      baseRevision: currentSettings.body.settings.revision,
    }),
  });
  assert.equal(noOpJetSettingsSave.response.status, 200);
  assert.equal(noOpJetSettingsSave.body.settings.revision, currentSettings.body.settings.revision, "no-op saves must not change the semantic settings revision");

  const jetAdjustment = { frequency: "monthly", period: "2026-10", regionKey: "padd5", lineId: "exports", valueKbd: 123.4 };
  const changedJetSettings = await fetchJson(`${baseUrl}/api/settings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      product: "jet",
      adjustments: [jetAdjustment],
      baseRevision: noOpJetSettingsSave.body.settings.revision,
    }),
  });
  assert.equal(changedJetSettings.response.status, 200);
  assert.notEqual(changedJetSettings.body.settings.revision, currentSettings.body.settings.revision);
  const updatedJetState = {
    ...portableState,
    id: "test-jet-state-updated",
    savedAt: new Date().toISOString(),
    settings: {
      forecastEnd: changedJetSettings.body.settings.forecastEnd,
      revision: changedJetSettings.body.settings.revision,
      adjustments: changedJetSettings.body.settings.adjustments.jet,
      crudeOutages: changedJetSettings.body.settings.crudeOutages,
      refineryCapacityAdjustments: changedJetSettings.body.settings.refineryCapacityAdjustments,
    },
  };
  const resavedJetState = await fetchJson(`${baseUrl}/api/dashboard-state`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ product: "jet", state: updatedJetState }),
  });
  assert.equal(resavedJetState.response.status, 200);

  const dieselOutputsStarted = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "weekly-call-outputs", product: "diesel" }),
  });
  assert.equal(dieselOutputsStarted.response.status, 202, "saving Jet must not invalidate the saved Diesel state");
  assert.deepEqual(dieselOutputsStarted.body.job.args.slice(-4), ["--product", "diesel", "--dashboard-state", savedDieselStatePath]);
  const dieselOutputsJob = await waitForTerminalJob(baseUrl);
  assert.equal(dieselOutputsJob.status, "succeeded");
  assert.equal(dieselOutputsJob.result, "saved");

  const weeklyOutputsStarted = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "weekly-call-outputs", product: "jet" }),
  });
  assert.equal(weeklyOutputsStarted.response.status, 202);
  assert.equal(weeklyOutputsStarted.body.job.group, "weekly-call-outputs");
  assert.equal(weeklyOutputsStarted.body.job.product, "jet");
  assert.deepEqual(weeklyOutputsStarted.body.job.args.slice(-4), ["--product", "jet", "--dashboard-state", savedDashboardStatePath]);
  assert.equal(weeklyOutputsStarted.body.job.status, "running");

  const weeklyOutputsJob = await waitForTerminalJob(baseUrl);
  assert.equal(weeklyOutputsJob.group, "weekly-call-outputs");
  assert.equal(weeklyOutputsJob.product, "jet");
  assert.equal(weeklyOutputsJob.status, "succeeded");
  assert.equal(weeklyOutputsJob.exitCode, 0);
  assert.equal(weeklyOutputsJob.signal, null);
  assert.equal(weeklyOutputsJob.result, "saved");
  assert.equal(weeklyOutputsJob.dataChanged, true);
  assert.match(weeklyOutputsJob.lines.join("\n"), /Jet weekly table and bar charts were saved/);

  writeFileSync(silentNoopFile, "trigger\n");
  const silentNoopStarted = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "monthly", force: true }),
  });
  assert.equal(silentNoopStarted.response.status, 202);
  const silentNoopJob = await waitForTerminalJob(baseUrl);
  assert.equal(silentNoopJob.status, "failed");
  assert.equal(silentNoopJob.exitCode, 0);
  assert.equal(silentNoopJob.result, null);
  assert.equal(silentNoopJob.dataChanged, null);
  assert.match(silentNoopJob.lines.join("\n"), /no update steps were confirmed/);
  console.log(`dashboard update server contract ok build=${initialHealth.buildId}`);
} catch (error) {
  console.error(output.join(""));
  throw error;
} finally {
  child.kill();
  rmSync(readyFile, { force: true });
  rmSync(silentNoopFile, { force: true });
  rmSync(settingsDir, { recursive: true, force: true });
}
