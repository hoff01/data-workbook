import { spawnSync } from "node:child_process";
import { access, cp, mkdir, mkdtemp, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const MANIFEST_PATH = join(ROOT, "config", "legacy_feature_overlay.json");
const NODE_MODULES = join(ROOT, "node_modules");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const pythonCommand = process.env.US_BALANCES_PYTHON || (process.platform === "win32" ? "python" : "python3");

function run(command, args, cwd, options = {}) {
  const result = spawnSync(command, args, {
    cwd,
    env: { ...process.env, FORCE_COLOR: "0", ...options.env },
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = options.capture
      ? `\n${String(result.stdout || "")}\n${String(result.stderr || "")}`
      : "";
    throw new Error(`${command} ${args.join(" ")} failed with exit code ${result.status}.${detail}`);
  }
  return String(result.stdout || "").trim();
}

async function copyOverlayFile(relativePath, targetRoot) {
  const source = join(ROOT, relativePath);
  const destination = join(targetRoot, relativePath);
  await access(source);
  await mkdir(dirname(destination), { recursive: true });
  await cp(source, destination, { force: true });
}

const manifest = JSON.parse(await readFile(MANIFEST_PATH, "utf8"));
if (manifest.schema_version !== 1) throw new Error("Unsupported legacy feature overlay manifest version.");
if (!Array.isArray(manifest.runtime_files) || !manifest.runtime_files.length) {
  throw new Error("The legacy feature overlay has no runtime files.");
}
if (!Array.isArray(manifest.validation_files)) {
  throw new Error("The legacy feature overlay validation file list is missing.");
}

await access(NODE_MODULES);
run("git", ["cat-file", "-e", `${manifest.baseline_commit}^{commit}`], ROOT);

const temporaryRoot = await mkdtemp(join(tmpdir(), "us-balances-legacy-overlay-"));
const legacyRoot = join(temporaryRoot, "legacy-project");
const archivePath = join(temporaryRoot, "legacy-project.tar");
const keepTemporary = process.env.US_BALANCES_KEEP_LEGACY_OVERLAY === "1";

try {
  await mkdir(legacyRoot, { recursive: true });
  run("git", ["archive", "--format=tar", `--output=${archivePath}`, manifest.baseline_commit], ROOT);
  run("tar", ["-xf", archivePath, "-C", legacyRoot], ROOT);

  const overlayFiles = [...new Set([...manifest.runtime_files, ...manifest.validation_files])];
  for (const relativePath of overlayFiles) await copyOverlayFile(relativePath, legacyRoot);
  await symlink(NODE_MODULES, join(legacyRoot, "node_modules"), process.platform === "win32" ? "junction" : "dir");

  run(npmCommand, ["run", "build:balances"], legacyRoot);
  run(npmCommand, ["run", "typecheck"], legacyRoot);
  run(npmCommand, ["run", "test:balance-adjustments"], legacyRoot);
  run(npmCommand, ["run", "test:dashboard-runner"], legacyRoot);
  run(pythonCommand, ["tests/test_kpler_padd1_eia_split.py"], legacyRoot);
  run(npmCommand, ["run", "verify:dashboard"], legacyRoot);
  run(npmCommand, ["run", "validate"], legacyRoot);
  run(npmCommand, ["run", "verify:windows"], legacyRoot);

  const baselineSubject = run(
    "git",
    ["show", "-s", "--format=%h %s", manifest.baseline_commit],
    ROOT,
    { capture: true },
  );
  console.log(
    `PASS legacy feature overlay: ${overlayFiles.length} source/config/test files copied onto ${baselineSubject}; old datasets and user state were preserved.`,
  );
} finally {
  if (keepTemporary) {
    console.log(`Legacy overlay test directory retained: ${legacyRoot}`);
  } else {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
}
