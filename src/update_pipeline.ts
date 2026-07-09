import "./env.js";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

type UpdateGroup = "weekly" | "monthly" | "other" | "all" | "power-dfo";

type Step = {
  label: string;
  command: string;
  args: string[];
};

type StepBranch = {
  label: string;
  steps: Step[];
};

type ParallelPhase = {
  label: string;
  parallel: StepBranch[];
};

type Phase = Step | ParallelPhase;

type RunProgress = {
  nextStep: number;
  totalSteps: number;
};

const pythonCommand = process.env.US_BALANCES_PYTHON || (process.platform === "win32" ? "python" : "python3");
const tsxCommand = process.env.US_BALANCES_TSX_COMMAND;
const nodeCommand = process.execPath;
const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = process.env.US_BALANCES_SHARED_ROOT ? resolve(process.env.US_BALANCES_SHARED_ROOT) : SOURCE_ROOT;

function pythonStep(label: string, script: string, args: string[] = []): Step {
  return { label, command: pythonCommand, args: [script, ...args] };
}

function tsStep(label: string, script: string, args: string[] = []): Step {
  if (tsxCommand) return { label, command: tsxCommand, args: [script, ...args] };
  return { label, command: nodeCommand, args: ["--import", "tsx", script, ...args] };
}

function scriptStep(label: string, script: string): Step {
  switch (script) {
    case "weekly:raw":
      return pythonStep(label, "src/weekly_xls.py");
    case "monthly":
      return tsStep(label, "src/monthly.ts");
    case "capacity":
      return pythonStep(label, "src/eia_capacity.py");
    case "capacity:refineries":
      return pythonStep(label, "src/refinery_capacity_units.py");
    case "power:dfo":
      return pythonStep(label, "power_generation_dfo/pull_power_generation_dfo.py");
    case "power:dfo:hourly":
      return pythonStep(label, "power_generation_dfo/hourly_dfo_forecast.py");
    case "kpler":
      return pythonStep(label, "src/kpler_pull.py");
    case "kpler:padd1:eia":
      return pythonStep(label, "src/kpler_padd1_eia_split.py");
    case "padd1":
      return pythonStep(label, "src/padd_1_distillate.py");
    case "clean:eia":
      return pythonStep(label, "src/clean_eia_outputs.py");
    case "export:weekly:clean":
      return pythonStep(label, "src/export_raw_headers.py", ["weekly", "--skip-weekly-raw-archive"]);
    case "export:monthly":
      return pythonStep(label, "src/export_raw_headers.py", ["monthly"]);
    case "export:bulk-series":
      return pythonStep(label, "src/export_bulk_series.py");
    case "export:headers:clean":
      return pythonStep(label, "src/export_raw_headers.py", ["all", "--skip-weekly-raw-archive"]);
    case "verify:weekly":
      return tsStep(label, "src/verify_weekly_freshness.ts");
    case "verify:monthly":
      return tsStep(label, "src/verify_monthly_freshness.ts");
    case "verify:dashboard":
      return tsStep(label, "src/verify_dashboard_freshness.ts");
    case "validate":
      return pythonStep(label, "src/validate_outputs.py");
    case "data:check":
      return pythonStep(label, "src/data_health_check.py");
    case "build:balances":
      return tsStep(label, "src/build_balance_dashboards.ts");
    default:
      throw new Error(`No direct update command is configured for npm script ${script}`);
  }
}

function branch(label: string, steps: Step[]): StepBranch {
  return { label, steps };
}

function parallelPhase(label: string, parallel: StepBranch[]): ParallelPhase {
  return { label, parallel };
}

function isParallelPhase(phase: Phase): phase is ParallelPhase {
  return "parallel" in phase;
}

