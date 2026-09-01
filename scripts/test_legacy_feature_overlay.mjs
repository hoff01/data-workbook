import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  access,
  cp,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  readlink,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
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

async function addPathToHash(hash, absolutePath, logicalPath) {
  const metadata = await lstat(absolutePath);
  if (metadata.isDirectory()) {
    hash.update(`directory\0${logicalPath}\0`);
    const entries = (await readdir(absolutePath)).sort((left, right) => left.localeCompare(right));
    for (const entry of entries) {
      await addPathToHash(hash, join(absolutePath, entry), join(logicalPath, entry));
    }
    return;
  }
  if (metadata.isSymbolicLink()) {
    hash.update(`symlink\0${logicalPath}\0${await readlink(absolutePath)}\0`);
    return;
  }
  hash.update(`file\0${logicalPath}\0`);
  hash.update(await readFile(absolutePath));
  hash.update("\0");
}

async function preservedPathDigest(targetRoot, relativePath) {
  const hash = createHash("sha256");
  try {
    await addPathToHash(hash, join(targetRoot, relativePath), relativePath);
    return hash.digest("hex");
  } catch (error) {
    if (error && typeof error === "object" && error.code === "ENOENT") return "missing";
    throw error;
  }
}

async function preservedStateSnapshot(targetRoot, relativePaths) {
  const snapshot = {};
  for (const relativePath of relativePaths) {
    snapshot[relativePath] = await preservedPathDigest(targetRoot, relativePath);
  }
  return snapshot;
}

function canonicalJson(value) {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort((left, right) => left.localeCompare(right))
      .map((key) => [key, canonicalJson(value[key])]),
  );
}

function removeJsonField(value, fieldPath) {
  const parts = fieldPath.split(".").filter(Boolean);
  let current = value;
  for (const part of parts.slice(0, -1)) {
    if (!current || typeof current !== "object") return;
    current = current[part];
  }
  if (current && typeof current === "object" && parts.length) delete current[parts.at(-1)];
}

async function semanticJsonSnapshot(targetRoot, definitions) {
  const snapshot = {};
  for (const [relativePath, volatileFields] of Object.entries(definitions || {})) {
    const value = JSON.parse(await readFile(join(targetRoot, relativePath), "utf8"));
    for (const fieldPath of volatileFields) removeJsonField(value, fieldPath);
    snapshot[relativePath] = createHash("sha256")
      .update(JSON.stringify(canonicalJson(value)))
      .digest("hex");
  }
  return snapshot;
}

function assertPreservedState(before, after, stage) {
  const changed = Object.keys(before).filter((relativePath) => before[relativePath] !== after[relativePath]);
  if (changed.length) {
    throw new Error(`Legacy projection or override state changed ${stage}: ${changed.join(", ")}`);
  }
}

async function ensurePreservationFixtures(targetRoot, fixtures) {
  for (const [relativePath, contents] of Object.entries(fixtures || {})) {
    const destination = join(targetRoot, relativePath);
    try {
      await access(destination);
    } catch {
      await mkdir(dirname(destination), { recursive: true });
      await writeFile(destination, String(contents), "utf8");
    }
  }
}

const manifest = JSON.parse(await readFile(MANIFEST_PATH, "utf8"));
if (manifest.schema_version !== 1) throw new Error("Unsupported legacy feature overlay manifest version.");
if (!Array.isArray(manifest.runtime_files) || !manifest.runtime_files.length) {
  throw new Error("The legacy feature overlay has no runtime files.");
}
if (!Array.isArray(manifest.validation_files)) {
  throw new Error("The legacy feature overlay validation file list is missing.");
}
if (!Array.isArray(manifest.preserve_from_target) || !manifest.preserve_from_target.length) {
  throw new Error("The legacy feature overlay preservation list is missing.");
}
if (!manifest.preserve_semantic_json || typeof manifest.preserve_semantic_json !== "object") {
  throw new Error("The legacy feature overlay semantic preservation map is missing.");
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
  await ensurePreservationFixtures(legacyRoot, manifest.test_preservation_fixtures);
  const preservedBeforeOverlay = await preservedStateSnapshot(legacyRoot, manifest.preserve_from_target);
  const semanticBeforeOverlay = await semanticJsonSnapshot(legacyRoot, manifest.preserve_semantic_json);

  const overlayFiles = [...new Set([...manifest.runtime_files, ...manifest.validation_files])];
  for (const relativePath of overlayFiles) await copyOverlayFile(relativePath, legacyRoot);
  assertPreservedState(
    preservedBeforeOverlay,
    await preservedStateSnapshot(legacyRoot, manifest.preserve_from_target),
    "while copying the feature files",
  );
  assertPreservedState(
    semanticBeforeOverlay,
    await semanticJsonSnapshot(legacyRoot, manifest.preserve_semantic_json),
    "while copying the feature files",
  );
  await symlink(NODE_MODULES, join(legacyRoot, "node_modules"), process.platform === "win32" ? "junction" : "dir");

  run(npmCommand, ["run", "build:balances"], legacyRoot);
  run(npmCommand, ["run", "typecheck"], legacyRoot);
  run(npmCommand, ["run", "test:balance-adjustments"], legacyRoot);
  run(npmCommand, ["run", "test:dashboard-runner"], legacyRoot);
  run(pythonCommand, ["tests/test_kpler_padd1_eia_split.py"], legacyRoot);
  run(npmCommand, ["run", "verify:dashboard"], legacyRoot);
  run(npmCommand, ["run", "validate"], legacyRoot);
  run(npmCommand, ["run", "verify:windows"], legacyRoot);
  assertPreservedState(
    preservedBeforeOverlay,
    await preservedStateSnapshot(legacyRoot, manifest.preserve_from_target),
    "during rebuild and validation",
  );
  assertPreservedState(
    semanticBeforeOverlay,
    await semanticJsonSnapshot(legacyRoot, manifest.preserve_semantic_json),
    "during rebuild and validation",
  );

  const baselineSubject = run(
    "git",
    ["show", "-s", "--format=%h %s", manifest.baseline_commit],
    ROOT,
    { capture: true },
  );
  console.log(
    `PASS legacy feature overlay: ${overlayFiles.length} source/config/test files copied onto ${baselineSubject}; ${manifest.preserve_from_target.length} user-state paths remained byte-for-byte unchanged and ${Object.keys(manifest.preserve_semantic_json).length} generated companion remained semantically unchanged.`,
  );
} finally {
  if (keepTemporary) {
    console.log(`Legacy overlay test directory retained: ${legacyRoot}`);
  } else {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
}
