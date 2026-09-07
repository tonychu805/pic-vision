// Every IPC handler that accepts an OBJECT from the renderer must be
// classified here, deliberately.
//
// The renderer's copy of a stored entity is redacted (ADR-088:
// publicCamera() strips `password` and stars credentials out of
// `streamUri`). If a handler then takes that object back and uses it as
// though it were complete, the secrets are simply gone -- which is exactly
// what shipped on 2026-09-07: every configured camera failed its own
// connection check with a 401, while live view kept working because it
// takes an ID and looks the camera up in main instead.
//
// The safe shape is `liveview:start`'s: take an id, read the real record
// in main. Where a handler genuinely must take an object -- the add flow,
// where the camera isn't stored yet and the credentials were just typed --
// that's fine, and it's recorded below as such.
//
// This test does NOT try to infer intent from the code. It requires each
// object-taking channel to appear in one of the two lists, so adding a new
// one fails until someone decides which it is. That's the point: the gap
// this closes isn't a known bug, it's the *next* instance of the class.
//
// Static, like imports.test.js and packaged-paths.test.js -- reads the
// source rather than running Electron.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));

// Channels that receive a STORED entity from the renderer, and therefore
// must restore its secrets in main before using it.
const RESTORES_SECRETS = new Set([
  // Takes a camera the renderer got from cameras:list -- i.e. redacted.
  // Calls withStoredSecrets() first. Without that it authenticates with
  // an undefined password (the 2026-09-07 regression).
  "cameras:testConnection",
]);

// Channels whose object argument is freshly-typed input for something not
// yet stored. Nothing to restore: the credentials in hand are the only
// ones that exist, and are exactly what needs verifying.
const FRESH_INPUT_ONLY = new Set([
  "cameras:add", // the ONVIF add form
  "cameras:addRtsp", // the RTSP fallback form
  "cameras:addSampleClip", // a local file, no credentials at all
  "cameras:probeRtspFallback", // probes typed credentials before saving
  // { timeout } from the Scan button. No entity at all, stored or
  // otherwise -- found by this test on its first run, having been missed
  // by a manual audit that grepped for `config` and not `options`.
  "cameras:discover",
]);

// Parameter names that indicate an object rather than a scalar id. A
// handler taking `id`/`cameraId`/`url` can't carry a stripped secret.
const OBJECT_PARAM = /^(config|camera|options|settings|payload|data|body)$/;

function handlerSignatures() {
  const source = readFileSync(path.join(ROOT, "main.js"), "utf8");
  const pattern = /ipcMain\.handle\(\s*"([^"]+)"\s*,\s*(?:async\s*)?\(([^)]*)\)/g;
  const found = [];
  let match;
  while ((match = pattern.exec(source)) !== null) {
    const channel = match[1];
    const params = match[2]
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean)
      .slice(1); // drop the leading _event
    found.push({ channel, params });
  }
  return found;
}

test("every object-taking IPC handler is classified", () => {
  const handlers = handlerSignatures();
  assert.ok(handlers.length > 10, `only found ${handlers.length} handlers -- did main.js's shape change?`);

  const unclassified = handlers
    .filter(({ params }) => params.some((p) => OBJECT_PARAM.test(p)))
    .map(({ channel }) => channel)
    .filter((channel) => !RESTORES_SECRETS.has(channel) && !FRESH_INPUT_ONLY.has(channel));

  assert.deepEqual(
    unclassified,
    [],
    `These IPC handlers take an object from the renderer and aren't classified in ` +
      `ipc-contract.test.js:\n  ${unclassified.join("\n  ")}\n\n` +
      `The renderer's copy of a stored entity has its secrets stripped (ADR-088), so an ` +
      `object handed back from there is incomplete. Decide which this is:\n` +
      `  - it receives a STORED entity -> call withStoredSecrets() and add it to RESTORES_SECRETS\n` +
      `  - it receives freshly-typed input -> add it to FRESH_INPUT_ONLY\n` +
      `  - neither -> prefer taking an id and reading the record in main (see liveview:start)`,
  );
});

test("handlers that receive a stored entity actually restore its secrets", () => {
  const source = readFileSync(path.join(ROOT, "main.js"), "utf8");

  for (const channel of RESTORES_SECRETS) {
    // The handler body, from its channel name to the next handler.
    const start = source.indexOf(`ipcMain.handle("${channel}"`);
    assert.notEqual(start, -1, `${channel} is listed here but no longer exists in main.js`);
    const next = source.indexOf("ipcMain.handle(", start + 1);
    const body = source.slice(start, next === -1 ? source.length : next);

    assert.match(
      body,
      /withStoredSecrets\(/,
      `${channel} is classified as receiving a stored entity but never calls withStoredSecrets(). ` +
        `It will authenticate with an undefined password -- the 2026-09-07 regression.`,
    );
  }
});

test("the classification lists don't rot", () => {
  // A channel removed from main.js but left listed here would quietly
  // weaken the first test (fewer things to check).
  const source = readFileSync(path.join(ROOT, "main.js"), "utf8");
  for (const channel of [...RESTORES_SECRETS, ...FRESH_INPUT_ONLY]) {
    assert.ok(
      source.includes(`ipcMain.handle("${channel}"`),
      `${channel} is classified in ipc-contract.test.js but no longer exists in main.js -- remove it`,
    );
  }
});