const GROUP_PHASES: Record<UpdateGroup, Phase[]> = {
  weekly: [
    scriptStep("weekly EIA pull", "weekly:raw"),
    scriptStep("weekly export files", "export:weekly:clean"),
    scriptStep("clean public EIA outputs", "clean:eia"),
    scriptStep("Kpler PADD 1 EIA split", "kpler:padd1:eia"),
    scriptStep("weekly freshness check", "verify:weekly"),
    scriptStep("rebuild balance dashboards", "build:balances"),
    scriptStep("dashboard freshness check", "verify:dashboard"),
  ],
  monthly: [
    scriptStep("monthly EIA pull", "monthly"),
    scriptStep("monthly export files", "export:monthly"),
    scriptStep("monthly needed bulk series inventory", "export:bulk-series"),
    scriptStep("PADD 1 distillate split", "padd1"),
    scriptStep("clean public EIA outputs", "clean:eia"),
    scriptStep("monthly freshness check", "verify:monthly"),
    scriptStep("rebuild balance dashboards", "build:balances"),
    scriptStep("dashboard freshness check", "verify:dashboard"),
  ],
  other: [
    parallelPhase("independent context refreshes", [
      branch("Kpler package", [scriptStep("Kpler flow package", "kpler"), scriptStep("Kpler PADD 1 EIA split", "kpler:padd1:eia")]),
      branch("capacity", [scriptStep("capacity refresh", "capacity"), scriptStep("refinery unit capacity refresh", "capacity:refineries")]),
      branch("power DFO", [scriptStep("power DFO daily refresh", "power:dfo"), scriptStep("power DFO hourly forecast", "power:dfo:hourly")]),
    ]),
    scriptStep("validate clean outputs", "validate"),
    scriptStep("data health check", "data:check"),
    scriptStep("rebuild balance dashboards", "build:balances"),
    scriptStep("dashboard freshness check", "verify:dashboard"),
  ],
  all: [
    parallelPhase("EIA source refreshes", [
      branch("weekly EIA", [scriptStep("weekly EIA pull", "weekly:raw")]),
      branch("monthly EIA", [scriptStep("monthly EIA pull", "monthly")]),
    ]),
    scriptStep("weekly/monthly export files", "export:headers:clean"),
    scriptStep("monthly needed bulk series inventory", "export:bulk-series"),
    scriptStep("PADD 1 distillate split", "padd1"),
    scriptStep("clean public EIA outputs", "clean:eia"),
    parallelPhase("EIA freshness checks", [
      branch("weekly freshness", [scriptStep("weekly freshness check", "verify:weekly")]),
      branch("monthly freshness", [scriptStep("monthly freshness check", "verify:monthly")]),
    ]),
    parallelPhase("independent context refreshes", [
      branch("Kpler package", [scriptStep("Kpler flow package", "kpler"), scriptStep("Kpler PADD 1 EIA split", "kpler:padd1:eia")]),
      branch("capacity", [scriptStep("capacity refresh", "capacity"), scriptStep("refinery unit capacity refresh", "capacity:refineries")]),
      branch("power DFO", [scriptStep("power DFO daily refresh", "power:dfo"), scriptStep("power DFO hourly forecast", "power:dfo:hourly")]),
    ]),
    scriptStep("validate clean outputs", "validate"),
    scriptStep("data health check", "data:check"),
    scriptStep("rebuild balance dashboards", "build:balances"),
    scriptStep("dashboard freshness check", "verify:dashboard"),
  ],
  "power-dfo": [
    scriptStep("power DFO daily refresh", "power:dfo"),
    scriptStep("power DFO hourly forecast", "power:dfo:hourly"),
    scriptStep("rebuild balance dashboards", "build:balances"),
    scriptStep("dashboard freshness check", "verify:dashboard"),
  ],
};

function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${(seconds - minutes * 60).toFixed(1)}s`;
}

function commandText(step: Step): string {
  return [step.command, ...step.args].join(" ");
}

function countSteps(phases: Phase[]): number {
  return phases.reduce((total, phase) => {
    if (!isParallelPhase(phase)) return total + 1;
    return total + phase.parallel.reduce((branchTotal, item) => branchTotal + item.steps.length, 0);
  }, 0);
}

async function runStep(step: Step, progress: RunProgress, context?: string): Promise<number> {
  const index = progress.nextStep;
  progress.nextStep += 1;
  const started = performance.now();
  const label = context ? `${context} / ${step.label}` : step.label;
  console.log(`[update] step ${index}/${progress.totalSteps} start: ${label} :: ${commandText(step)}`);
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
  console.log(`[update] step ${index}/${progress.totalSteps} done: ${label} duration=${formatDuration(elapsed)}`);
  return elapsed;
}

async function runBranch(item: StepBranch, progress: RunProgress): Promise<number> {
  const started = performance.now();
  console.log(`[update] branch start: ${item.label} steps=${item.steps.length}`);
  let branchRuntime = 0;
  for (const step of item.steps) {
    branchRuntime += await runStep(step, progress, item.label);
  }
  const elapsed = performance.now() - started;
  console.log(`[update] branch done: ${item.label} duration=${formatDuration(elapsed)} step_runtime=${formatDuration(branchRuntime)}`);
  return branchRuntime;
}

async function runPhase(phase: Phase, progress: RunProgress): Promise<number> {
  if (!isParallelPhase(phase)) return runStep(phase, progress);

  const started = performance.now();
  console.log(`[update] phase start: ${phase.label} branches=${phase.parallel.length}`);
  const results = await Promise.allSettled(phase.parallel.map((item) => runBranch(item, progress)));
  const branchRuntime = results.reduce((total, result) => total + (result.status === "fulfilled" ? result.value : 0), 0);
  const elapsed = performance.now() - started;
  const failed = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
  console.log(
    `[update] phase ${failed ? "failed" : "done"}: ${phase.label} duration=${formatDuration(elapsed)} branch_runtime=${formatDuration(branchRuntime)}`,
  );
  if (failed) throw failed.reason;
  return branchRuntime;
}

export async function runUpdateGroup(group: UpdateGroup): Promise<void> {
  const phases = GROUP_PHASES[group];
  const totalSteps = countSteps(phases);
  const started = performance.now();
  console.log(`[update] group=${group} steps=${totalSteps} phases=${phases.length} started_at=${new Date().toISOString()}`);
  let workRuntime = 0;
  const progress: RunProgress = { nextStep: 1, totalSteps };
  for (const phase of phases) {
    workRuntime += await runPhase(phase, progress);
  }
  const elapsed = performance.now() - started;
  console.log(
    `[update] group=${group} complete total=${formatDuration(elapsed)} work_runtime=${formatDuration(workRuntime)} finished_at=${new Date().toISOString()}`,
  );
}

function parseGroup(value: string | undefined): UpdateGroup {
  if (value === "weekly" || value === "monthly" || value === "other" || value === "all" || value === "power-dfo") return value;
  throw new Error(`Unknown update group ${value ?? ""}. Use weekly, monthly, other, all, or power-dfo.`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runUpdateGroup(parseGroup(process.argv[2] ?? "all")).catch((error: unknown) => {
    console.error(`[update] failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}
