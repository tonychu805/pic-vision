// Loads every main-process module for real, with Electron stubbed.
//
// Catches three things `node --check` cannot, all of which have actually
// happened here: a missing named export (an edit removed six from
// capture.js and the app wouldn't start), a circular import that fails to
// resolve (cloud.js -> pipeline.js -> consoleApi.js -> cloud.js), and
// anything that throws at module scope.
//
// Run via `npm test`, which registers electron-stub-loader.mjs.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));

function modules(dir = ROOT) {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return modules(full);
    return name.endsWith(".js") && !name.endsWith(".test.js") ? [full] : [];
  });
}

test("every main-process module imports cleanly", async () => {
  for (const file of modules()) {
    await assert.doesNotReject(
      () => import(file),
      `${path.relative(ROOT, file)} failed to import`,
    );
  }
});

test("the cloud <-> pipeline circular import resolves both ways", async () => {
  // cloud.js needs runCloudJob to send a scheduled recording; pipeline.js
  // reaches back for the stored connection through consoleApi.js. Safe only
  // because both are hoisted function declarations -- worth pinning, since
  // converting either to a const arrow would break it at load time.
  const cloud = await import("./cloud.js");
  const pipeline = await import("./pipeline.js");
  assert.equal(typeof cloud.getCloudConnection, "function");
  assert.equal(typeof pipeline.runCloudJob, "function");
});
