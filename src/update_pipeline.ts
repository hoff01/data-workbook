import { spawn } from "node:child_process";
import { performance } from "node:perf_hooks";

type UpdateGroup = "weekly" | "monthly" | "other" | "all";

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

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";

function npmStep(label: string, script: string): Step {
  return { label, command: npmCommand, args: ["run", script] };
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
    npmStep("weekly EIA pull", "weekly:raw"),
    npmStep("weekly export files", "export:weekly:clean"),
    npmStep("clean public EIA outputs", "clean:eia"),
    npmStep("Kpler PADD 1 EIA split", "kpler:padd1:eia"),
    npmStep("weekly freshness check", "verify:weekly"),
    npmStep("rebuild balance dashboards", "build:balances"),
    npmStep("dashboard freshness check", "verify:dashboard"),
  ],
  monthly: [
    npmStep("monthly EIA pull", "monthly"),
    npmStep("monthly export files", "export:monthly"),
    npmStep("monthly bulk series inventory", "export:bulk-series"),
    npmStep("PADD 1 distillate split", "padd1"),
    npmStep("clean public EIA outputs", "clean:eia"),
    npmStep("monthly freshness check", "verify:monthly"),
    npmStep("rebuild balance dashboards", "build:balances"),
    npmStep("dashboard freshness check", "verify:dashboard"),
  ],
  other: [
    parallelPhase("independent context refreshes", [
      branch("Kpler package", [npmStep("Kpler flow package", "kpler"), npmStep("Kpler PADD 1 EIA split", "kpler:padd1:eia")]),
      branch("capacity", [npmStep("capacity refresh", "capacity"), npmStep("refinery unit capacity refresh", "capacity:refineries")]),
      branch("power DFO", [npmStep("power DFO daily refresh", "power:dfo"), npmStep("power DFO hourly forecast", "power:dfo:hourly")]),
    ]),
    npmStep("validate clean outputs", "validate"),
    npmStep("data health check", "data:check"),
    npmStep("rebuild balance dashboards", "build:balances"),
    npmStep("dashboard freshness check", "verify:dashboard"),
  ],
  all: [
    parallelPhase("EIA source refreshes", [
      branch("weekly EIA", [npmStep("weekly EIA pull", "weekly:raw")]),
      branch("monthly EIA", [npmStep("monthly EIA pull", "monthly")]),
    ]),
    npmStep("weekly/monthly export files", "export:headers:clean"),
    npmStep("monthly bulk series inventory", "export:bulk-series"),
    npmStep("PADD 1 distillate split", "padd1"),
    npmStep("clean public EIA outputs", "clean:eia"),
    parallelPhase("EIA freshness checks", [
      branch("weekly freshness", [npmStep("weekly freshness check", "verify:weekly")]),
      branch("monthly freshness", [npmStep("monthly freshness check", "verify:monthly")]),
    ]),
    parallelPhase("independent context refreshes", [
      branch("Kpler package", [npmStep("Kpler flow package", "kpler"), npmStep("Kpler PADD 1 EIA split", "kpler:padd1:eia")]),
      branch("capacity", [npmStep("capacity refresh", "capacity"), npmStep("refinery unit capacity refresh", "capacity:refineries")]),
      branch("power DFO", [npmStep("power DFO daily refresh", "power:dfo"), npmStep("power DFO hourly forecast", "power:dfo:hourly")]),
    ]),
    npmStep("validate clean outputs", "validate"),
    npmStep("data health check", "data:check"),
    npmStep("rebuild balance dashboards", "build:balances"),
    npmStep("dashboard freshness check", "verify:dashboard"),
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
      cwd: process.cwd(),
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
  if (value === "weekly" || value === "monthly" || value === "other" || value === "all") return value;
  throw new Error(`Unknown update group ${value ?? ""}. Use weekly, monthly, other, or all.`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runUpdateGroup(parseGroup(process.argv[2] ?? "all")).catch((error: unknown) => {
    console.error(`[update] failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}
