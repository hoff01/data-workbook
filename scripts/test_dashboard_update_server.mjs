#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { writeFileSync, rmSync } from "node:fs";
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

const port = await openPort();
const baseUrl = `http://127.0.0.1:${port}`;
const readyFile = join(tmpdir(), `us-balances-refresh-ready-${process.pid}-${Date.now()}`);
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

  const blocked = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "all", force: true }),
  });
  assert.equal(blocked.response.status, 503);
  assert.match(blocked.body.error, /First-run refresh setup is still finishing/);

  writeFileSync(readyFile, new Date().toISOString());
  const readyHealth = await waitForHealth(baseUrl);
  assert.equal(readyHealth.refreshReady, true);

  const started = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "all", force: true }),
  });
  assert.equal(started.response.status, 202);
  assert.equal(started.body.job.status, "running");

  const job = await waitForTerminalJob(baseUrl);
  assert.equal(job.status, "succeeded");
  assert.equal(job.exitCode, 0);
  assert.equal(job.signal, null);
  assert.equal(job.result, "current");
  assert.equal(job.dataChanged, false);
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

  const missingWeeklyOutputProduct = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "weekly-call-outputs" }),
  });
  assert.equal(missingWeeklyOutputProduct.response.status, 400);
  assert.match(missingWeeklyOutputProduct.body.error, /requires product=diesel or product=jet/);

  const weeklyOutputsStarted = await fetchJson(`${baseUrl}/api/update/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ group: "weekly-call-outputs", product: "jet" }),
  });
  assert.equal(weeklyOutputsStarted.response.status, 202);
  assert.equal(weeklyOutputsStarted.body.job.group, "weekly-call-outputs");
  assert.equal(weeklyOutputsStarted.body.job.product, "jet");
  assert.deepEqual(weeklyOutputsStarted.body.job.args.slice(-2), ["--product", "jet"]);
  assert.equal(weeklyOutputsStarted.body.job.status, "running");

  const weeklyOutputsJob = await waitForTerminalJob(baseUrl);
  assert.equal(weeklyOutputsJob.group, "weekly-call-outputs");
  assert.equal(weeklyOutputsJob.product, "jet");
  assert.equal(weeklyOutputsJob.status, "succeeded");
  assert.equal(weeklyOutputsJob.exitCode, 0);
  assert.equal(weeklyOutputsJob.signal, null);
  assert.equal(weeklyOutputsJob.result, "saved");
  assert.equal(weeklyOutputsJob.dataChanged, true);
  assert.match(weeklyOutputsJob.lines.join("\n"), /Jet weekly call outputs were saved/);
  console.log(`dashboard update server contract ok build=${initialHealth.buildId}`);
} catch (error) {
  console.error(output.join(""));
  throw error;
} finally {
  child.kill();
  rmSync(readyFile, { force: true });
}
