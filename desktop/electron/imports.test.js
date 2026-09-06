// Checks that every named import between our own modules actually exists.
//
// Written after breaking the app for real: an edit to capture.js removed six
// exports (the whole recording subsystem) as collateral, and nothing caught
// it. `node --check` passes -- the file is perfectly valid JavaScript -- and
// the unit tests don't import these modules, because most of them pull in
// Electron and can't run outside it. The failure only surfaced when the app
// was launched and the main process died on
// "does not provide an export named 'grabFrameFromFile'".
//
// This is deliberately static: it reads the files rather than importing
// them, so it covers modules that need Electron without needing Electron.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));

function sourceFiles(dir = ROOT) {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return name.endsWith(".js") && !name.endsWith(".test.js") ? [full] : [];
  });
}

// `export function x`, `export async function x`, `export const x`,
// `export { a, b }`. Enough for this codebase; no re-exports are used.
function exportsOf(file) {
  const src = readFileSync(file, "utf8");
  const names = new Set();
  for (const m of src.matchAll(/^export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)/gm)) {
    names.add(m[1]);
  }
  for (const m of src.matchAll(/^export\s*\{([^}]*)\}/gm)) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/).pop().trim();
      if (name) names.add(name);
    }
  }
  return names;
}

test("every named import from a local module actually exists there", () => {
  const missing = [];
  for (const file of sourceFiles()) {
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(/^import\s*\{([^}]*)\}\s*from\s*["'](\.[^"']*)["']/gm)) {
      const target = path.resolve(path.dirname(file), m[2]);
      let available;
      try {
        available = exportsOf(target);
      } catch {
        missing.push(`${path.relative(ROOT, file)} imports from missing file ${m[2]}`);
        continue;
      }
      for (const part of m[1].split(",")) {
        const name = part.trim().split(/\s+as\s+/)[0].trim();
        if (name && !available.has(name)) {
          missing.push(`${path.relative(ROOT, file)} imports '${name}' from ${m[2]}, which doesn't export it`);
        }
      }
    }
  }
  assert.deepEqual(missing, [], `broken imports:\n  ${missing.join("\n  ")}`);
});
