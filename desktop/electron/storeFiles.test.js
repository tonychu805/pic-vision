// Two things about the store files on disk, both of which were asserted
// by a human reading the code and turned out to be false (2026-09-07).
//
// 1. The hardened-file list matches the stores that actually exist. It
//    named a schedules.json nothing creates, and would have silently
//    skipped a store added later -- no chmod repair, no plaintext
//    migration, no failure.
//
// 2. Owner-only permissions SURVIVE a write. The first attempt chmod-ed
//    the files at startup and stopped there. conf writes atomically (temp
//    file, rename), so that chmod lasted until the app's next write --
//    seconds, for activityLog.json. This is the paired assertion the
//    redaction incident is supposed to have taught us to write: proving
//    the lock was applied is not proving it holds.
//
// Static plus a real filesystem round trip; no Electron.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Conf from "conf";
import { LEGACY_STORE_FILES, STORE_FILES } from "./storeFiles.js";

const ROOT = path.dirname(fileURLToPath(import.meta.url));

// Every `new Store({ name: "x" })` under electron/, as "x.json".
function storeFilesInSource() {
  const found = new Set();
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== "node_modules") walk(full);
      } else if (entry.name.endsWith(".js") && !entry.name.endsWith(".test.js")) {
        for (const m of readFileSync(full, "utf8").matchAll(/new Store\(\{[^}]*name:\s*"([^"]+)"/g)) {
          found.add(`${m[1]}.json`);
        }
      }
    }
  };
  walk(ROOT);
  return found;
}

test("the hardened-file list matches the stores that exist", () => {
  const actual = storeFilesInSource();
  assert.ok(actual.size > 0, "found no `new Store({ name })` call sites -- did the pattern change?");

  const missing = [...actual].filter((f) => !STORE_FILES.includes(f));
  assert.deepEqual(
    missing,
    [],
    `These stores exist but aren't in STORE_FILES, so secureStoreFiles() skips them ` +
      `-- no permission repair and no plaintext migration, silently:\n  ${missing.join("\n  ")}`,
  );

  const stale = STORE_FILES.filter((f) => !actual.has(f));
  assert.deepEqual(
    stale,
    [],
    `STORE_FILES names files no store creates. If the store was removed, move the ` +
      `filename to LEGACY_STORE_FILES -- copies are still sitting in userData on every ` +
      `machine that ran the older build, and still need the repair pass:\n  ${stale.join("\n  ")}`,
  );

  // A legacy entry that matches a live store is just a duplicate, and
  // would get chmod-ed twice while claiming to be a leftover.
  const notLegacy = LEGACY_STORE_FILES.filter((f) => actual.has(f));
  assert.deepEqual(notLegacy, [], `Listed as legacy but a store still creates it:\n  ${notLegacy.join("\n  ")}`);
});

test("every store asks for owner-only permissions", () => {
  const walk = (dir, out = []) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== "node_modules") walk(full, out);
      } else if (entry.name.endsWith(".js") && !entry.name.endsWith(".test.js")) {
        // Requires a quoted name, so prose in a comment mentioning the
        // call shape doesn't register as a call site.
        for (const m of readFileSync(full, "utf8").matchAll(/new Store\(\{[^}]*name:\s*"[^"]+"[^}]*\}\)/g)) {
          out.push({ file: path.relative(ROOT, full), call: m[0] });
        }
      }
    }
    return out;
  };

  for (const { file, call } of walk(ROOT)) {
    assert.match(
      call,
      /configFileMode:\s*0o600/,
      `${file} creates a store without configFileMode: 0o600. conf defaults to 0o666, ` +
        `so the file lands readable by every account on the machine -- and a startup chmod ` +
        `does not fix it, because conf's atomic write replaces the inode.\n  ${call}`,
    );
  }
});

// The one that would have caught the original mistake: not "we set 0600"
// but "0600 is still there after the app writes again".
//
// Uses conf directly because electron-store is stubbed out by
// electron-stub-loader.mjs, so the real one can't run in this harness at
// all. conf is what actually writes the file (electron-store subclasses it
// and forwards its options verbatim), so this tests the mechanism that
// matters. Checked once by hand against the real electron-store outside the
// harness, 2026-09-07: default 664, with the option 600 after three writes.
test("owner-only permissions survive repeated writes", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "picvision-store-"));
  try {
    const store = new Conf({ cwd: dir, configName: "modes", projectName: "pic-vision", configFileMode: 0o600 });
    store.set("first", 1);
    assert.equal(statSync(store.path).mode & 0o777, 0o600, "wrong mode on the first write");
    // conf's first write and its subsequent writes take different paths;
    // it was the SECOND one that undid the old chmod-at-startup fix.
    store.set("second", 2);
    assert.equal(statSync(store.path).mode & 0o777, 0o600, "a later write widened the mode again");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
