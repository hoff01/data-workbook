import "./env.js";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

type Step = {
  label: string;
  command: string;
  args: string[];
};

const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = process.env.US_BALANCES_SHARED_ROOT ? resolve(process.env.US_BALANCES_SHARED_ROOT) : SOURCE_ROOT;
const pythonCommand = process.env.US_BALANCES_PYTHON || (process.platform === "win32" ? "python" : "python3");

function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${(seconds - minutes * 60).toFixed(1)}s`;
}

function commandText(step: Step): string {
  return [step.command, ...step.args].join(" ");
}

async function runStep(step: Step, index: number, total: number): Promise<number> {
  const started = performance.now();
  console.log(`[weekly] step ${index}/${total} start: ${step.label} :: ${commandText(step)}`);
  await new Promise<void>((resolve, reject) => {
    const child = spawn(step.command, step.args, {
      cwd: ROOT,
      env: { ...process.env, FORCE_COLOR: "0" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk: Buffer) => process.stdout.write(chunk));
    child.stderr.on("data", (chunk: Buffer) => process.stderr.write(chunk));
    child.on("error", reject);
    child.on("close", (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${step.label} failed with code ${code ?? "n/a"} signal ${signal ?? "n/a"}`));
    });
  });
  const elapsed = performance.now() - started;
  console.log(`[weekly] step ${index}/${total} done: ${step.label} duration=${formatDuration(elapsed)}`);
  return elapsed;
}

async function main(): Promise<void> {
  const weeklyRawArgs = process.argv.slice(2);
  const steps: Step[] = [
    { label: "weekly raw EIA pull", command: pythonCommand, args: ["src/weekly_xls.py", ...weeklyRawArgs] },
    {
      label: "weekly clean CSV export",
      command: pythonCommand,
      args: ["src/export_raw_headers.py", "weekly", "--skip-weekly-raw-archive"],
    },
    { label: "clean public EIA outputs", command: pythonCommand, args: ["src/clean_eia_outputs.py"] },
    { label: "Kpler PADD 1 EIA split", command: pythonCommand, args: ["src/kpler_padd1_eia_split.py"] },
  ];
  const started = performance.now();
  let workRuntime = 0;
  for (const [index, step] of steps.entries()) {
    workRuntime += await runStep(step, index + 1, steps.length);
  }
  const elapsed = performance.now() - started;
  console.log(`[weekly] complete total=${formatDuration(elapsed)} work_runtime=${formatDuration(workRuntime)}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error: unknown) => {
    console.error(`[weekly] failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}
