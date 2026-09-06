// Every file the main process reaches for at runtime must actually be in
// the packaged app.
//
// Written after shipping a build that launched to nothing (2026-09-07):
// `app.dock.setIcon(.../build/icon.png)` ran unguarded on macOS, but
// `build/` isn't in package.json's build.files, so the path didn't exist
// inside the .app. It threw before createWindow(), and the app started
// with no window while staying alive with a Dock icon -- indistinguishable
// from a window that opened and drew nothing, because the window is
// frameless and transparent.
//
// Nothing caught it: the CI build passed, the asar contained everything it
// claimed to, and the failure only existed in a packaged app on macOS.
//
// Static, like imports.test.js -- it reads the source rather than running
// Electron, so it covers main-process code that can't be imported outside
// Electron.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PKG = JSON.parse(readFileSync(path.join(ROOT, "..", "package.json"), "utf8"));

// Top-level directories build.files actually ships, e.g. "dist/**/*" -> "dist".
const PACKAGED = new Set(
  PKG.build.files.map((pattern) => pattern.split("/")[0]).filter((seg) => seg && !seg.includes("*")),
);

function mainProcessSources() {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(js|cjs)$/.test(entry.name) && !entry.name.endsWith(".test.js")) files.push(full);
    }
  };
  walk(ROOT);
  return files;
}

test("runtime paths escaping electron/ point at packaged directories", () => {
  // path.join(__dirname, "..", "<dir>", ...) -- the shape used to reach
  // out of electron/ into the app root.
  const escaping = /path\.join\(__dirname,\s*"\.\.",\s*"([^"]+)"/g;

  for (const file of mainProcessSources()) {
    const source = readFileSync(file, "utf8");
    const lines = source.split("\n");

    for (const [index, line] of lines.entries()) {
      escaping.lastIndex = 0;
      let match;
      while ((match = escaping.exec(line)) !== null) {
        const dir = match[1];
        if (PACKAGED.has(dir)) continue;

        // Not packaged: only legitimate behind an isDev guard, and the
        // guard has to be close enough to actually cover this line.
        const context = lines.slice(Math.max(0, index - 6), index + 1).join("\n");
        assert.ok(
          /\bisDev\b/.test(context),
          `${path.relative(ROOT, file)}:${index + 1} reads from "${dir}/", which build.files does not ` +
            `package (${[...PACKAGED].join(", ")}), and no isDev guard is in scope. ` +
            `In a packaged app this path does not exist.`,
        );
      }
    }
  }
});

test("the packaged-file list still covers the renderer and main process", () => {
  // A guard on the guard: if someone narrows build.files, the test above
  // starts passing for the wrong reason (fewer things to check).
  assert.ok(PACKAGED.has("dist"), "the renderer bundle must be packaged");
  assert.ok(PACKAGED.has("electron"), "the main process must be packaged");
});
